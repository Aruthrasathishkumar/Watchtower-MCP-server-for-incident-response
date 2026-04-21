"""Map Slack messages to WatchTower event rows."""
from __future__ import annotations

from datetime import datetime, timezone


def _infer_severity(text: str) -> str:
    """Classify a message by keywords in the text.
    Must return one of: info, warning, error, critical."""
    lower = text.lower()
    if any(k in lower for k in (
        "sev0", "sev1", "critical", "outage", "page", "incident",
        "500s", "503", "pager just",
    )):
        return "warning"
    return "info"


def _infer_service(text: str) -> str | None:
    """Best-effort: extract a service name from the message."""
    services = [
        "checkoutservice", "paymentservice", "cartservice",
        "shippingservice", "productcatalogservice", "currencyservice",
        "emailservice", "recommendationservice", "adservice",
        "frontend", "loadgenerator", "redis",
    ]
    lower = text.lower()
    for svc in services:
        if svc in lower:
            return svc
    return None


def map_message(message: dict, channel_id: str,
                user_cache: dict[str, str]) -> dict:
    """Convert a Slack message dict into an events-table row shape."""
    ts_float = float(message["ts"])
    timestamp = datetime.fromtimestamp(ts_float, tz=timezone.utc)
    user_id = message.get("user", "unknown")
    user_name = user_cache.get(user_id, user_id)
    text = message.get("text", "") or ""

    source_id = f"{channel_id}:{message['ts']}"

    first_line = text.strip().splitlines()[0] if text.strip() else "(empty message)"
    title = first_line[:200]

    return {
        "timestamp": timestamp,
        "event_type": "slack_msg",
        "severity": _infer_severity(text),
        "service": _infer_service(text),
        "actor": user_name,
        "source_system": "slack",
        "source_id": source_id,
        "title": title,
        "payload": {
            "channel": channel_id,
            "user_id": user_id,
            "ts": message["ts"],
            "thread_ts": message.get("thread_ts"),
            "reactions": message.get("reactions", []),
            "full_text": text,
        },
    }