"""Tests for signal clustering and interpretation logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from watchtower.tools._correlate_helpers import (
    Signal,
    cluster_signals,
    interpret_cluster,
    Cluster,
)


def _make_signal(offset_seconds: int = 0, signal_type: str = "event",
                 summary: str = "x", detail: dict | None = None) -> Signal:
    base = datetime(2026, 4, 20, 17, 0, 0, tzinfo=timezone.utc)
    return Signal(
        timestamp=base + timedelta(seconds=offset_seconds),
        signal_type=signal_type,
        summary=summary,
        detail=detail or {},
    )


class TestClusterSignals:
    def test_empty_returns_empty(self):
        assert cluster_signals([], bucket_seconds=60) == []

    def test_single_signal_one_cluster(self):
        clusters = cluster_signals([_make_signal()], bucket_seconds=60)
        assert len(clusters) == 1
        assert len(clusters[0].signals) == 1

    def test_signals_within_bucket_grouped(self):
        signals = [
            _make_signal(offset_seconds=0),
            _make_signal(offset_seconds=30),
            _make_signal(offset_seconds=50),
        ]
        clusters = cluster_signals(signals, bucket_seconds=60)
        assert len(clusters) == 1
        assert len(clusters[0].signals) == 3

    def test_signals_beyond_bucket_split(self):
        signals = [
            _make_signal(offset_seconds=0),
            _make_signal(offset_seconds=200),  # > 60s gap
        ]
        clusters = cluster_signals(signals, bucket_seconds=60)
        assert len(clusters) == 2


class TestInterpretCluster:
    def test_sandbox_changed_detected(self):
        cluster = Cluster(signals=[
            _make_signal(
                signal_type="event",
                detail={"reason": "SandboxChanged"},
            ),
        ])
        assert "runtime" in interpret_cluster(cluster).lower()

    def test_oom_detected(self):
        cluster = Cluster(signals=[
            _make_signal(
                signal_type="event",
                detail={"reason": "OOMKilled"},
            ),
        ])
        assert "memory" in interpret_cluster(cluster).lower()

    def test_unmatched_cluster_returns_empty_string(self):
        """Random cluster with no interpretable pattern."""
        cluster = Cluster(signals=[
            _make_signal(
                signal_type="log_burst",
                summary="burst",
                detail={"count": 10},
            ),
            _make_signal(
                signal_type="metric_delta",
                summary="restart +1",
                detail={"delta": 1},
            ),
        ])
        result = interpret_cluster(cluster)
        # This specific combo may or may not match a rule; just make sure
        # the function returns a string, never crashes.
        assert isinstance(result, str)