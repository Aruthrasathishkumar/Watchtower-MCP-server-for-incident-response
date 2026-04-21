"""One-shot script to populate event embeddings.

Can be re-run safely. Only updates rows where embedding IS NULL.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from watchtower.config import configure_logging, load_config
from watchtower.db import connection
from watchtower.embeddings import embed_batch


log = logging.getLogger("backfill")

BATCH_SIZE = 50


def main() -> int:
    cfg = load_config()
    configure_logging(cfg.log_level)

    with connection(cfg) as conn:
        while True:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, timestamp, title FROM events "
                    "WHERE embedding IS NULL "
                    "ORDER BY timestamp DESC "
                    "LIMIT %s",
                    (BATCH_SIZE,),
                )
                batch = cur.fetchall()

            if not batch:
                log.info("All events have embeddings. Done.")
                break

            titles = [row["title"] or "" for row in batch]
            log.info("Embedding batch of %d events...", len(batch))
            vecs = embed_batch(titles)

            with conn.cursor() as cur:
                for row, vec in zip(batch, vecs):
                    cur.execute(
                        "UPDATE events SET embedding = %s::vector "
                        "WHERE id = %s AND timestamp = %s",
                        (str(vec), row["id"], row["timestamp"]),
                    )
            log.info("Wrote %d embeddings.", len(batch))

    return 0


if __name__ == "__main__":
    sys.exit(main())