"""PagerDuty collector — pulls incidents into the event store.

Run as:  python -m collectors.pagerduty.collector
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

import psycopg
import requests

sys.path.insert(
    0,
    str(__import__("pathlib").Path(__file__).resolve().parents[2] / "server"),
)

from watchtower.config import load_config, configure_logging  # noqa: E402
from watchtower.db import connection  # noqa: E402
from collectors.github.writer import write_events  # noqa: E402
from collectors.pagerduty.mapper import map_incident  # noqa: E402


log = logging.getLogger("collector.pagerduty")


PD_API_BASE = "https://api.pagerduty.com"


def _last_ingested_timestamp(cfg) -> datetime | None:
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT timestamp
            FROM events
            WHERE source_system = 'pagerduty'
            ORDER BY timestamp DESC
            LIMIT 1
            """,
        )
        row = cur.fetchone()
    return row["timestamp"] if row else None


def fetch_incidents(token: str, since: datetime,
                    service_ids: list[str]) -> list[dict]:
    headers = {
        "Authorization": f"Token token={token}",
        "Accept": "application/vnd.pagerduty+json;version=2",
    }

    incidents: list[dict] = []
    offset = 0
    limit = 100

    while True:
        params: dict = {
            "since": since.isoformat(),
            "until": datetime.now(timezone.utc).isoformat(),
            "statuses[]": ["triggered", "acknowledged", "resolved"],
            "limit": limit,
            "offset": offset,
            "sort_by": "created_at:asc",
        }
        if service_ids:
            params["service_ids[]"] = service_ids

        resp = requests.get(
            f"{PD_API_BASE}/incidents",
            headers=headers,
            params=params,
            timeout=15,
        )
        if resp.status_code != 200:
            log.error("PagerDuty API returned %d: %s",
                      resp.status_code, resp.text[:200])
            break

        data = resp.json()
        batch = data.get("incidents", [])
        incidents.extend(batch)

        if not data.get("more"):
            break
        offset += limit
        if offset >= 1000:
            log.warning("Stopping pagination at 1000 incidents")
            break

    return incidents


def main() -> int:
    parser = argparse.ArgumentParser(description="PagerDuty collector.")
    parser.add_argument(
        "--since-hours",
        type=int,
        default=None,
        help="Override: fetch last N hours regardless of last-ingested state.",
    )
    args = parser.parse_args()

    cfg = load_config()
    configure_logging(cfg.log_level)

    if not cfg.pagerduty_api_token:
        log.error("WATCHTOWER_PAGERDUTY_API_TOKEN is not set.")
        return 2

    if args.since_hours:
        since = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
    else:
        last = _last_ingested_timestamp(cfg)
        since = last if last else datetime.now(timezone.utc) - timedelta(hours=24)
    log.info("Fetching incidents since %s", since.isoformat())

    incidents = fetch_incidents(
        cfg.pagerduty_api_token, since, cfg.pagerduty_services,
    )
    log.info("PagerDuty returned %d incident(s)", len(incidents))

    if not incidents:
        return 0

    rows = [map_incident(i) for i in incidents]

    with connection(cfg) as conn:
        written = write_events(conn, rows)
        conn.commit()

    log.info("Wrote %d incident event(s)", written)
    return 0


if __name__ == "__main__":
    sys.exit(main())