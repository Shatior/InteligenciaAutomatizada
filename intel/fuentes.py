"""Registro de fuentes: config/fuentes.yaml es la verdad; la base guarda además su salud."""
import logging

import yaml

from . import config, db

log = logging.getLogger("intel.fuentes")

_CAMPOS_PROPIOS = {"id", "nombre", "url", "metodo", "dominio", "region", "idioma", "tipo", "fiabilidad", "activa"}


def cargar_yaml() -> list[dict]:
    datos = yaml.safe_load((config.DIR_CONFIG / "fuentes.yaml").read_text(encoding="utf-8"))
    fuentes = datos.get("fuentes", [])
    ids = [f["id"] for f in fuentes]
    repetidos = {i for i in ids if ids.count(i) > 1}
    if repetidos:
        raise ValueError(f"Identificadores de fuente repetidos: {sorted(repetidos)}")
    return fuentes


def sincronizar() -> int:
    """Vuelca el YAML a la base. Las fuentes que desaparecen del YAML se desactivan, no se borran."""
    fuentes = cargar_yaml()
    for f in fuentes:
        extra = {k: v for k, v in f.items() if k not in _CAMPOS_PROPIOS}
        db.ex(
            """
            INSERT INTO fuentes (id, nombre, url, metodo, dominio, region, idioma, tipo, fiabilidad, activa, config)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                nombre = EXCLUDED.nombre, url = EXCLUDED.url, metodo = EXCLUDED.metodo,
                dominio = EXCLUDED.dominio, region = EXCLUDED.region, idioma = EXCLUDED.idioma,
                tipo = EXCLUDED.tipo, fiabilidad = EXCLUDED.fiabilidad, activa = EXCLUDED.activa,
                config = EXCLUDED.config,
                fallos_consecutivos = CASE WHEN fuentes.url <> EXCLUDED.url THEN 0 ELSE fuentes.fallos_consecutivos END
            """,
            (
                f["id"], f["nombre"], f["url"], f.get("metodo", "rss"), f["dominio"],
                f.get("region", "global"), f.get("idioma", "en"), f.get("tipo", "prensa"),
                f.get("fiabilidad", "C"), f.get("activa", True), db.Jsonb(extra),
            ),
        )
    ids = [f["id"] for f in fuentes]
    db.ex("UPDATE fuentes SET activa = FALSE WHERE NOT (id = ANY(%s))", (ids,))
    log.info("Registro sincronizado: %d fuentes", len(fuentes))
    return len(fuentes)


def activas() -> list[dict]:
    return db.q("SELECT * FROM fuentes WHERE activa ORDER BY id")


def cargar_ediciones() -> dict:
    datos = yaml.safe_load((config.DIR_CONFIG / "ediciones.yaml").read_text(encoding="utf-8"))
    return datos["ediciones"]


def guia_pieza() -> str:
    return (config.DIR_CONFIG / "guia_pieza.md").read_text(encoding="utf-8")
