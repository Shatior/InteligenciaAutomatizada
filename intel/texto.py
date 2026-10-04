"""Utilidades de texto: limpieza, normalización y huellas para deduplicar."""
import hashlib
import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_RASTREO = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_|cmpid|ocid|smid|ncid|at_|s_cid)", re.I)
_ETIQUETA = re.compile(r"<[^>]+>")
_ESPACIOS = re.compile(r"\s+")


def url_canonica(url: str) -> str:
    """Quita fragmento, parámetros de rastreo y barra final para comparar URLs."""
    p = urlsplit(url.strip())
    consulta = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _RASTREO.match(k)]
    ruta = p.path.rstrip("/") or "/"
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return urlunsplit((p.scheme.lower() or "https", host, ruta, urlencode(consulta), ""))


def huella(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()


def huella_url(url: str) -> str:
    return huella(url_canonica(url))


def sin_html(valor: str | None) -> str:
    if not valor:
        return ""
    limpio = _ETIQUETA.sub(" ", valor)
    return _ESPACIOS.sub(" ", html.unescape(limpio)).strip()


def normalizar(valor: str) -> str:
    """Minúsculas, sin acentos ni puntuación: base para comparar títulos y citas."""
    s = unicodedata.normalize("NFKD", valor or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9ñ ]+", " ", s)
    return _ESPACIOS.sub(" ", s).strip()


def huella_titulo(titulo: str | None) -> str | None:
    n = normalizar(titulo or "")
    if len(n) < 20:  # títulos demasiado cortos no sirven para deduplicar
        return None
    return huella(n)


def contar_palabras(valor: str | None) -> int:
    return len(re.findall(r"\w+", valor or "", flags=re.UNICODE))


def recortar(valor: str | None, limite: int) -> str:
    valor = valor or ""
    if len(valor) <= limite:
        return valor
    corte = valor[:limite]
    ultimo = corte.rfind(". ")
    return (corte[: ultimo + 1] if ultimo > limite * 0.6 else corte) + " […]"


def cita_en_texto(cita: str, texto: str) -> bool:
    """¿La cita literal aparece en el texto de la fuente?

    Primero coincidencia exacta normalizada; si falla, exige que al menos el 80 %
    de los grupos de cinco palabras de la cita estén en el texto.
    """
    c, t = normalizar(cita), normalizar(texto)
    if not c or not t:
        return False
    if c in t:
        return True
    palabras = c.split()
    if len(palabras) < 6:
        return False
    grupos = [" ".join(palabras[i : i + 5]) for i in range(len(palabras) - 4)]
    aciertos = sum(1 for g in grupos if g in t)
    return aciertos / len(grupos) >= 0.8


_NUMERO = re.compile(r"\d[\d.,]*\d|\d")


def numeros(valor: str | None) -> set[str]:
    """Cifras de un texto, sin separadores, para cotejar borrador contra dossier."""
    resultado = set()
    for m in _NUMERO.findall(valor or ""):
        digitos = re.sub(r"[.,]", "", m)
        if digitos:
            resultado.add(digitos.lstrip("0") or "0")
    return resultado
