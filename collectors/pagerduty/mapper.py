"""Map PagerDuty incidents to WatchTower event rows."""
from __future__ import annotations

from datetime import datetime


# PagerDuty urgency → event_severity enum value
_URGENCY_SEVERITY = {
    "high": "error",
    "low": "warning",
}

# Incident status → event_type enum value
_STATUS_EVENT_TYPE = {
    "triggered": "incident_open",
    "acknowledged": "incident_open",   # same bucket until resolved
    "resolved": "incident_resolved",
}


def _infer_service_from_title(title: str) -> str | None:
    services = [
        "checkoutservice", "paymentservice", "cartservice",
        "shippingservice", "productcatalogservice", "currencyservice",
        "emailservice", "recommendationservice", "adservice",
        "frontend", "loadgenerator",
    ]
    lower = title.lower()
    for svc in services:
        if svc in lower:
            return svc
    return None


def map_incident(incident: dict) -> dict:
    """Convert a PagerDuty incident into the events-table row shape."""
    created_at = datetime.fromisoformat(
        incident["created_at"].replace("Z", "+00:00")
    )

    title = incident.get("title") or incident.get("summary") or "(no title)"
    urgency = incident.get("urgency", "low")
    status = incident.get("status", "triggered")

    return {
        "timestamp": created_at,
        "event_type": _STATUS_EVENT_TYPE.get(status, "incident_open"),
        "severity": _URGENCY_SEVERITY.get(urgency, "info"),
        "service": _infer_service_from_title(title),
        "actor": (incident.get("service") or {}).get("summary", "pagerduty"),
        "source_system": "pagerduty",
        "source_id": str(incident["id"]),
        "title": title[:200],
        "payload": {
            "incident_number": incident.get("incident_number"),
            "status": status,
            "urgency": urgency,
            "service_id": (incident.get("service") or {}).get("id"),
            "service_name": (incident.get("service") or {}).get("summary"),
            "assignments": [
                a.get("assignee", {}).get("summary")
                for a in incident.get("assignments", [])
            ],
            "html_url": incident.get("html_url"),
        },
    }