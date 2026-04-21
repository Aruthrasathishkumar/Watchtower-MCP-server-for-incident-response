"""Approval token signing, verification, and the approval broker module.

Implements the security model from docs/rfc-security-model.md.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from .config import Config
from .db import connection


log = logging.getLogger(__name__)


#  shape and crypto
CURRENT_TOKEN_VERSION = 1


@dataclass
class ApprovalTokenPayload:
    """The decoded contents of an approval token."""
    version: int
    proposal_id: str
    runbook_id: str
    remedy_id: str
    approver: str
    issued_at: int
    expires_at: int
    nonce: str

    def to_dict(self) -> dict:
        return {
            "v": self.version,
            "pid": self.proposal_id,
            "rb": self.runbook_id,
            "rid": self.remedy_id,
            "approver": self.approver,
            "iat": self.issued_at,
            "exp": self.expires_at,
            "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ApprovalTokenPayload":
        return cls(
            version=d["v"],
            proposal_id=d["pid"],
            runbook_id=d["rb"],
            remedy_id=d["rid"],
            approver=d["approver"],
            issued_at=d["iat"],
            expires_at=d["exp"],
            nonce=d["nonce"],
        )


class TokenError(Exception):
    """Any problem with an approval token."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def _sign(payload_bytes: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()


def sign_token(payload: ApprovalTokenPayload, secret: str) -> str:
    """Produce a signed token string."""
    if not secret:
        raise TokenError("WATCHTOWER_APPROVAL_SECRET is not set — cannot sign tokens.")
    payload_json = json.dumps(payload.to_dict(), sort_keys=True,
                              separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64encode(payload_json)
    sig = _sign(payload_b64.encode("ascii"), secret)
    sig_b64 = _b64encode(sig)
    return f"{payload_b64}.{sig_b64}"


def verify_token(token: str, secret: str) -> ApprovalTokenPayload:
    """Verify signature + expiry. Returns decoded payload on success.

    Raises TokenError on any failure.
    """
    if not secret:
        raise TokenError("Server secret not configured.")
    try:
        payload_b64, sig_b64 = token.strip().split(".")
    except ValueError as exc:
        raise TokenError(f"Malformed token: {exc}")

    expected_sig = _sign(payload_b64.encode("ascii"), secret)
    actual_sig = _b64decode(sig_b64)

    # Constant-time compare
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise TokenError("Signature mismatch.")

    try:
        payload_bytes = _b64decode(payload_b64)
        payload = ApprovalTokenPayload.from_dict(json.loads(payload_bytes))
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise TokenError(f"Unable to decode payload: {exc}")

    if payload.version != CURRENT_TOKEN_VERSION:
        raise TokenError(f"Unsupported token version {payload.version}")

    now = int(time.time())
    if now >= payload.expires_at:
        raise TokenError(
            f"Token expired at {payload.expires_at} (now {now})."
        )

    return payload


# Broker: request, approve, audit 

def create_request(cfg: Config, runbook_id: str, remedy_id: str,
                   rationale: str, requested_by: str = "claude") -> str:
    """Record an approval request. Returns the proposal_id (uuid string)."""
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO approval_requests
                (runbook_id, remedy_id, rationale, requested_by, status)
            VALUES (%s, %s, %s, %s, 'pending')
            RETURNING id
            """,
            (runbook_id, remedy_id, rationale, requested_by),
        )
        proposal_id = str(cur.fetchone()["id"])
        # Also log to audit
        cur.execute(
            """
            INSERT INTO approval_audit (proposal_id, action, actor)
            VALUES (%s, 'requested', %s)
            """,
            (proposal_id, requested_by),
        )
    return proposal_id


def load_request(cfg: Config, proposal_id: str) -> Optional[dict]:
    """Fetch an approval request row, or None."""
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, runbook_id, remedy_id, rationale, requested_by,"
            "       requested_at, status"
            " FROM approval_requests WHERE id = %s",
            (proposal_id,),
        )
        row = cur.fetchone()
    return row


def approve_request(cfg: Config, proposal_id: str, approver: str,
                    runbook_id: str, remedy_id: str) -> str:
    """Mark a request approved and generate a token. Returns the token string."""
    now = int(time.time())
    payload = ApprovalTokenPayload(
        version=CURRENT_TOKEN_VERSION,
        proposal_id=proposal_id,
        runbook_id=runbook_id,
        remedy_id=remedy_id,
        approver=approver,
        issued_at=now,
        expires_at=now + cfg.approval_ttl_seconds,
        nonce=secrets.token_hex(16),
    )
    token = sign_token(payload, cfg.approval_secret)

    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE approval_requests SET status = 'approved' WHERE id = %s",
            (proposal_id,),
        )
        cur.execute(
            """
            INSERT INTO approval_audit
                (proposal_id, action, actor, token_nonce, token_payload)
            VALUES (%s, 'approved', %s, %s, %s)
            """,
            (proposal_id, approver, payload.nonce, Jsonb(payload.to_dict())),
        )

    return token


def nonce_already_used(cfg: Config, nonce: str) -> bool:
    """Check if a token's nonce was ever marked as executed."""
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM approval_audit "
            "WHERE token_nonce = %s AND action IN ('executed', 'execution_failed') "
            "LIMIT 1",
            (nonce,),
        )
        return cur.fetchone() is not None


def record_audit(cfg: Config, proposal_id: Optional[str], action: str,
                 actor: str, token_nonce: Optional[str] = None,
                 token_payload: Optional[dict] = None,
                 stdout: Optional[str] = None, stderr: Optional[str] = None,
                 exit_code: Optional[int] = None) -> None:
    """Append a row to the audit log."""
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO approval_audit (
                proposal_id, action, actor,
                token_nonce, token_payload,
                stdout, stderr, exit_code
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                proposal_id, action, actor,
                token_nonce, Jsonb(token_payload) if token_payload else None,
                stdout, stderr, exit_code,
            ),
        )


def mark_executed(cfg: Config, proposal_id: str) -> None:
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE approval_requests SET status = 'executed' WHERE id = %s",
            (proposal_id,),
        )