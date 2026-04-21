"""Map GitHub API responses to WatchTower event rows.

Kept separate from fetching so it's easy to unit-test the transform logic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def push_to_event(push: dict[str, Any], repo: str) -> dict[str, Any]:
    """Convert a GitHub push event into a WatchTower event row.

    ``push`` should be the dict returned by the GitHub Events API
    (``type == "PushEvent"``).

    Returns a dict ready to INSERT into the ``events`` table.
    """
    payload = push["payload"]
    head_sha = payload.get("head") or push["id"]
    ref = payload.get("ref", "refs/heads/unknown")
    branch = ref.split("/")[-1]
    commits = payload.get("commits") or []
    head_commit = commits[-1] if commits else {}

    title = (
        head_commit.get("message", "").splitlines()[0]
        if head_commit.get("message")
        else f"Push to {branch} ({len(commits)} commit(s))"
    )

    # GitHub returns ISO-8601 timestamps in UTC
    created_at = datetime.fromisoformat(
        push["created_at"].replace("Z", "+00:00")
    ).astimezone(timezone.utc)

    severity = "info" if branch in {"main", "master"} else "info"
    # Could escalate severity for force-pushes if GitHub told us about them.

    return {
        "timestamp": created_at,
        "event_type": "deploy",
        "severity": severity,
        "service": repo.split("/")[-1],  # repo name without owner prefix
        "actor": push.get("actor", {}).get("login"),
        "source_system": "github",
        "source_id": f"push-{head_sha[:12]}-{branch}",
        "title": title[:500],  # cap long messages
        "payload": {
            "repo": repo,
            "branch": branch,
            "head_sha": head_sha,
            "commit_count": len(commits),
            "commits": [
                {
                    "sha": c.get("sha"),
                    "message": c.get("message"),
                    "author": c.get("author", {}).get("name"),
                }
                for c in commits
            ],
            "github_event_id": push["id"],
        },
    }