"""Búsqueda semántica con Exa: encuentra documentos sobre un tema para el dossier."""
import logging
from datetime import datetime, timedelta, timezone

import httpx

from . import config

log = logging.getLogger("intel.buscador")


def disponible() -> bool:
    return bool(config.EXA_API_KEY)


def buscar(consulta: str, n: int = 5, dias: int | None = None) -> list[dict]:
    """Devuelve resultados con título, URL, fecha y texto. Lista vacía si no hay clave o falla."""
    if not disponible():
        return []
    cuerpo = {
        "query": consulta,
        "numResults": n,
        "type": "auto",
        "contents": {"text": {"maxCharacters": config.DOSSIER_CARACTERES_POR_FUENTE + 1000}},
    }
    if dias:
        desde = datetime.now(timezone.utc) - timedelta(days=dias)
        cuerpo["startPublishedDate"] = desde.strftime("%Y-%m-%dT00:00:00.000Z")
    try:
        r = httpx.post(
            "https://api.exa.ai/search",
            json=cuerpo,
            headers={"x-api-key": config.EXA_API_KEY, "Content-Type": "application/json"},
            timeout=60,
        )
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        log.warning("Búsqueda fallida «%s»: %s", consulta, e)
        return []
    resultados = []
    for x in r.json().get("results", []):
        if not x.get("url"):
            continue
        resultados.append(
            {
                "url": x["url"],
                "titulo": x.get("title") or "",
                "publicado": x.get("publishedDate"),
                "texto": x.get("text") or "",
            }
        )
    return resultados
