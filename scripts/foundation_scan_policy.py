"""Strict metadata gate for the owner's two foundation-only scanner exceptions."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from scripts.application_contract import ContractError, decode, read_artifact

POLICY = Path("infra/tofu/foundation/.trivyignore.yaml")
APPROVED_IDS = frozenset({"AVD-AZU-0010", "AVD-AZU-0057"})
APPROVED_EXPIRY = date(2026, 11, 27)
APPROVAL = "https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/pull/1633#issuecomment-6493579386"


def validate_policy(raw: bytes, today: date) -> dict[str, object]:
    """Validate JSON-form YAML without introducing a separate YAML parser dependency."""
    value = decode(raw)
    if not isinstance(value, dict) or set(value) != {"misconfigurations"}:
        raise ContractError("foundation policy may contain only its approved misconfiguration exceptions")
    entries = value["misconfigurations"]
    if not isinstance(entries, list) or len(entries) != len(APPROVED_IDS):
        raise ContractError("foundation policy requires exactly two approved exceptions")
    identifiers = {_validate_entry(entry, today) for entry in entries}
    if identifiers != APPROVED_IDS:
        raise ContractError("foundation exception IDs differ from owner approval; no key-expiry exception")
    return value


def _validate_entry(entry: object, today: date) -> str:
    fields = {"id", "paths", "expired_at", "statement"}
    if not isinstance(entry, dict) or set(entry) != fields:
        raise ContractError("exception fields must exactly include ID, paths, expiry and approval statement")
    if entry["paths"] != ["main.tf"]:
        raise ContractError("foundation exception path must be exactly scanner-reported main.tf")
    if not isinstance(entry["id"], str) or not isinstance(entry["expired_at"], str):
        raise ContractError("exception ID and expiry must be strings")
    try:
        expiry = date.fromisoformat(entry["expired_at"][:10])
    except ValueError as exc:
        raise ContractError("exception expiry must be an ISO UTC midnight timestamp") from exc
    if entry["expired_at"] != f"{expiry.isoformat()}T00:00:00Z":
        raise ContractError("exception expiry must be an ISO UTC midnight timestamp")
    if expiry <= today:
        raise ContractError(f"foundation exception expired on {expiry.isoformat()}")
    if expiry != APPROVED_EXPIRY:
        raise ContractError("foundation exception expiry differs from owner-approved 2026-11-27")
    statement = entry["statement"]
    if not isinstance(statement, str) or "Owner approved 2026-10-29" not in statement or APPROVAL not in statement:
        raise ContractError("exception must retain its explicit owner approval reference")
    return entry["id"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", nargs="?", type=Path, default=POLICY)
    args = parser.parse_args()
    try:
        validate_policy(read_artifact(args.policy), datetime.now(UTC).date())
    except (ContractError, OSError) as exc:
        print(f"foundation scanner policy error: {exc}", file=sys.stderr)
        return 1
    print("Validated two foundation-only exceptions; expiry 2026-11-27, no inherited or key-expiry exception.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
