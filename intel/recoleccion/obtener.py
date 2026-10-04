"""Obtención de páginas por niveles con Scrapling.

Nivel 1 (http):      petición HTTP con huella de navegador. Barata; cubre casi todo.
Nivel 2 (navegador): Chromium completo para páginas que se pintan con JavaScript.
Nivel 3 (sigilo):    navegador sigiloso que resuelve Cloudflare. Solo se usa en fuentes
                     marcadas `sigilo: true` en el registro: es una decisión por fuente.

Los PDF siguen su propia vía (descarga directa y PyMuPDF).
"""
import logging
import threading
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
import trafilatura

from .. import config

log = logging.getLogger("intel.obtener")


def _silenciar_scrapling() -> None:
    """Scrapling instala su propio registro a nivel INFO al importarse: una línea por petición."""
    import importlib

    importlib.import_module("scrapling")
    registro = logging.getLogger("scrapling")
    registro.setLevel(logging.WARNING)
    registro.propagate = False


_silenciar_scrapling()

_BLOQUEO = {401, 403, 406, 429, 503}
_MARCAS_BLOQUEO = ("just a moment", "cf-chl", "enable javascript", "attention required", "captcha", "access denied")
_MIN_TEXTO = 500

_candado_navegador = threading.Lock()
_usos_navegador = 0
_navegador_roto = False


@dataclass
class Pagina:
    texto: str = ""
    metodo: str = ""
    titulo: str | None = None
    fecha: str | None = None
    html: str = ""
    error: str | None = None
    intentos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.texto) >= _MIN_TEXTO


def reiniciar_cuota_navegador() -> None:
    global _usos_navegador
    _usos_navegador = 0


def _es_pdf(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf")


def _texto_pdf(datos: bytes) -> str:
    import fitz  # PyMuPDF

    with fitz.open(stream=datos, filetype="pdf") as doc:
        paginas = [p.get_text("text") for p in doc[:80]]
    return "\n".join(paginas).strip()


def _descargar_pdf(url: str) -> Pagina:
    try:
        r = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": config.AGENTE_FEEDS})
        r.raise_for_status()
        return Pagina(texto=_texto_pdf(r.content), metodo="pdf")
    except Exception as e:  # noqa: BLE001
        return Pagina(error=f"pdf: {e}"[:300])


def extraer(html: str, url: str) -> tuple[str, str | None, str | None]:
    """Texto principal, título y fecha de un HTML."""
    if not html:
        return "", None, None
    texto = trafilatura.extract(
        html, url=url, include_comments=False, include_tables=True, favor_recall=True, deduplicate=True
    ) or ""
    titulo = fecha = None
    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
        if meta:
            titulo, fecha = meta.title, meta.date
    except Exception:  # noqa: BLE001
        pass
    return texto.strip(), titulo, fecha


def _html_de(respuesta) -> str:
    contenido = getattr(respuesta, "html_content", None)
    if contenido:
        return str(contenido)
    cuerpo = getattr(respuesta, "body", b"")
    if isinstance(cuerpo, bytes):
        return cuerpo.decode(getattr(respuesta, "encoding", None) or "utf-8", errors="replace")
    return str(cuerpo or "")


def _parece_bloqueo(estado: int, html: str, texto: str) -> bool:
    if estado in _BLOQUEO:
        return True
    if len(texto) < _MIN_TEXTO:
        cabecera = html[:3000].lower()
        return any(m in cabecera for m in _MARCAS_BLOQUEO)
    return False


def html_http(url: str, timeout: int = 25):
    """Nivel 1. Devuelve (estado, html, cabeceras, cuerpo_bytes)."""
    from scrapling.fetchers import Fetcher

    r = Fetcher.get(url, stealthy_headers=True, follow_redirects=True, timeout=timeout, retries=1)
    cuerpo = getattr(r, "body", b"")
    return r.status, _html_de(r), dict(r.headers or {}), cuerpo if isinstance(cuerpo, bytes) else b""


def _html_navegador(url: str, sigilo: bool) -> tuple[int, str]:
    """Niveles 2 y 3. Un navegador a la vez y con cuota por pasada."""
    global _usos_navegador, _navegador_roto
    if not config.NAVEGADOR or _navegador_roto:
        raise RuntimeError("navegador desactivado")
    with _candado_navegador:
        if _usos_navegador >= config.MAX_NAVEGADOR_POR_PASADA:
            raise RuntimeError("cuota de navegador agotada en esta pasada")
        _usos_navegador += 1
        try:
            if sigilo:
                from scrapling.fetchers import StealthyFetcher

                r = StealthyFetcher.fetch(url, headless=True, solve_cloudflare=True, timeout=60000, block_ads=True)
            else:
                from scrapling.fetchers import DynamicFetcher

                r = DynamicFetcher.fetch(
                    url, headless=True, network_idle=True, disable_resources=True, timeout=45000, block_ads=True
                )
            return r.status, _html_de(r)
        except Exception as e:  # noqa: BLE001
            # Si el navegador no puede ni arrancar, se desactiva para no repetir el fallo en cada URL.
            if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
                _navegador_roto = True
                log.error("Chromium no disponible; se desactivan los niveles de navegador: %s", e)
            raise


def obtener(url: str, sigilo: bool = False, navegador: bool = True) -> Pagina:
    """Trae una página escalando de nivel solo cuando el anterior no basta."""
    if _es_pdf(url):
        return _descargar_pdf(url)

    pagina = Pagina()
    estado, html = 0, ""
    try:
        estado, html, cabeceras, cuerpo = html_http(url)
        tipo = str(cabeceras.get("content-type") or cabeceras.get("Content-Type") or "").lower()
        if "application/pdf" in tipo and cuerpo:
            return Pagina(texto=_texto_pdf(cuerpo), metodo="pdf")
        texto, titulo, fecha = extraer(html, url)
        pagina = Pagina(texto=texto, metodo="http", titulo=titulo, fecha=fecha, html=html)
        pagina.intentos.append(f"http:{estado}:{len(texto)}")
    except Exception as e:  # noqa: BLE001
        pagina.error = f"http: {e}"[:300]
        pagina.intentos.append("http:error")

    if pagina.ok and not _parece_bloqueo(estado, html, pagina.texto):
        return pagina
    if not navegador:
        if not pagina.ok and not pagina.error:
            pagina.error = f"texto insuficiente (HTTP {estado})"
        return pagina

    niveles = [("navegador", False)] + ([("sigilo", True)] if sigilo else [])
    for nombre, modo_sigilo in niveles:
        try:
            estado, html = _html_navegador(url, modo_sigilo)
            texto, titulo, fecha = extraer(html, url)
            pagina.intentos.append(f"{nombre}:{estado}:{len(texto)}")
            if len(texto) > len(pagina.texto):
                pagina.texto, pagina.metodo, pagina.html = texto, nombre, html
                pagina.titulo, pagina.fecha = titulo or pagina.titulo, fecha or pagina.fecha
            if pagina.ok and not _parece_bloqueo(estado, html, pagina.texto):
                pagina.error = None
                return pagina
        except Exception as e:  # noqa: BLE001
            pagina.intentos.append(f"{nombre}:error")
            if not pagina.error:
                pagina.error = f"{nombre}: {e}"[:300]

    if not pagina.ok and not pagina.error:
        pagina.error = f"texto insuficiente (HTTP {estado})"
    return pagina
