"""Tests for the collector mappers.

Mappers live under collectors/<source>/mapper.py. They transform
source-specific payloads into the events-table row shape.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Add the project root so `collectors` imports work
_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root))

from collectors.slack.mapper import map_message as map_slack  # noqa: E402
from collectors.pagerduty.mapper import map_incident as map_pd  # noqa: E402


class TestSlackMapper:
    def test_minimal_message(self):
        msg = {
            "ts": "1729534800.000100",
            "user": "U123",
            "text": "hello world",
        }
        row = map_slack(msg, "C999", user_cache={"U123": "Alice"})
        assert row["source_system"] == "slack"
        assert row["event_type"] == "slack_msg"
        assert row["source_id"] == "C999:1729534800.000100"
        assert row["actor"] == "Alice"
        assert row["severity"] == "info"

    def test_infers_service_from_text(self):
        msg = {
            "ts": "1729534800.000100",
            "user": "U1",
            "text": "Seeing errors on checkoutservice",
        }
        row = map_slack(msg, "C1", user_cache={})
        assert row["service"] == "checkoutservice"

    def test_severity_warning_on_incident_keyword(self):
        msg = {
            "ts": "1729534800.000100",
            "user": "U1",
            "text": "pager just went off for an incident",
        }
        row = map_slack(msg, "C1", user_cache={})
        assert row["severity"] == "warning"


class TestPagerDutyMapper:
    def test_triggered_maps_to_incident_open(self):
        incident = {
            "id": "Q123",
            "incident_number": 42,
            "title": "paymentservice latency spike",
            "status": "triggered",
            "urgency": "high",
            "created_at": "2026-04-20T17:00:00Z",
            "service": {"id": "PABC", "summary": "paymentservice"},
            "assignments": [],
        }
        row = map_pd(incident)
        assert row["event_type"] == "incident_open"
        assert row["severity"] == "error"  # high urgency
        assert row["source_system"] == "pagerduty"
        assert row["source_id"] == "Q123"
        assert row["service"] == "paymentservice"

    def test_resolved_maps_to_incident_resolved(self):
        incident = {
            "id": "Q999",
            "incident_number": 1,
            "title": "something resolved",
            "status": "resolved",
            "urgency": "low",
            "created_at": "2026-04-20T17:00:00Z",
            "service": {"id": "P1", "summary": "some service"},
        }
        row = map_pd(incident)
        assert row["event_type"] == "incident_resolved"
        assert row["severity"] == "warning"  # low urgency