"""Write WatchTower events to Postgres.

Idempotent: duplicate (source_system, source_id, timestamp) is silently skipped,
so the collector can safely retry or re-run without creating duplicates.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)


INSERT_SQL = """
INSERT INTO events (
    timestamp, event_type, severity, service, actor,
    source_system, source_id, title, payload
) VALUES (
    %(timestamp)s, %(event_type)s, %(severity)s, %(service)s, %(actor)s,
    %(source_system)s, %(source_id)s, %(title)s, %(payload)s
)
ON CONFLICT (source_system, source_id, timestamp) DO NOTHING
RETURNING id
"""


def write_events(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> int:
    """Insert events, skipping duplicates. Returns the count actually inserted."""
    inserted = 0
    with conn.cursor() as cur:
        for row in rows:
            row_to_write = {**row, "payload": Jsonb(row["payload"])}
            cur.execute(INSERT_SQL, row_to_write)
            if cur.fetchone():
                inserted += 1
    return inserted