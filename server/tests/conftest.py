"""Shared pytest fixtures for WatchTower tests."""
from __future__ import annotations

import pytest

from watchtower.config import Config


@pytest.fixture
def fake_config() -> Config:
    """A Config with made-up values — no real DB or secrets needed."""
    return Config(
        db_host="fake-host",
        db_port=5432,
        db_name="fake_db",
        db_user="fake_user",
        db_password="fake_pw",
        log_level="INFO",
        github_token="",
        github_repos=[],
        approval_secret="test-secret-" + "x" * 50,
        approval_ttl_seconds=300,
        slack_bot_token="",
        slack_channels=[],
        pagerduty_api_token="",
        pagerduty_services=[],
    )