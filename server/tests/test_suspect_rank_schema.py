"""Smoke test for the suspect_rank tool's schema declaration."""
from __future__ import annotations

from watchtower.tools.suspect_rank import TOOL_SCHEMA


class TestSuspectRankSchema:
    def test_schema_has_required_fields(self):
        assert TOOL_SCHEMA["name"] == "suspect_rank"
        assert "description" in TOOL_SCHEMA
        assert "inputSchema" in TOOL_SCHEMA

    def test_input_requires_service(self):
        required = TOOL_SCHEMA["inputSchema"].get("required", [])
        assert "service" in required

    def test_input_includes_incident_description(self):
        props = TOOL_SCHEMA["inputSchema"]["properties"]
        assert "incident_description" in props
        # Not required, just optional
        assert "incident_description" not in TOOL_SCHEMA["inputSchema"].get("required", [])