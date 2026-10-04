"""Pasada del radar: recolectar → traer texto → deduplicar → puntuar."""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import config, db, fuentes, puntuar
from .recoleccion import html as rec_html
from .recoleccion import obtener, rss
from .texto import huella_titulo, huella_url

log = logging.getLogger("intel.radar")


def _fecha_iso(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        f = datetime.fromisoformat(valor[:19])
        return f if f.tzinfo else f.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _marcar_duplicados() -> int:
    """Marca como duplicado todo item cuyo titular ya entró antes por otra fuente en la última semana.

    Se hace en una sola sentencia tras la recolección: comprobarlo al insertar daría carreras
    entre los hilos que leen fuentes distintas a la vez.
    """
    return db.ex(
        """
        UPDATE items i SET estado = 'duplicado'
        WHERE i.estado IN ('nuevo', 'con_texto', 'sin_texto') AND i.titulo_hash IS NOT NULL
          AND i.recolectado > now() - interval '2 days'
          AND EXISTS (
              SELECT 1 FROM items j
              WHERE j.titulo_hash = i.titulo_hash AND j.id < i.id AND j.estado <> 'duplicado'
                AND j.recolectado > i.recolectado - interval '7 days'
          )
        """
    )


def _recolectar_fuente(f: dict) -> dict:
    """Lee una fuente e inserta lo nuevo. Nunca lanza: el fallo queda anotado en la fuente."""
    limite = datetime.now(timezone.utc) - timedelta(days=config.DIAS_VENTANA)
    try:
        entradas = rss.recolectar(f) if f["metodo"] == "rss" else rec_html.recolectar(f)
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"[:300]
        db.ex(
            """
            UPDATE fuentes SET ultimo_intento = now(), ultimo_error = %s,
                fallos_consecutivos = fallos_consecutivos + 1, items_ultimo = 0
            WHERE id = %s
            """,
            (error, f["id"]),
        )
        log.warning("FUENTE FALLA %-28s %s", f["id"], error)
        return {"id": f["id"], "ok": False, "error": error, "nuevos": 0}

    recientes = [e for e in entradas if not e["publicado"] or e["publicado"] >= limite]
    recientes = recientes[: config.MAX_ITEMS_POR_FUENTE]
    nuevos = 0
    for e in recientes:
        th = huella_titulo(e["titulo"])
        con_texto = len(e["contenido"]) >= 1500
        estado = "con_texto" if con_texto else "nuevo"
        fila = db.q1(
            """
            INSERT INTO items (fuente_id, url, url_hash, titulo, titulo_hash, publicado, resumen_fuente,
                               texto, texto_metodo, estado)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url_hash) DO NOTHING
            RETURNING id
            """,
            (
                f["id"], e["url"], huella_url(e["url"]), e["titulo"], th, e["publicado"], e["resumen"] or None,
                e["contenido"] if con_texto else None, "feed" if con_texto else None, estado,
            ),
        )
        if fila:
            nuevos += 1
    db.ex(
        """
        UPDATE fuentes SET ultimo_intento = now(), ultimo_ok = now(), ultimo_error = NULL,
            fallos_consecutivos = 0, items_ultimo = %s, items_total = items_total + %s
        WHERE id = %s
        """,
        (len(recientes), nuevos, f["id"]),
    )
    log.info("FUENTE OK    %-28s leídos=%d recientes=%d nuevos=%d", f["id"], len(entradas), len(recientes), nuevos)
    return {"id": f["id"], "ok": True, "nuevos": nuevos, "leidos": len(entradas)}


def _traer_texto(it: dict) -> str:
    cfg = it["config"] or {}
    if cfg.get("solo_feed"):
        db.ex("UPDATE items SET estado = 'sin_texto', texto_error = 'solo_feed' WHERE id = %s", (it["id"],))
        return "sin_texto"

    usa_navegador = bool(cfg.get("navegador") or cfg.get("sigilo"))
    pagina = obtener.obtener(it["url"], sigilo=bool(cfg.get("sigilo")), navegador=usa_navegador)
    titulo = it["titulo"] or (pagina.titulo or "")[:500] or None
    publicado = it["publicado"] or _fecha_iso(pagina.fecha)
    th = huella_titulo(titulo)

    limite = datetime.now(timezone.utc) - timedelta(days=config.DIAS_VENTANA)
    if publicado and publicado < limite:
        estado = "antiguo"
    elif pagina.ok:
        estado = "con_texto"
    else:
        estado = "sin_texto"

    db.ex(
        """
        UPDATE items SET titulo = %s, titulo_hash = %s, publicado = %s, texto = %s, texto_metodo = %s,
            texto_error = %s, estado = %s
        WHERE id = %s
        """,
        (
            titulo, th, publicado, pagina.texto[:200000] if pagina.ok else None,
            pagina.metodo if pagina.ok else None,
            None if pagina.ok else (pagina.error or "; ".join(pagina.intentos))[:300], estado, it["id"],
        ),
    )
    return estado


def pasada() -> dict:
    """Una pasada completa. Devuelve un resumen que se guarda con el trabajo."""
    inicio = datetime.now(timezone.utc)
    fuentes.sincronizar()
    obtener.reiniciar_cuota_navegador()
    lista = fuentes.activas()
    log.info("Radar: %d fuentes activas", len(lista))

    with ThreadPoolExecutor(max_workers=config.HILOS) as hilos:
        resultados = list(hilos.map(_recolectar_fuente, lista))
    fallidas = [r for r in resultados if not r["ok"]]
    nuevos = sum(r["nuevos"] for r in resultados)
    log.info("Recolección: %d nuevos; %d fuentes fallan de %d", nuevos, len(fallidas), len(lista))

    duplicados = _marcar_duplicados()

    pendientes = db.q(
        """
        SELECT i.id, i.url, i.titulo, i.publicado, f.config
        FROM items i JOIN fuentes f ON f.id = i.fuente_id
        WHERE i.estado = 'nuevo'
        ORDER BY i.recolectado DESC
        LIMIT %s
        """,
        (config.MAX_TEXTOS_POR_PASADA,),
    )

    def _seguro(it):
        try:
            return _traer_texto(it)
        except Exception as e:  # noqa: BLE001
            log.warning("Texto fallido %s: %s", it["url"], e)
            db.ex(
                "UPDATE items SET estado = 'sin_texto', texto_error = %s WHERE id = %s",
                (f"{type(e).__name__}: {e}"[:300], it["id"]),
            )
            return "sin_texto"

    with ThreadPoolExecutor(max_workers=config.HILOS) as hilos:
        estados = list(hilos.map(_seguro, pendientes))
    conteo = {e: estados.count(e) for e in set(estados)}
    duplicados += _marcar_duplicados()  # las fuentes sin feed reciben su titular al traer el artículo
    log.info("Textos: %s; duplicados: %d", conteo, duplicados)

    puntuacion = puntuar.puntuar_pendientes()

    resumen = {
        "fuentes": len(lista),
        "fuentes_fallidas": [{"id": r["id"], "error": r["error"]} for r in fallidas],
        "nuevos": nuevos,
        "textos": conteo,
        "duplicados": duplicados,
        "puntuacion": puntuacion,
        "segundos": round((datetime.now(timezone.utc) - inicio).total_seconds()),
    }
    log.info(
        "Radar terminado en %ss: nuevos=%d fallidas=%d puntuados=%s",
        resumen["segundos"], nuevos, len(fallidas), puntuacion.get("puntuados"),
    )
    return resumen
