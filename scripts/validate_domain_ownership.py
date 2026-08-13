"""Validate Static Web App custom-domain ownership across environments."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

_CUSTOM_DOMAIN_PATTERN = re.compile(r'^custom_domain\s*=\s*"([^"]*)"', re.MULTILINE)


@dataclass(frozen=True)
class DomainOwnershipResult:
    dev_domain: str
    prd_domain: str
    requires_transfer: bool


def extract_custom_domain(tfvars_text: str) -> str:
    match = _CUSTOM_DOMAIN_PATTERN.search(tfvars_text)
    if match is None:
        raise ValueError("tfvars file must set custom_domain explicitly")
    return match.group(1).strip()


def read_custom_domain(tfvars_path: Path) -> str:
    return extract_custom_domain(tfvars_path.read_text())


def parse_bool(raw_value: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"Invalid boolean value: {raw_value!r}")


def validate_domain_ownership(
    *,
    dev_domain: str,
    prd_domain: str,
    target_env: str,
    allow_transfer: bool,
) -> DomainOwnershipResult:
    if target_env not in {"dev", "prd"}:
        raise ValueError("target_env must be 'dev' or 'prd'")

    if prd_domain == "":
        raise ValueError("prd.tfvars must set a non-empty custom_domain")

    requires_transfer = dev_domain != "" and dev_domain == prd_domain
    if requires_transfer and not (target_env == "prd" and allow_transfer):
        raise ValueError(
            "dev and prd currently claim the same custom domain. "
            "Set distinct custom_domain values, or run a controlled prod transfer "
            "with workflow_dispatch allow_domain_transfer=true."
        )

    return DomainOwnershipResult(
        dev_domain=dev_domain,
        prd_domain=prd_domain,
        requires_transfer=requires_transfer,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-tfvars", type=Path, required=True, help="Path to dev tfvars")
    parser.add_argument("--prd-tfvars", type=Path, required=True, help="Path to prod tfvars")
    parser.add_argument("--target-env", choices=["dev", "prd"], required=True, help="Deploy target env")
    parser.add_argument(
        "--allow-transfer",
        default="false",
        help="Boolean toggle for controlled prod custom-domain transfer",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    allow_transfer = parse_bool(args.allow_transfer)
    result = validate_domain_ownership(
        dev_domain=read_custom_domain(args.dev_tfvars),
        prd_domain=read_custom_domain(args.prd_tfvars),
        target_env=args.target_env,
        allow_transfer=allow_transfer,
    )

    if result.requires_transfer:
        print(f"Domain ownership check passed with controlled transfer override: {result.prd_domain}")
    else:
        print(f"Domain ownership check passed: dev={result.dev_domain or '<none>'} prd={result.prd_domain}")


if __name__ == "__main__":
    main()
