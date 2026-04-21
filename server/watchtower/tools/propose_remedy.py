"""propose_remedy MCP tool.

Returns a structured proposal for a runbook's remedy. DOES NOT EXECUTE —
execution requires the Approval Broker (Phase 14). This tool exists so
Claude can show the operator a clear 'here is what I would do' before
any consent is given.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..config import Config
from ..runbooks import runbook_by_id


log = logging.getLogger(__name__)


TOOL_NAME = "propose_remedy"


TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Propose (do NOT execute) a remedy from a runbook. Returns a "
        "structured proposal describing what would be done, its safety "
        "level, and whether it requires approval.\n\n"
        "Actual execution is not implemented in this version — it requires "
        "Phase 14's Approval Broker with HMAC-signed consent tokens. The "
        "proposal is the planning step; the operator can then manually run "
        "the command or wait for the executor."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "runbook_id": {
                "type": "string",
                "description": "The runbook id.",
            },
            "remedy_id": {
                "type": "string",
                "description": "The remedy id within the runbook.",
            },
        },
        "required": ["runbook_id", "remedy_id"],
    },
}


def run(cfg: Config, args: dict[str, Any]) -> str:
    runbook_id = args.get("runbook_id")
    remedy_id = args.get("remedy_id")

    if not runbook_id or not remedy_id:
        return "Error: both 'runbook_id' and 'remedy_id' are required."

    rb = runbook_by_id(runbook_id)
    if rb is None:
        return f"Error: runbook '{runbook_id}' not found."

    remedy = next((r for r in rb.remedies if r.id == remedy_id), None)
    if remedy is None:
        available = ", ".join(r.id for r in rb.remedies) or "(none)"
        return (
            f"Error: remedy '{remedy_id}' not found in runbook "
            f"'{runbook_id}'. Available: {available}"
        )

    proposal = {
        "runbook_id": rb.id,
        "remedy_id": remedy.id,
        "description": remedy.description,
        "command": remedy.command,
        "safety": remedy.safety,
        "requires_approval": remedy.requires_approval,
        "status": "proposed_only_not_executed",
        "note": (
            "This proposal is not executed. Phase 14's Approval Broker will "
            "add the signed-consent execution path."
        ),
    }

    lines = [
        f"# Remedy proposal: `{rb.id}` / `{remedy.id}`",
        "",
        f"**What:** {remedy.description}",
        f"**Safety:** {remedy.safety}",
        f"**Requires approval:** {remedy.requires_approval}",
        "",
        "**Command that would run:**",
        "```",
        remedy.command or "(no command — manual/informational remedy)",
        "```",
        "",
        "**Status:** ⚠️ PROPOSED ONLY — not executed.",
        "",
        "Phase 14's Approval Broker will add the signed-consent executor. "
        "For now, the operator can run the command manually after reviewing "
        "it, or wait for Phase 14.",
        "",
        "**Full proposal (JSON):**",
        "```json",
        json.dumps(proposal, indent=2),
        "```",
    ]
    return "\n".join(lines).strip()