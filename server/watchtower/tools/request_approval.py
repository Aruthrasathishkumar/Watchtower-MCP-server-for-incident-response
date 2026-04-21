"""request_approval MCP tool.

Claude calls this to formally ask for operator consent before running a
remedy. Returns a proposal id and tells Claude what the operator needs
to do.
"""
from __future__ import annotations

import logging
from typing import Any

from ..approval import create_request
from ..config import Config
from ..runbooks import runbook_by_id


log = logging.getLogger(__name__)


TOOL_NAME = "request_approval"


TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Request operator approval to execute a runbook remedy. This creates "
        "a pending approval record and tells the operator how to approve it "
        "via the CLI.\n\n"
        "The workflow:\n"
        "1. You call `request_approval` with the runbook, remedy, and your "
        "reasoning.\n"
        "2. WatchTower returns a proposal id.\n"
        "3. You tell the operator to run "
        "`python -m watchtower.cli.approve <proposal_id>` in their terminal.\n"
        "4. The operator reviews and approves; the CLI prints a token.\n"
        "5. The operator pastes the token back into the chat.\n"
        "6. You call `execute_approved_remedy` with that token.\n\n"
        "Call this tool only when you have clear evidence justifying the "
        "remedy. The operator will see your rationale; make it specific."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "runbook_id": {"type": "string"},
            "remedy_id": {"type": "string"},
            "rationale": {
                "type": "string",
                "description": (
                    "Why this remedy is needed. Cite specific signals "
                    "(log burst at X time, pod restart count Y, etc.). "
                    "The operator uses this to decide."
                ),
            },
        },
        "required": ["runbook_id", "remedy_id", "rationale"],
    },
}


def run(cfg: Config, args: dict[str, Any]) -> str:
    runbook_id = args.get("runbook_id")
    remedy_id = args.get("remedy_id")
    rationale = args.get("rationale", "")

    if not runbook_id or not remedy_id:
        return "Error: runbook_id and remedy_id are required."

    # Validate the runbook + remedy exist before creating the request
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

    proposal_id = create_request(
        cfg,
        runbook_id=runbook_id,
        remedy_id=remedy_id,
        rationale=rationale,
    )

    return (
        f"# Approval requested\n\n"
        f"- **Proposal ID:** `{proposal_id}`\n"
        f"- **Runbook:** `{runbook_id}`\n"
        f"- **Remedy:** `{remedy_id}` — {remedy.description}\n"
        f"- **Safety:** {remedy.safety}\n"
        f"- **Command:** `{remedy.command or '(no-op)'}`\n"
        f"- **Rationale given:** {rationale}\n\n"
        f"**Next step — the operator must approve.** Ask them to run:\n\n"
        f"```\n"
        f"python -m watchtower.cli.approve {proposal_id}\n"
        f"```\n\n"
        f"They'll review the proposal, approve or deny, and the CLI will "
        f"print a token if they approved. Have them paste the token back "
        f"into this conversation, then call `execute_approved_remedy` with "
        f"it to run the remedy."
    )