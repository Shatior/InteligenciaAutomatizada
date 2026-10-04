"""Recolección de fuentes sin feed: se lee la portada o el listado y se extraen enlaces.

Cada fuente declara en el registro un `patron` (expresión regular sobre la URL del
artículo). El título y la fecha se completan al traer el artículo.
"""
import logging
import re
from urllib.parse import urljoin, urlsplit

from ..texto import sin_html, url_canonica
from .obtener import html_http

log = logging.getLogger("intel.html")

_ENLACE = re.compile(r'<a\b[^>]*?href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', re.I | re.S)


def recolectar(fuente: dict) -> list[dict]:
    cfg = fuente.get("config") or {}
    patron = re.compile(cfg["patron"]) if cfg.get("patron") else None
    estado, html, _, _ = html_http(fuente["url"])
    if estado >= 400 or not html:
        if cfg.get("navegador"):
            from .obtener import _html_navegador

            estado, html = _html_navegador(fuente["url"], sigilo=bool(cfg.get("sigilo")))
        if estado >= 400 or not html:
            raise RuntimeError(f"HTTP {estado}")

    host = urlsplit(fuente["url"]).netloc.lower().removeprefix("www.")
    # Un mismo artículo suele enlazarse dos veces (imagen y titular): se conserva el título más largo.
    titulos: dict[str, tuple[str, str]] = {}
    for href, interior in _ENLACE.findall(html):
        url = urljoin(fuente["url"], href.strip())
        partes = urlsplit(url)
        if not partes.scheme.startswith("http"):
            continue
        if partes.netloc.lower().removeprefix("www.") != host:
            continue
        if patron and not patron.search(partes.path):
            continue
        if not patron and partes.path.count("/") < 2:
            continue
        clave = url_canonica(url)
        titulo = sin_html(interior)
        if clave not in titulos or len(titulo) > len(titulos[clave][1]):
            titulos[clave] = (url, titulo)

    items = [
        {
            "url": url,
            "titulo": titulo[:500] if len(titulo) >= 25 else None,
            "publicado": None,
            "resumen": "",
            "contenido": "",
        }
        for url, titulo in titulos.values()
    ]
    if not items:
        raise RuntimeError("ningún enlace coincide con el patrón")
    return items
