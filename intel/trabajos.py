"""Cola de trabajos en Postgres y bucle del motor.

El panel solo encola; el motor ejecuta. Dos hilos: uno para lo largo y programado
(radar, candidatos) y otro para lo que alguien espera delante del panel (dossier, pieza).
La programación se deduce de la propia tabla, así que un reinicio no pierde el compás.
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from . import candidatos, config, db, dossier, llm, radar, redaccion

log = logging.getLogger("intel.trabajos")

LENTOS = ["radar", "candidatos"]
INTERACTIVOS = ["dossier", "pieza", "reverificar"]


def encolar(tipo: str, payload: dict | None = None, origen: str = "panel") -> int:
    fila = db.q1(
        "INSERT INTO trabajos (tipo, payload, origen) VALUES (%s, %s, %s) RETURNING id",
        (tipo, db.Jsonb(payload or {}), origen),
    )
    return fila["id"]


def hay_activo(tipo: str) -> bool:
    return db.q1(
        "SELECT 1 FROM trabajos WHERE tipo = %s AND estado IN ('pendiente', 'en_curso') LIMIT 1", (tipo,)
    ) is not None


def _reclamar(tipos: list[str]) -> dict | None:
    return db.q1(
        """
        UPDATE trabajos SET estado = 'en_curso', iniciado = now()
        WHERE id = (
            SELECT id FROM trabajos WHERE estado = 'pendiente' AND tipo = ANY(%s)
            ORDER BY creado FOR UPDATE SKIP LOCKED LIMIT 1
        )
        RETURNING *
        """,
        (tipos,),
    )


def _ejecutar(t: dict) -> dict:
    p = t["payload"] or {}
    if t["tipo"] == "radar":
        return radar.pasada()
    if t["tipo"] == "candidatos":
        return candidatos.generar(p.get("edicion"))
    if t["tipo"] == "dossier":
        return dossier.construir(int(p["dossier_id"]))
    if t["tipo"] == "pieza":
        return redaccion.redactar(int(p["pieza_id"]))
    if t["tipo"] == "reverificar":
        return redaccion.reverificar(int(p["pieza_id"]))
    raise ValueError(f"Tipo de trabajo desconocido: {t['tipo']}")


def _trabajador(nombre: str, tipos: list[str]) -> None:
    while True:
        try:
            t = _reclamar(tipos)
            if not t:
                time.sleep(5)
                continue
            log.info("[%s] trabajo %d (%s) empieza", nombre, t["id"], t["tipo"])
            try:
                resultado = _ejecutar(t)
                db.ex(
                    "UPDATE trabajos SET estado = 'hecho', resultado = %s, terminado = now() WHERE id = %s",
                    (db.Jsonb(resultado), t["id"]),
                )
                log.info("[%s] trabajo %d (%s) hecho", nombre, t["id"], t["tipo"])
            except Exception as e:  # noqa: BLE001
                log.exception("[%s] trabajo %d (%s) falló", nombre, t["id"], t["tipo"])
                db.ex(
                    "UPDATE trabajos SET estado = 'error', error = %s, terminado = now() WHERE id = %s",
                    (f"{type(e).__name__}: {e}"[:1000], t["id"]),
                )
        except Exception:  # noqa: BLE001  la base puede caerse un momento: el hilo no debe morir
            log.exception("[%s] error en el bucle", nombre)
            time.sleep(15)


def _recuperar_interrumpidos() -> None:
    """Lo que estaba en curso cuando el motor se reinició se da por fallido, no se repite a ciegas."""
    n = db.ex(
        "UPDATE trabajos SET estado = 'error', error = 'Interrumpido por un reinicio del motor', terminado = now() "
        "WHERE estado = 'en_curso'"
    )
    db.ex("UPDATE dossieres SET estado = 'error', error = 'Interrumpido por un reinicio del motor' WHERE estado = 'en_curso'")
    if n:
        log.warning("%d trabajos interrumpidos marcados como error", n)


def _programar() -> None:
    ahora = datetime.now(timezone.utc)

    # Radar: cada RADAR_CADA_HORAS desde el último que se encoló.
    if not hay_activo("radar"):
        ultimo = db.q1("SELECT max(creado) AS t FROM trabajos WHERE tipo = 'radar'")["t"]
        if ultimo is None or ahora - ultimo >= timedelta(hours=config.RADAR_CADA_HORAS):
            encolar("radar", origen="programado")
            log.info("Radar programado encolado")

    # Candidatos: una vez por semana, a partir del día y la hora configurados.
    if llm.disponible() and not hay_activo("candidatos"):
        lunes = (ahora - timedelta(days=ahora.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        cita = lunes + timedelta(days=config.CANDIDATOS_DIA, hours=config.CANDIDATOS_HORA_UTC)
        if ahora >= cita:
            hecho = db.q1(
                "SELECT 1 FROM trabajos WHERE tipo = 'candidatos' AND origen = 'programado' AND creado >= %s LIMIT 1",
                (cita,),
            )
            if not hecho:
                encolar("candidatos", origen="programado")
                log.info("Candidatos de la semana encolados")


def _probar_navegador() -> None:
    """Al arrancar, comprueba una vez que Chromium funciona en el contenedor y lo deja en el registro."""
    if not config.NAVEGADOR:
        return
    try:
        from scrapling.fetchers import DynamicFetcher

        r = DynamicFetcher.fetch("https://example.com/", headless=True, timeout=30000)
        log.info("Navegador: Chromium operativo (HTTP %s)", r.status)
    except Exception as e:  # noqa: BLE001
        log.error("Navegador: Chromium NO operativo; solo funcionará el nivel HTTP. %s", str(e)[:300])


def _probar_panel() -> None:
    """Al arrancar, pinta todas las páginas del panel con los datos reales y deja el resultado en el registro.

    El panel vive en otro servicio y tras contraseña; esta comprobación usa el mismo código y la misma
    base, así que un fallo de plantilla con datos de producción aparece aquí en cada despliegue.
    """
    try:
        import base64
        import secrets

        from fastapi.testclient import TestClient

        from .web.app import app

        clave = secrets.token_urlsafe(16)
        config.PANEL_PASSWORD = clave  # solo en este proceso, que no sirve el panel
        cabeceras = {"Authorization": "Basic " + base64.b64encode(f"motor:{clave}".encode()).decode()}
        rutas = ["/", "/radar", "/radar?estado=sin_puntuar&orden=reciente", "/radar?estado=todos&q=banco",
                 "/candidatos", "/dossieres", "/piezas", "/fuentes", "/trabajos"]
        d = db.q1("SELECT id FROM dossieres ORDER BY id DESC LIMIT 1")
        p = db.q1("SELECT id FROM piezas ORDER BY id DESC LIMIT 1")
        rutas += ([f"/dossier/{d['id']}"] if d else []) + ([f"/pieza/{p['id']}"] if p else [])
        cliente = TestClient(app)
        fallos = []
        for ruta in rutas:
            r = cliente.get(ruta, headers=cabeceras)
            if r.status_code != 200:
                fallos.append(f"{ruta} -> {r.status_code}: {r.text[:200]}")
        if fallos:
            log.error("Panel: %d de %d páginas fallan con datos reales: %s", len(fallos), len(rutas), " | ".join(fallos))
        else:
            log.info("Panel: %d de %d páginas correctas con datos reales", len(rutas), len(rutas))
    except Exception as e:  # noqa: BLE001
        log.error("Panel: no se pudo ejecutar la autoprueba: %s", str(e)[:300])


def motor() -> None:
    db.migrar()
    _recuperar_interrumpidos()
    threading.Thread(target=_probar_navegador, daemon=True).start()
    threading.Thread(target=_probar_panel, daemon=True).start()
    if config.RADAR_AL_ARRANCAR and not hay_activo("radar"):
        encolar("radar", origen="arranque")
        log.info("Radar encolado por RADAR_AL_ARRANCAR")
    log.info(
        "Motor en marcha. Radar cada %dh. Claude: %s. Exa: %s. Navegador: %s",
        config.RADAR_CADA_HORAS,
        "sí" if llm.disponible() else "NO (sin ANTHROPIC_API_KEY)",
        "sí" if config.EXA_API_KEY else "NO (sin EXA_API_KEY)",
        "sí" if config.NAVEGADOR else "no",
    )
    threading.Thread(target=_trabajador, args=("lento", LENTOS), daemon=True).start()
    threading.Thread(target=_trabajador, args=("interactivo", INTERACTIVOS), daemon=True).start()
    while True:
        try:
            _programar()
        except Exception:  # noqa: BLE001
            log.exception("Error al programar")
        time.sleep(60)
