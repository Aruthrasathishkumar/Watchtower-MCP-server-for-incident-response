"""suspect_rank MCP tool.

Given an incident (service + optional description) and a time window,
returns a ranked list of the change events most likely to have caused
the incident.

See docs/rfc-suspect-ranking.md for the algorithm design.
"""
from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from ..config import Config
from ..db import connection
from ..embeddings import embed_text


log = logging.getLogger(__name__)


TOOL_NAME = "suspect_rank"

# Weights from the RFC
W_SERVICE = 0.40
W_RECENCY = 0.25
W_BLAST = 0.15
W_SEMANTIC = 0.20

# Recency decay half-life, in minutes
RECENCY_HALF_LIFE = 10.0

# Blast-radius saturation threshold
BLAST_SATURATION = 10

# Change-type events are the only candidates
CHANGE_EVENT_TYPES = ("deploy", "terraform_apply", "config_change", "feature_flag")


TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Given an incident (a service that's failing), return the top N change "
        "events most likely to have caused the incident, ranked by a composite "
        "score combining service match, recency, blast radius, and semantic "
        "similarity. Use this AFTER what_changed when you need to focus on "
        "the most probable causes rather than reviewing every change."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "The service that is failing (e.g. 'checkout').",
            },
            "since": {
                "type": "string",
                "default": "30m",
                "description": "How far back to search. e.g. '10m', '2h', '1d'.",
            },
            "incident_description": {
                "type": "string",
                "description": (
                    "Optional free-form description of the failure. Improves "
                    "semantic matching. If omitted, the service name is used."
                ),
            },
            "limit": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
                "description": "Number of suspects to return.",
            },
        },
        "required": ["service"],
    },
}


_WINDOW_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_UNIT_TO_MINUTES = {"s": 1 / 60, "m": 1, "h": 60, "d": 1440}


def _parse_window_minutes(window: str) -> float:
    match = _WINDOW_RE.match(window)
    if not match:
        raise ValueError(
            f"Invalid window '{window}'. Use formats like '30m', '2h', '1d'."
        )
    return int(match.group(1)) * _UNIT_TO_MINUTES[match.group(2).lower()]


# --- Individual signal scorers -------------------------------------------------

def _service_match_score(change_service: str, incident_service: str) -> float:
    """Signal 1: how well does the changed service match the incident service?"""
    if not change_service:
        return 0.0
    if change_service == incident_service:
        return 1.0
    # Same namespace heuristic: if both look like K8s services, they're in the
    # same deployment group. This is a placeholder until we have a real service
    # graph (Phase 12).
    return 0.3  # weakly related


def _recency_score(age_minutes: float) -> float:
    """Signal 2: exponential decay with half-life RECENCY_HALF_LIFE."""
    if age_minutes < 0:
        return 1.0
    return math.exp(-age_minutes / RECENCY_HALF_LIFE)


def _blast_score(blast_count: int) -> float:
    """Signal 3: min(1.0, blast_count / BLAST_SATURATION)."""
    return min(1.0, blast_count / BLAST_SATURATION)


def _semantic_score(similarity: float | None) -> float:
    """Signal 4: pgvector returns cosine DISTANCE (0=same). Convert to similarity."""
    if similarity is None:
        return 0.0
    # pgvector <=> is cosine distance. For normalised vectors, similarity = 1 - distance.
    # Distance is in [0, 2]; clamp similarity to [0, 1].
    return max(0.0, min(1.0, 1.0 - similarity))


# --- Main ranker ---------------------------------------------------------------

def run(cfg: Config, args: dict[str, Any]) -> str:
    """Execute the suspect_rank tool."""
    incident_service = args.get("service")
    if not incident_service:
        return "Error: 'service' parameter is required."

    since = args.get("since", "30m")
    try:
        window_minutes = _parse_window_minutes(since)
    except ValueError as exc:
        return f"Error: {exc}"

    description = args.get("incident_description") or incident_service
    limit = min(int(args.get("limit", 5)), 20)

    # Embed the incident description for semantic scoring
    incident_vec = embed_text(description)
    incident_vec_str = str(incident_vec)

    # Build the candidate query. Pull all change-type events in window, plus
    # each event's similarity to the incident (via pgvector).
    placeholders = ",".join(["%s"] * len(CHANGE_EVENT_TYPES))
    sql = f"""
    WITH candidates AS (
        SELECT
            id, timestamp, event_type, severity, service, actor,
            source_system, source_id, title, payload,
            -- cosine distance; NULL if event has no embedding
            CASE
              WHEN embedding IS NOT NULL
              THEN embedding <=> %s::vector
              ELSE NULL
            END AS semantic_distance
        FROM events
        WHERE timestamp >= NOW() - INTERVAL '{int(window_minutes)} minutes'
          AND event_type IN ({placeholders})
    ),
    blast AS (
        SELECT actor, COUNT(*) AS actor_count
        FROM candidates
        WHERE actor IS NOT NULL
        GROUP BY actor
    )
    SELECT c.*, COALESCE(b.actor_count, 1) AS blast_count
    FROM candidates c
    LEFT JOIN blast b ON c.actor = b.actor
    ORDER BY c.timestamp DESC
    """

    params: list[Any] = [incident_vec_str, *CHANGE_EVENT_TYPES]

    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        candidates = cur.fetchall()

    if not candidates:
        return f"No change events found for service '{incident_service}' in the last {since}."

    # Score each candidate
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    scored = []
    for row in candidates:
        age_minutes = (now - row["timestamp"]).total_seconds() / 60
        s_service = _service_match_score(row["service"], incident_service)
        s_recency = _recency_score(age_minutes)
        s_blast = _blast_score(row["blast_count"])
        s_semantic = _semantic_score(row["semantic_distance"])

        final = (
            W_SERVICE * s_service
            + W_RECENCY * s_recency
            + W_BLAST * s_blast
            + W_SEMANTIC * s_semantic
        )

        scored.append({
            "row": row,
            "age_minutes": age_minutes,
            "signals": {
                "service": s_service,
                "recency": s_recency,
                "blast": s_blast,
                "semantic": s_semantic,
            },
            "final": final,
        })

    # Sort by final score, take top N
    scored.sort(key=lambda s: -s["final"])
    top = scored[:limit]

    # Format output for Claude. Markdown table + per-suspect justification.
    lines = [
        f"# Suspect ranking for incident on service `{incident_service}`",
        f"Window: last {since} · description: {description!r}",
        f"Candidates scored: {len(scored)} · Top {len(top)} shown",
        "",
    ]
    for i, s in enumerate(top, start=1):
        row = s["row"]
        sig = s["signals"]
        lines.append(f"## {i}. Score {s['final']:.3f} — {row['title']}")
        lines.append(
            f"- Service: `{row['service']}` · Actor: `{row['actor']}` · "
            f"Age: {s['age_minutes']:.1f}min · "
            f"Source: `{row['source_system']}:{row['source_id']}`"
        )
        lines.append(
            f"- Signal breakdown: "
            f"service={sig['service']:.2f} (w0.40), "
            f"recency={sig['recency']:.2f} (w0.25), "
            f"blast={sig['blast']:.2f} (w0.15), "
            f"semantic={sig['semantic']:.2f} (w0.20)"
        )
        if row["payload"]:
            lines.append(f"- Payload: `{json.dumps(row['payload'], default=str)[:200]}...`")
        lines.append("")

    return "\n".join(lines).strip()