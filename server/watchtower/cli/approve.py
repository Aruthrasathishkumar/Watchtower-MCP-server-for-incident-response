"""Interactive CLI for approving a pending remedy.

Usage:
    python -m watchtower.cli.approve <proposal_id>

Shows the full proposal, prompts for confirmation, emits a signed token.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from ..approval import approve_request, load_request, record_audit
from ..config import configure_logging, load_config
from ..runbooks import runbook_by_id


def _show_proposal(cfg, proposal_id: str) -> dict:
    req = load_request(cfg, proposal_id)
    if req is None:
        print(f"Error: no approval request with id {proposal_id}", file=sys.stderr)
        sys.exit(2)

    if req["status"] != "pending":
        print(
            f"Error: request status is {req['status']}, cannot approve.",
            file=sys.stderr,
        )
        sys.exit(2)

    rb = runbook_by_id(req["runbook_id"])
    if rb is None:
        print(
            f"Error: runbook '{req['runbook_id']}' not found on disk.",
            file=sys.stderr,
        )
        sys.exit(2)

    remedy = next((r for r in rb.remedies if r.id == req["remedy_id"]), None)
    if remedy is None:
        print(
            f"Error: remedy '{req['remedy_id']}' not found in runbook.",
            file=sys.stderr,
        )
        sys.exit(2)

    print("=" * 72)
    print(f"Approval request {proposal_id}")
    print("=" * 72)
    print(f"Runbook:     {rb.id}")
    print(f"Remedy:      {remedy.id}")
    print(f"Description: {remedy.description}")
    print(f"Safety:      {remedy.safety}")
    print(f"Requested by: {req['requested_by']} at {req['requested_at']}")
    print()
    print("Command that will execute on approval:")
    print(f"    {remedy.command or '(no-op)'}")
    print()
    print("Rationale provided:")
    for line in (req.get("rationale") or "").splitlines() or ["(none)"]:
        print(f"    {line}")
    print()
    return {"request": req, "remedy": remedy, "runbook": rb}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Approve a pending WatchTower remedy request.",
    )
    parser.add_argument("proposal_id", help="Proposal UUID")
    parser.add_argument(
        "--approver",
        default=None,
        help="Approver identifier (defaults to $USER).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (for scripted use).",
    )
    args = parser.parse_args()

    cfg = load_config()
    configure_logging(cfg.log_level)

    info = _show_proposal(cfg, args.proposal_id)
    remedy = info["remedy"]

    if not args.yes:
        answer = input("Approve this remedy? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("Denied.")
            record_audit(
                cfg,
                proposal_id=args.proposal_id,
                action="denied",
                actor=args.approver or getpass.getuser(),
            )
            return 1

    approver = args.approver or getpass.getuser()
    token = approve_request(
        cfg,
        proposal_id=args.proposal_id,
        approver=approver,
        runbook_id=info["runbook"].id,
        remedy_id=remedy.id,
    )

    print()
    print("Approval token (valid for", cfg.approval_ttl_seconds, "seconds):")
    print()
    print(token)
    print()
    print(
        "Paste this token into Claude when it calls execute_approved_remedy."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())