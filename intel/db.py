"""Acceso a Postgres: un pool compartido y tres ayudantes."""
import logging
import threading
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from . import config

log = logging.getLogger("intel.db")

_pool: ConnectionPool | None = None
_candado = threading.Lock()


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _candado:
            if _pool is None:
                if not config.DATABASE_URL:
                    raise RuntimeError("Falta la variable DATABASE_URL")
                _pool = ConnectionPool(
                    config.DATABASE_URL,
                    min_size=1,
                    max_size=max(4, config.HILOS + 4),
                    kwargs={"row_factory": dict_row, "autocommit": True},
                    open=True,
                )
                _pool.wait(timeout=60)
    return _pool


def q(sql: str, params=None) -> list[dict]:
    """Consulta que devuelve filas."""
    with pool().connection() as con:
        return con.execute(sql, params).fetchall()


def q1(sql: str, params=None) -> dict | None:
    with pool().connection() as con:
        return con.execute(sql, params).fetchone()


def ex(sql: str, params=None) -> int:
    """Sentencia sin resultado; devuelve filas afectadas."""
    with pool().connection() as con:
        return con.execute(sql, params).rowcount


def migrar() -> None:
    sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    with pool().connection() as con:
        # El candado evita que panel y motor migren a la vez al arrancar juntos.
        con.execute("SELECT pg_advisory_lock(727001)")
        try:
            con.execute(sql)
        finally:
            con.execute("SELECT pg_advisory_unlock(727001)")
    log.info("Esquema al día")


__all__ = ["q", "q1", "ex", "migrar", "pool", "Jsonb"]
