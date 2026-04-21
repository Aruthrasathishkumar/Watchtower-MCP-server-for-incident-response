"""WatchTower configuration loader.

Reads from environment variables. Uses python-dotenv to load from a .env
file in development.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# Load .env file if it exists (development convenience)
# In production, env vars are set by the runtime, not a file.
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration."""

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    log_level: str
    github_token: str
    github_repos: list[str]
    approval_secret: str
    approval_ttl_seconds: int
    slack_bot_token: str
    slack_channels: list[str]
    pagerduty_api_token: str
    pagerduty_services: list[str]

    @property
    def db_dsn(self) -> str:
        """Postgres connection string in DSN (URI) form."""
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(
            f"Missing required env var: {key}. "
            f"Copy server/.env.example to server/.env and fill it in."
        )
    return val


def load_config() -> Config:
    """Build a Config from the current environment."""
    return Config(
        db_host=_require("WATCHTOWER_DB_HOST"),
        db_port=int(_require("WATCHTOWER_DB_PORT")),
        db_name=_require("WATCHTOWER_DB_NAME"),
        db_user=_require("WATCHTOWER_DB_USER"),
        db_password=_require("WATCHTOWER_DB_PASSWORD"),
        log_level=os.environ.get("WATCHTOWER_LOG_LEVEL", "INFO"),
        github_token=os.environ.get("WATCHTOWER_GITHUB_TOKEN", ""),
        github_repos=[
            r.strip()
            for r in os.environ.get("WATCHTOWER_GITHUB_REPOS", "").split(",")
            if r.strip()
        ],
        approval_secret=os.environ.get("WATCHTOWER_APPROVAL_SECRET", ""),
        approval_ttl_seconds=int(os.environ.get("WATCHTOWER_APPROVAL_TTL_SECONDS", "300")),
        slack_bot_token=os.environ.get("WATCHTOWER_SLACK_BOT_TOKEN", ""),
        slack_channels=[
            c.strip()
            for c in os.environ.get("WATCHTOWER_SLACK_CHANNELS", "").split(",")
            if c.strip()
        ],
        pagerduty_api_token=os.environ.get("WATCHTOWER_PAGERDUTY_API_TOKEN", ""),
        pagerduty_services=[
            s.strip()
            for s in os.environ.get("WATCHTOWER_PAGERDUTY_SERVICES", "").split(",")
            if s.strip()
        ],
    )


def configure_logging(level: str) -> None:
    """Configure Python logging for the server."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )