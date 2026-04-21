"""Tests for approval.py — HMAC token signing and verification.

These are the highest-value tests in the suite: if any of them fail,
the security model is compromised. Every test isolates a single
property.
"""
from __future__ import annotations

import time

import pytest

from watchtower.approval import (
    ApprovalTokenPayload,
    CURRENT_TOKEN_VERSION,
    TokenError,
    sign_token,
    verify_token,
)


# helpers 

def _make_payload(
    *,
    pid: str = "test-proposal-123",
    rb: str = "checkout-latency",
    rid: str = "restart_deployment",
    approver: str = "operator",
    issued_at_offset: int = 0,
    expires_in: int = 300,
    nonce: str = "abc123nonce",
    version: int = CURRENT_TOKEN_VERSION,
) -> ApprovalTokenPayload:
    now = int(time.time())
    return ApprovalTokenPayload(
        version=version,
        proposal_id=pid,
        runbook_id=rb,
        remedy_id=rid,
        approver=approver,
        issued_at=now + issued_at_offset,
        expires_at=now + issued_at_offset + expires_in,
        nonce=nonce,
    )


# tests 

class TestSignAndVerify:
    """Round-trip: sign a token, verify it, get the payload back."""

    def test_round_trip_returns_same_payload(self):
        secret = "some-secret"
        payload = _make_payload()
        token = sign_token(payload, secret)
        decoded = verify_token(token, secret)

        assert decoded.proposal_id == payload.proposal_id
        assert decoded.runbook_id == payload.runbook_id
        assert decoded.remedy_id == payload.remedy_id
        assert decoded.approver == payload.approver
        assert decoded.nonce == payload.nonce

    def test_token_has_two_parts_separated_by_dot(self):
        token = sign_token(_make_payload(), "some-secret")
        parts = token.split(".")
        assert len(parts) == 2
        assert parts[0]  # payload is non-empty
        assert parts[1]  # signature is non-empty


class TestTamperDetection:
    """If someone flips a bit, verification MUST fail."""

    def test_flipped_signature_character_rejected(self):
        secret = "some-secret"
        token = sign_token(_make_payload(), secret)
        # Flip the last char of the signature
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        with pytest.raises(TokenError, match="Signature mismatch"):
            verify_token(tampered, secret)

    def test_flipped_payload_character_rejected(self):
        secret = "some-secret"
        token = sign_token(_make_payload(), secret)
        # Flip a character in the payload half
        payload_part, sig_part = token.split(".")
        tampered_payload = payload_part[:5] + (
            "A" if payload_part[5] != "A" else "B"
        ) + payload_part[6:]
        tampered = f"{tampered_payload}.{sig_part}"
        with pytest.raises(TokenError):
            verify_token(tampered, secret)

    def test_wrong_secret_rejected(self):
        token = sign_token(_make_payload(), "correct-secret")
        with pytest.raises(TokenError, match="Signature mismatch"):
            verify_token(token, "wrong-secret")


class TestExpiry:
    """Tokens past their expires_at must be rejected."""

    def test_expired_token_rejected(self):
        secret = "some-secret"
        # Token that expired 10 seconds ago
        payload = _make_payload(issued_at_offset=-600, expires_in=300)
        token = sign_token(payload, secret)
        with pytest.raises(TokenError, match="expired"):
            verify_token(token, secret)


class TestMalformedTokens:
    """Garbage input should raise TokenError, never crash."""

    def test_no_dot_separator(self):
        with pytest.raises(TokenError, match="Malformed token"):
            verify_token("not-a-valid-token", "secret")

    def test_empty_string(self):
        with pytest.raises(TokenError):
            verify_token("", "secret")

    def test_unsupported_version(self):
        secret = "some-secret"
        payload = _make_payload(version=99)
        token = sign_token(payload, secret)
        with pytest.raises(TokenError, match="version"):
            verify_token(token, secret)


class TestEmptySecret:
    """Signing without a server secret must fail fast (config bug)."""

    def test_sign_without_secret_raises(self):
        with pytest.raises(TokenError, match="APPROVAL_SECRET"):
            sign_token(_make_payload(), "")

    def test_verify_without_secret_raises(self):
        with pytest.raises(TokenError, match="secret"):
            verify_token("anything.anything", "")