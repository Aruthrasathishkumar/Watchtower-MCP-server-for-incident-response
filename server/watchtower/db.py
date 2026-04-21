"""Database connection handling for WatchTower."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from .config import Config


log = logging.getLogger(__name__)


@contextmanager
def connection(cfg: Config) -> Iterator[psycopg.Connection]:
    """Yield a Postgres connection that is closed on exit.

    Use with a ``with`` statement::

        with connection(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ...")

    Rows are returned as dicts (column name -> value).
    """
    log.debug("Opening DB connection to %s:%s/%s", cfg.db_host, cfg.db_port, cfg.db_name)
    conn = psycopg.connect(cfg.db_dsn, row_factory=dict_row, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()
        log.debug("DB connection closed")


def ping(cfg: Config) -> bool:
    """Return True if the database is reachable and responds to SELECT 1."""
    try:
        with connection(cfg) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            row = cur.fetchone()
            return bool(row and row.get("ok") == 1)
    except Exception as exc:
        log.error("DB ping failed: %s", exc)
        return False