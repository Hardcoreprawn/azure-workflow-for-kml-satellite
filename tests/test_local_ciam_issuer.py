"""Contract tests for the isolated local OIDC issuer used by API verification."""

from __future__ import annotations

import jwt
import pytest


def test_local_tokens_are_signed_api_tokens_with_distinct_test_identities(monkeypatch: pytest.MonkeyPatch) -> None:
    import local_ciam_issuer as issuer

    monkeypatch.setenv("LOCAL_CIAM_AUTHORITY", "http://local-ciam:8080")
    monkeypatch.setenv("LOCAL_CIAM_TENANT_ID", "local-dev-tenant")
    monkeypatch.setenv("LOCAL_CIAM_API_AUDIENCE", "api://local-dev-audience")
    tokens = issuer._tokens()
    metadata = issuer._metadata_document()
    jwks = issuer._jwks_document()
    identities = ("owner", "wrong_user", "wrong_org")

    claims = {
        identity: jwt.decode(
            tokens[identity],
            key=issuer._private_key.public_key(),
            algorithms=["RS256"],
            audience="api://local-dev-audience",
            issuer="http://local-ciam:8080/local-dev-tenant/v2.0",
            options={"require": ["exp", "iss", "aud", "nbf", "tid", "oid", "ver", "scp"]},
        )
        for identity in identities
    }

    assert metadata == {
        "issuer": "http://local-ciam:8080/local-dev-tenant/v2.0",
        "jwks_uri": "http://local-ciam:8080/jwks",
    }
    assert jwks["keys"][0]["kid"] == jwt.get_unverified_header(tokens["owner"])["kid"]
    assert {claims[identity]["oid"] for identity in identities} == {
        "local-verifier-owner",
        "local-verifier-wrong-user",
        "local-verifier-wrong-org",
    }
    assert all(claim["scp"] == "User.Read" for claim in claims.values())
