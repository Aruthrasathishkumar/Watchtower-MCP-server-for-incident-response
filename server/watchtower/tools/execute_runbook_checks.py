"""execute_runbook_checks MCP tool.

Runs the diagnostic checks defined in a runbook. Only 'prometheus' and
'loki' check types are executed in Phase 13. 'shell' checks are refused
until Phase 14 adds the Approval Broker.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import Config
from ..runbooks import runbook_by_id
from .query_metrics import run as run_query_metrics
from .search_logs import run as run_search_logs


log = logging.getLogger(__name__)


TOOL_NAME = "execute_runbook_checks"


TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Execute all diagnostic checks in a runbook. Read-only operations "
        "only — prometheus and loki queries. Shell-based checks are "
        "refused until Phase 14's Approval Broker is available.\n\n"
        "Returns each check's id, description, and result as a structured "
        "report. Use after `list_applicable_runbooks` narrows to a specific "
        "runbook."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "runbook_id": {
                "type": "string",
                "description": "The id of the runbook (e.g. 'checkout-latency').",
            },
        },
        "required": ["runbook_id"],
    },
}


def _run_check(cfg: Config, check) -> str:
    """Run a single check and return its result text."""
    if check.type == "prometheus":
        args = {"query": check.query}
        if check.window:
            args["query_type"] = "range"
            args["window"] = check.window
        return run_query_metrics(cfg, args)

    if check.type == "loki":
        args = {"query": check.query}
        if check.window:
            args["window"] = check.window
        return run_search_logs(cfg, args)

    if check.type == "shell":
        return (
            "⚠️  Shell checks are not executable in Phase 13. "
            "This check requires the Approval Broker (Phase 14) to run safely. "
            f"The runbook specified: `{check.query}`"
        )

    return f"Error: unknown check type '{check.type}'"


def run(cfg: Config, args: dict[str, Any]) -> str:
    runbook_id = args.get("runbook_id")
    if not runbook_id:
        return "Error: 'runbook_id' is required."

    rb = runbook_by_id(runbook_id)
    if rb is None:
        return f"Error: runbook '{runbook_id}' not found in runbooks/ directory."

    if not rb.checks:
        return f"Runbook '{runbook_id}' has no checks defined."

    log.info("Executing %d check(s) for runbook '%s'", len(rb.checks), runbook_id)

    lines = [
        f"# Runbook: `{rb.id}`",
        f"{rb.description}",
        f"Executing {len(rb.checks)} check(s)...",
        "",
    ]

    for check in rb.checks:
        lines.append(f"## Check: `{check.id}` ({check.type})")
        lines.append(f"{check.description}")
        lines.append("")
        lines.append("```")
        try:
            result = _run_check(cfg, check)
        except Exception as exc:
            result = f"Error: {exc}"
        # Truncate very long outputs
        if len(result) > 3000:
            result = result[:3000] + "\n...(truncated)"
        lines.append(result)
        lines.append("```")
        lines.append("")

    if rb.remedies:
        lines.append(f"## Available remedies ({len(rb.remedies)})")
        for r in rb.remedies:
            status = "⚠️ disruptive" if r.safety == "disruptive" else "ℹ️ read-only"
            lines.append(f"- `{r.id}` — {r.description} ({status})")
        lines.append("")
        lines.append(
            "Use `propose_remedy` with runbook_id + remedy_id to see the "
            "full proposal. Actual execution requires Phase 14's Approval "
            "Broker."
        )

    return "\n".join(lines).strip()