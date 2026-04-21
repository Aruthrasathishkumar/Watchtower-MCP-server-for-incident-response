"""Slack collector — pulls recent channel messages into the event store.

Run as:  python -m collectors.slack.collector
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import psycopg
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Put server/ on sys.path so we can import the shared config + db helpers
sys.path.insert(
    0,
    str(__import__("pathlib").Path(__file__).resolve().parents[2] / "server"),
)

from watchtower.config import load_config, configure_logging  # noqa: E402
from watchtower.db import connection  # noqa: E402
from collectors.github.writer import write_events  # noqa: E402
from collectors.slack.mapper import map_message  # noqa: E402


log = logging.getLogger("collector.slack")


def _resolve_users(client: WebClient, user_ids: set[str]) -> dict[str, str]:
    """Fetch display names for a set of user IDs."""
    cache: dict[str, str] = {}
    for uid in user_ids:
        if not uid or uid == "unknown":
            continue
        try:
            resp = client.users_info(user=uid)
            user = resp["user"]
            cache[uid] = user.get("real_name") or user.get("name") or uid
        except SlackApiError as exc:
            log.warning("Failed to resolve user %s: %s", uid, exc)
            cache[uid] = uid
    return cache


def _last_ingested_ts(cfg, channel_id: str) -> str | None:
    """Find the most recent Slack message ts we've already ingested."""
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_id
            FROM events
            WHERE source_system = 'slack'
              AND source_id LIKE %s
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (f"{channel_id}:%",),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return row["source_id"].split(":", 1)[1]


def collect_channel(cfg, client: WebClient, channel_id: str) -> int:
    """Pull recent messages from one channel, write new ones, return count."""
    oldest = _last_ingested_ts(cfg, channel_id)
    if oldest is None:
        oldest = str(time.time() - 86400)
        log.info("Channel %s: no prior ingestion, pulling last 24h", channel_id)
    else:
        log.info("Channel %s: resuming from ts=%s", channel_id, oldest)

    try:
        resp = client.conversations_history(
            channel=channel_id,
            oldest=oldest,
            inclusive=False,
            limit=200,
        )
    except SlackApiError as exc:
        log.error("Slack API error: %s", exc.response["error"])
        return 0

    messages = resp.get("messages", [])
    if not messages:
        log.info("Channel %s: no new messages", channel_id)
        return 0

    user_ids = {m.get("user", "") for m in messages if m.get("user")}
    user_cache = _resolve_users(client, user_ids)

    rows = [map_message(m, channel_id, user_cache) for m in messages]

    with connection(cfg) as conn:
        written = write_events(conn, rows)
        conn.commit()

    log.info("Channel %s: wrote %d message(s)", channel_id, written)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Slack message collector.")
    parser.add_argument(
        "--channel",
        help="Override WATCHTOWER_SLACK_CHANNELS with a single channel id.",
    )
    args = parser.parse_args()

    cfg = load_config()
    configure_logging(cfg.log_level)

    if not cfg.slack_bot_token:
        log.error("WATCHTOWER_SLACK_BOT_TOKEN is not set.")
        return 2

    channels = [args.channel] if args.channel else cfg.slack_channels
    if not channels:
        log.error("No channels configured.")
        return 2

    client = WebClient(token=cfg.slack_bot_token)

    try:
        auth = client.auth_test()
        log.info("Authenticated as %s in team %s", auth["user"], auth["team"])
    except SlackApiError as exc:
        log.error("Auth failed: %s", exc.response["error"])
        return 2

    total = 0
    for channel_id in channels:
        total += collect_channel(cfg, client, channel_id)

    log.info("Done. Total messages ingested: %d", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())