"""Export JSON snapshots for the static frontend.

Writes to frontend/public/data/*.json. Run whenever you want the
frontend to show fresh data: `python scripts/export_frontend_data.py`.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Add server to sys.path
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "server"),
)

from watchtower.config import load_config  # noqa: E402
from watchtower.db import connection  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "frontend" / "public" / "data"


def _json_default(obj):
    """Serialize datetimes and UUIDs to strings."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def export_events(cfg) -> None:
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, timestamp, event_type, severity, service, actor,
                   source_system, source_id, title, payload
            FROM events
            ORDER BY timestamp DESC
            LIMIT 300
            """,
        )
        rows = cur.fetchall()

    data = [dict(r) for r in rows]
    (OUT_DIR / "events.json").write_text(
        json.dumps(data, default=_json_default, indent=2)
    )
    print(f"events.json: wrote {len(data)} rows")


def export_approvals(cfg) -> None:
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, runbook_id, remedy_id, rationale, requested_by,
                   requested_at, status
            FROM approval_requests
            ORDER BY requested_at DESC
            LIMIT 50
            """,
        )
        rows = cur.fetchall()

    data = [dict(r) for r in rows]
    (OUT_DIR / "approvals.json").write_text(
        json.dumps(data, default=_json_default, indent=2)
    )
    print(f"approvals.json: wrote {len(data)} rows")


def export_audit(cfg) -> None:
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, proposal_id, action, actor,
                   token_nonce, stdout, stderr, exit_code, at
            FROM approval_audit
            ORDER BY at DESC
            LIMIT 100
            """,
        )
        rows = cur.fetchall()

    data = [dict(r) for r in rows]
    (OUT_DIR / "audit.json").write_text(
        json.dumps(data, default=_json_default, indent=2)
    )
    print(f"audit.json: wrote {len(data)} rows")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    export_events(cfg)
    export_approvals(cfg)
    export_audit(cfg)
    print(f"\nAll snapshots written to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())