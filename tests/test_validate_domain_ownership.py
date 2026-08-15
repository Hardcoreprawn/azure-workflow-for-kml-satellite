from __future__ import annotations

import pytest

from scripts import validate_domain_ownership as domain_guard


@pytest.mark.parametrize("raw_value", ["true", "True", "1", "yes", " TRUE "])
def test_parse_bool_accepts_truthy_values(raw_value: str) -> None:
    assert domain_guard.parse_bool(raw_value) is True


@pytest.mark.parametrize("raw_value", ["false", "False", "0", "no", " FALSE "])
def test_parse_bool_accepts_falsy_values(raw_value: str) -> None:
    assert domain_guard.parse_bool(raw_value) is False


def test_parse_bool_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="Invalid boolean value"):
        domain_guard.parse_bool("maybe")


def test_extract_custom_domain_reads_value() -> None:
    assert domain_guard.extract_custom_domain('custom_domain = "canopex.hrdcrprwn.com"\n') == "canopex.hrdcrprwn.com"


def test_extract_custom_domain_raises_when_missing() -> None:
    with pytest.raises(ValueError, match="custom_domain"):
        domain_guard.extract_custom_domain('environment = "dev"\n')


def test_validate_ownership_rejects_shared_domain_without_override() -> None:
    with pytest.raises(ValueError, match="same custom domain"):
        domain_guard.validate_domain_ownership(
            dev_domain="canopex.hrdcrprwn.com",
            prd_domain="canopex.hrdcrprwn.com",
            target_env="prd",
            allow_transfer=False,
        )


def test_validate_ownership_allows_shared_domain_with_explicit_prod_override() -> None:
    result = domain_guard.validate_domain_ownership(
        dev_domain="canopex.hrdcrprwn.com",
        prd_domain="canopex.hrdcrprwn.com",
        target_env="prd",
        allow_transfer=True,
    )
    assert result.requires_transfer is True


def test_validate_ownership_rejects_shared_domain_override_targeting_dev() -> None:
    """allow_transfer must not bypass the guard for a non-prod deploy target."""
    with pytest.raises(ValueError, match="same custom domain"):
        domain_guard.validate_domain_ownership(
            dev_domain="canopex.hrdcrprwn.com",
            prd_domain="canopex.hrdcrprwn.com",
            target_env="dev",
            allow_transfer=True,
        )


def test_validate_ownership_rejects_empty_prd_domain() -> None:
    with pytest.raises(ValueError, match=r"prd\.tfvars must set a non-empty custom_domain"):
        domain_guard.validate_domain_ownership(
            dev_domain="",
            prd_domain="",
            target_env="prd",
            allow_transfer=False,
        )


def test_validate_ownership_accepts_distinct_domains() -> None:
    result = domain_guard.validate_domain_ownership(
        dev_domain="dev.canopex.hrdcrprwn.com",
        prd_domain="canopex.hrdcrprwn.com",
        target_env="prd",
        allow_transfer=False,
    )
    assert result.requires_transfer is False


def test_validate_ownership_accepts_blank_dev_domain() -> None:
    result = domain_guard.validate_domain_ownership(
        dev_domain="",
        prd_domain="canopex.hrdcrprwn.com",
        target_env="dev",
        allow_transfer=False,
    )
    assert result.requires_transfer is False


def test_validate_ownership_rejects_case_and_trailing_dot_collision() -> None:
    with pytest.raises(ValueError, match="same custom domain"):
        domain_guard.validate_domain_ownership(
            dev_domain="Dev.Example.com",
            prd_domain="dev.example.com.",
            target_env="prd",
            allow_transfer=False,
        )


def test_validate_ownership_allows_case_and_trailing_dot_collision_with_override() -> None:
    result = domain_guard.validate_domain_ownership(
        dev_domain="Dev.Example.com",
        prd_domain="dev.example.com.",
        target_env="prd",
        allow_transfer=True,
    )
    assert result.requires_transfer is True
