"""execute_approved_remedy MCP tool.

Takes a signed approval token, verifies every safety property, and runs
the approved remedy. All attempts are audited.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import Config
from ..executor import execute


log = logging.getLogger(__name__)


TOOL_NAME = "execute_approved_remedy"


TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Execute a runbook remedy that the operator has approved. Takes a "
        "signed approval token (from the CLI). Verifies the signature, "
        "checks expiry and replay, re-validates the runbook still exists, "
        "and runs the command. Every attempt — success or failure — is "
        "logged to the audit table.\n\n"
        "Tokens are single-use and expire 5 minutes after approval. If you "
        "get a rejection (replay, expired, tampered), that's the security "
        "model working — ask the operator for a fresh approval rather than "
        "retrying."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "token": {
                "type": "string",
                "description": (
                    "The signed approval token emitted by "
                    "`python -m watchtower.cli.approve`."
                ),
            },
        },
        "required": ["token"],
    },
}


def run(cfg: Config, args: dict[str, Any]) -> str:
    token = (args.get("token") or "").strip()
    if not token:
        return "Error: 'token' is required."

    result = execute(cfg, token, actor="claude")

    if not result.ok:
        return (
            f"# Execution refused\n\n"
            f"**Error:** {result.error}\n\n"
            f"No command was run. The refusal is audited; the operator can "
            f"inspect `approval_audit` for forensic details."
        )

    return (
        f"# Execution succeeded\n\n"
        f"**Exit code:** {result.exit_code}\n\n"
        f"**stdout:**\n```\n{result.stdout or '(empty)'}\n```\n\n"
        f"**stderr:**\n```\n{result.stderr or '(empty)'}\n```\n\n"
        f"The operation is logged in `approval_audit` and the approval "
        f"request is marked executed."
    )