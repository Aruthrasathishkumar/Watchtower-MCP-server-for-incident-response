"""list_applicable_runbooks MCP tool.

Given an affected service and a list of observed signal types, return
runbooks whose triggers match.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import Config
from ..runbooks import match_runbooks, VALID_SIGNALS


log = logging.getLogger(__name__)


TOOL_NAME = "list_applicable_runbooks"


TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Given a service and a list of observed signal types, return runbooks "
        "that match. Use this when investigating an incident to discover "
        "pre-written procedures that apply.\n\n"
        "Signal types:\n"
        "- log_burst — unusual rate of error/warning logs\n"
        "- high_latency — elevated response times\n"
        "- pod_restart — container restart detected\n"
        "- service_down — service not ready\n"
        "- metric_anomaly — Prometheus-detected outlier\n"
        "\nIf no signals match, returns 'no applicable runbooks'."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "The affected service (e.g. 'checkoutservice').",
            },
            "signals": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    f"Observed signal types. Valid: {sorted(VALID_SIGNALS)}."
                ),
            },
        },
        "required": ["signals"],
    },
}


def run(cfg: Config, args: dict[str, Any]) -> str:
    service = args.get("service")
    signals = args.get("signals", [])

    if not isinstance(signals, list) or not signals:
        return "Error: 'signals' must be a non-empty list of signal types."

    invalid = [s for s in signals if s not in VALID_SIGNALS]
    if invalid:
        return (
            f"Error: invalid signal types {invalid}. "
            f"Valid: {sorted(VALID_SIGNALS)}"
        )

    matches = match_runbooks(signals=signals, service=service)

    if not matches:
        return (
            f"No runbooks matched (service={service!r}, signals={signals}). "
            f"Either no runbook covers this scenario yet, or the trigger "
            f"definitions don't align."
        )

    lines = [f"Found {len(matches)} applicable runbook(s):", ""]
    for rb in matches:
        lines.append(f"## `{rb.id}`")
        lines.append(f"{rb.description}")
        lines.append(f"- Checks: {len(rb.checks)}")
        lines.append(f"- Remedies: {len(rb.remedies)}")
        # List the triggers that matched
        matched_triggers = [
            t for t in rb.triggers
            if t.signal in signals and (not t.service or t.service == service)
        ]
        lines.append(
            f"- Matching triggers: "
            + ", ".join(
                f"{t.signal}"
                + (f"@{t.service}" if t.service else "")
                for t in matched_triggers
            )
        )
        lines.append("")

    lines.append(
        "Use `execute_runbook_checks` with the runbook id to run its "
        "diagnostic checks. Use `propose_remedy` to see remediation options."
    )
    return "\n".join(lines).strip()