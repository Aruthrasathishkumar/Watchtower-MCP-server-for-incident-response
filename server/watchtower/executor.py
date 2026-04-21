"""Remedy executor.

Given a validated approval token, runs the corresponding remedy command.
Refuses to run unless every safety check passes. Every attempt — success
or failure — is written to the audit log.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional

from .approval import (
    ApprovalTokenPayload,
    TokenError,
    load_request,
    mark_executed,
    nonce_already_used,
    record_audit,
    verify_token,
)
from .config import Config
from .runbooks import runbook_by_id


log = logging.getLogger(__name__)


# Hard limits
MAX_COMMAND_TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 50_000


@dataclass
class ExecutionResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    error: Optional[str] = None  # only set if ok == False


def execute(cfg: Config, token: str,
            actor: str = "claude") -> ExecutionResult:
    """Verify token, check all invariants, run the command, audit.

    Returns an ExecutionResult. Audit log rows are written even on failure
    so we have forensic record of every attempt.
    """
    # Step 1: decode and verify signature + expiry
    try:
        payload = verify_token(token, cfg.approval_secret)
    except TokenError as exc:
        # We don't have a proposal_id yet, but log what we can
        record_audit(
            cfg,
            proposal_id=None,
            action="invalid_token",
            actor=actor,
            token_nonce=None,
            token_payload=None,
            stderr=str(exc),
        )
        return ExecutionResult(
            ok=False, stdout="", stderr="", exit_code=-1,
            error=f"Token rejected: {exc}",
        )

    # Step 2: check replay
    if nonce_already_used(cfg, payload.nonce):
        record_audit(
            cfg,
            proposal_id=payload.proposal_id,
            action="replay_attempt",
            actor=actor,
            token_nonce=payload.nonce,
            token_payload=payload.to_dict(),
        )
        return ExecutionResult(
            ok=False, stdout="", stderr="", exit_code=-1,
            error="Token already consumed (replay attempt).",
        )

    # Step 3: check the request still exists in a valid state
    req = load_request(cfg, payload.proposal_id)
    if req is None:
        record_audit(
            cfg,
            proposal_id=None,
            action="invalid_token",
            actor=actor,
            token_nonce=payload.nonce,
            token_payload=payload.to_dict(),
            stderr="Approval request not found in database.",
        )
        return ExecutionResult(
            ok=False, stdout="", stderr="", exit_code=-1,
            error="Approval request not found.",
        )

    if req["status"] not in ("approved",):
        record_audit(
            cfg,
            proposal_id=payload.proposal_id,
            action="invalid_token",
            actor=actor,
            token_nonce=payload.nonce,
            token_payload=payload.to_dict(),
            stderr=f"Request status is {req['status']}, not approved.",
        )
        return ExecutionResult(
            ok=False, stdout="", stderr="", exit_code=-1,
            error=f"Approval request is in status '{req['status']}', "
                  "cannot execute.",
        )

    # Step 4: re-parse the runbook and find the remedy
    # This protects against "approved against one version, executed against
    # another" race conditions if the runbook file changed.
    rb = runbook_by_id(payload.runbook_id)
    if rb is None:
        record_audit(
            cfg,
            proposal_id=payload.proposal_id,
            action="execution_failed",
            actor=actor,
            token_nonce=payload.nonce,
            token_payload=payload.to_dict(),
            stderr=f"Runbook '{payload.runbook_id}' no longer exists.",
        )
        return ExecutionResult(
            ok=False, stdout="", stderr="", exit_code=-1,
            error=f"Runbook '{payload.runbook_id}' no longer exists.",
        )

    remedy = next((r for r in rb.remedies if r.id == payload.remedy_id), None)
    if remedy is None:
        record_audit(
            cfg,
            proposal_id=payload.proposal_id,
            action="execution_failed",
            actor=actor,
            token_nonce=payload.nonce,
            token_payload=payload.to_dict(),
            stderr=f"Remedy '{payload.remedy_id}' no longer exists in runbook.",
        )
        return ExecutionResult(
            ok=False, stdout="", stderr="", exit_code=-1,
            error=f"Remedy '{payload.remedy_id}' no longer exists in runbook.",
        )

    command = remedy.command.strip()

    # Step 5: handle no-op remedies (command is empty)
    if not command:
        record_audit(
            cfg,
            proposal_id=payload.proposal_id,
            action="executed",
            actor=actor,
            token_nonce=payload.nonce,
            token_payload=payload.to_dict(),
            stdout="(no-op remedy — no command to execute)",
            stderr="",
            exit_code=0,
        )
        mark_executed(cfg, payload.proposal_id)
        return ExecutionResult(
            ok=True, stdout="(no-op remedy)", stderr="", exit_code=0,
        )

    # Step 6: reject placeholders like <POD_NAME> — we don't do substitution
    if "<" in command and ">" in command:
        record_audit(
            cfg,
            proposal_id=payload.proposal_id,
            action="execution_failed",
            actor=actor,
            token_nonce=payload.nonce,
            token_payload=payload.to_dict(),
            stderr=f"Command contains unresolved placeholders: {command}",
        )
        return ExecutionResult(
            ok=False, stdout="", stderr="", exit_code=-1,
            error=(
                f"Refusing to execute: command contains placeholders "
                f"('{command}'). Parameterized remedies require the "
                f"Phase 15+ variable-substitution flow."
            ),
        )

    # Step 7: split and run. shlex.split is safe; no shell=True.
    log.info(
        "Executing approved remedy: runbook=%s remedy=%s proposal=%s",
        payload.runbook_id, payload.remedy_id, payload.proposal_id,
    )
    try:
        completed = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=MAX_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        record_audit(
            cfg,
            proposal_id=payload.proposal_id,
            action="execution_failed",
            actor=actor,
            token_nonce=payload.nonce,
            token_payload=payload.to_dict(),
            stderr=f"Timeout after {MAX_COMMAND_TIMEOUT_SECONDS}s",
            exit_code=-1,
        )
        return ExecutionResult(
            ok=False, stdout="", stderr="", exit_code=-1,
            error=f"Command timed out after {MAX_COMMAND_TIMEOUT_SECONDS}s.",
        )
    except FileNotFoundError as exc:
        record_audit(
            cfg,
            proposal_id=payload.proposal_id,
            action="execution_failed",
            actor=actor,
            token_nonce=payload.nonce,
            token_payload=payload.to_dict(),
            stderr=str(exc),
            exit_code=-1,
        )
        return ExecutionResult(
            ok=False, stdout="", stderr="", exit_code=-1,
            error=f"Command not found on PATH: {exc}",
        )
    except Exception as exc:
        record_audit(
            cfg,
            proposal_id=payload.proposal_id,
            action="execution_failed",
            actor=actor,
            token_nonce=payload.nonce,
            token_payload=payload.to_dict(),
            stderr=str(exc),
            exit_code=-1,
        )
        return ExecutionResult(
            ok=False, stdout="", stderr="", exit_code=-1,
            error=f"Unexpected error: {exc}",
        )

    stdout = completed.stdout[:MAX_OUTPUT_BYTES]
    stderr = completed.stderr[:MAX_OUTPUT_BYTES]
    action = "executed" if completed.returncode == 0 else "execution_failed"

    record_audit(
        cfg,
        proposal_id=payload.proposal_id,
        action=action,
        actor=actor,
        token_nonce=payload.nonce,
        token_payload=payload.to_dict(),
        stdout=stdout,
        stderr=stderr,
        exit_code=completed.returncode,
    )

    if completed.returncode == 0:
        mark_executed(cfg, payload.proposal_id)

    return ExecutionResult(
        ok=(completed.returncode == 0),
        stdout=stdout,
        stderr=stderr,
        exit_code=completed.returncode,
    )