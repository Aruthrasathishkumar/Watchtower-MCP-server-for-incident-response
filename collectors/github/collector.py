"""GitHub event collector for WatchTower.

Fetches push events for configured repos and writes them as WatchTower events.

Usage::

    python -m collectors.github.collector                 # collect and exit
    python -m collectors.github.collector --loop          # poll forever (60s)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Make imports work whether run from project root or collectors/github
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

from github import Github, Auth  # PyGithub
from watchtower.config import Config, configure_logging, load_config
from watchtower.db import connection

from .mapper import push_to_event
from .writer import write_events


log = logging.getLogger("collector.github")


def collect_once(cfg: Config) -> int:
    """Run one collection pass. Returns number of new events written."""
    if not cfg.github_token:
        log.error("WATCHTOWER_GITHUB_TOKEN is not set. Add it to server/.env.")
        return 0
    if not cfg.github_repos:
        log.error("WATCHTOWER_GITHUB_REPOS is empty. Add at least one 'owner/repo'.")
        return 0

    gh = Github(auth=Auth.Token(cfg.github_token), per_page=30)
    total_new = 0

    with connection(cfg) as conn:
        for repo_path in cfg.github_repos:
            log.info("Fetching events for %s", repo_path)
            try:
                repo = gh.get_repo(repo_path)
            except Exception as exc:
                log.warning("Could not access %s: %s", repo_path, exc)
                continue

            # GitHub Events API: most recent events first
            rows: list[dict] = []
            for event in repo.get_events():
                # PyGithub wraps the event; we need the raw dict
                raw = event.raw_data
                if raw.get("type") != "PushEvent":
                    continue
                rows.append(push_to_event(raw, repo_path))

            if not rows:
                log.info("  no push events found")
                continue

            inserted = write_events(conn, rows)
            total_new += inserted
            log.info("  %s push events seen, %s new inserted", len(rows), inserted)

    # Be polite — log remaining rate limit (API surface varies by PyGithub version)
    try:
        rl = gh.get_rate_limit()
        core = getattr(getattr(rl, "resources", rl), "core", None)
        remaining = core.remaining if core else "unknown"
        log.info("GitHub rate limit remaining: %s", remaining)
    except Exception as exc:
        log.debug("Could not read rate limit: %s", exc)

    return total_new


def main() -> int:
    parser = argparse.ArgumentParser(description="WatchTower GitHub collector")
    parser.add_argument("--loop", action="store_true", help="Run forever, polling every 60s")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between polls in --loop mode")
    args = parser.parse_args()

    cfg = load_config()
    configure_logging(cfg.log_level)

    if args.loop:
        log.info("Starting GitHub collector (poll interval: %ss)", args.interval)
        while True:
            try:
                collect_once(cfg)
            except Exception as exc:
                log.exception("Collection failed: %s", exc)
            time.sleep(args.interval)
    else:
        new = collect_once(cfg)
        log.info("Done. %s new events written.", new)

    return 0


if __name__ == "__main__":
    sys.exit(main())