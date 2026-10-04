"""Recolección por RSS/Atom: la vía principal del radar."""
import calendar
import logging
from datetime import datetime, timezone

import feedparser
import httpx

from .. import config
from ..texto import sin_html

log = logging.getLogger("intel.rss")


def _descargar(url: str) -> bytes:
    cabeceras = {
        "User-Agent": config.AGENTE_FEEDS,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    try:
        r = httpx.get(url, timeout=25, follow_redirects=True, headers=cabeceras)
        if r.status_code < 400 and r.content:
            return r.content
        estado = r.status_code
    except Exception as e:  # noqa: BLE001
        estado = f"error {type(e).__name__}"
    # Algunos servidores rechazan lectores desconocidos: segundo intento con huella de navegador.
    from .obtener import html_http

    estado2, html, _, cuerpo = html_http(url, timeout=25)
    if estado2 >= 400:
        raise RuntimeError(f"HTTP {estado} / {estado2}")
    return cuerpo or html.encode("utf-8")


def _fecha(entrada) -> datetime | None:
    for campo in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entrada.get(campo)
        if t:
            try:
                return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
            except (ValueError, OverflowError):
                continue
    return None


def recolectar(fuente: dict) -> list[dict]:
    datos = _descargar(fuente["url"])
    feed = feedparser.parse(datos)
    if not feed.entries:
        detalle = getattr(feed, "bozo_exception", None)
        raise RuntimeError(f"feed sin entradas ({detalle})" if detalle else "feed sin entradas")

    items = []
    for e in feed.entries:
        enlace = (e.get("link") or "").strip()
        titulo = sin_html(e.get("title"))
        if not enlace.startswith("http") or not titulo:
            continue
        contenido = ""
        if e.get("content"):
            contenido = sin_html(" ".join(c.get("value", "") for c in e["content"]))
        items.append(
            {
                "url": enlace,
                "titulo": titulo[:500],
                "publicado": _fecha(e),
                "resumen": sin_html(e.get("summary"))[:3000],
                "contenido": contenido,
            }
        )
    return items
