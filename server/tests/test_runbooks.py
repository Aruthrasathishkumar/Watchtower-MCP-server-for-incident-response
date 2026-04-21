"""Tests for runbook loading and validation."""
from __future__ import annotations

import pytest

from watchtower.runbooks import (
    RunbookError,
    parse_runbook,
    VALID_CHECK_TYPES,
    VALID_SIGNALS,
    VALID_SAFETY_LEVELS,
)


class TestParseRunbookValid:
    def test_minimal_valid_runbook(self):
        data = {
            "id": "minimal",
            "description": "test",
            "version": 1,
        }
        rb = parse_runbook(data, source_file="test.yaml")
        assert rb.id == "minimal"
        assert rb.version == 1
        assert rb.triggers == []
        assert rb.checks == []
        assert rb.remedies == []

    def test_full_runbook_parses_correctly(self):
        data = {
            "id": "full",
            "description": "complete runbook",
            "version": 1,
            "triggers": [
                {"signal": "log_burst", "service": "checkoutservice"},
            ],
            "checks": [
                {
                    "id": "c1",
                    "description": "Is pod ready?",
                    "type": "prometheus",
                    "query": "kube_pod_status_ready",
                    "window": "5m",
                },
            ],
            "remedies": [
                {
                    "id": "r1",
                    "description": "restart pod",
                    "requires_approval": True,
                    "command": "kubectl delete pod foo",
                    "safety": "disruptive",
                },
            ],
        }
        rb = parse_runbook(data, source_file="test.yaml")
        assert len(rb.triggers) == 1
        assert rb.triggers[0].signal == "log_burst"
        assert rb.triggers[0].service == "checkoutservice"
        assert len(rb.checks) == 1
        assert rb.checks[0].type == "prometheus"
        assert len(rb.remedies) == 1
        assert rb.remedies[0].safety == "disruptive"
        assert rb.remedies[0].requires_approval is True


class TestParseRunbookInvalid:
    def test_missing_id_raises(self):
        with pytest.raises(RunbookError, match="id"):
            parse_runbook(
                {"description": "no id here"},
                source_file="bad.yaml",
            )

    def test_invalid_signal_rejected(self):
        data = {
            "id": "bad",
            "description": "x",
            "triggers": [{"signal": "not_a_real_signal"}],
        }
        with pytest.raises(RunbookError, match="invalid trigger signal"):
            parse_runbook(data, source_file="bad.yaml")

    def test_invalid_check_type_rejected(self):
        data = {
            "id": "bad",
            "description": "x",
            "checks": [{
                "id": "c1",
                "description": "x",
                "type": "magic",
                "query": "foo",
            }],
        }
        with pytest.raises(RunbookError, match="invalid check type"):
            parse_runbook(data, source_file="bad.yaml")

    def test_invalid_safety_level_rejected(self):
        data = {
            "id": "bad",
            "description": "x",
            "remedies": [{
                "id": "r1",
                "description": "x",
                "safety": "nuclear",
            }],
        }
        with pytest.raises(RunbookError, match="invalid safety level"):
            parse_runbook(data, source_file="bad.yaml")


class TestEnumConstants:
    """These sets are imported and relied upon by tools; lock them down."""

    def test_valid_signals_is_set(self):
        assert isinstance(VALID_SIGNALS, set)
        assert "log_burst" in VALID_SIGNALS

    def test_valid_check_types_includes_core(self):
        assert {"prometheus", "loki", "shell"}.issubset(VALID_CHECK_TYPES)

    def test_valid_safety_levels_minimal(self):
        assert {"read_only", "disruptive"}.issubset(VALID_SAFETY_LEVELS)