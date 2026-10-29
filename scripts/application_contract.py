"""Strict, stdlib-only immutable application-governance wire contracts.

Import this module in foundation's consumer; do not duplicate the parser.
The external-provider adapter validates raw artifacts before grant declarations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast
from uuid import NAMESPACE_URL, uuid5

SCHEMA = "canopex.application-governance"
Stage = Literal["namespace", "prerequisites", "custody", "key", "encryption"]
STAGES: tuple[Stage, ...] = ("namespace", "prerequisites", "custody", "key", "encryption")
CRYPTO_OFFICER = "14b46e9e-c2b7-41b4-b07b-48a6ebf60603"
CRYPTO_SERVICE = "e147488a-f6f5-4113-8e2d-b22465e65bf6"
MAX_BYTES = 65536
# Transport envelopes contain several raw artifacts and nested JSON escaping.
MAX_ARTIFACT_BUNDLE_BYTES = 2 * 1024 * 1024
MAX_EXTERNAL_REQUEST_BYTES = 16 * 1024 * 1024
UUID_PATTERN = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
REVISION_PATTERN = r"[0-9a-f]{40}"
DIGEST_PATTERN = r"[0-9a-f]{64}"


class ContractError(ValueError):
    """A wire artifact does not match its explicitly approved context."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _object(value: object, fields: Sequence[str], label: str) -> dict[str, object]:
    _require(isinstance(value, dict), f"{label} must be an object")
    result = dict(value) if isinstance(value, dict) else {}
    _require(set(result) == set(fields), f"{label} fields must be exactly {sorted(fields)}")
    return result


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    _require(len(result) == len(pairs), "duplicate JSON fields are forbidden")
    return result


def decode(raw: bytes) -> object:
    """Decode bounded raw JSON without dropping duplicate keys or non-finite values."""
    return _decode_bounded(raw, MAX_BYTES, "artifact")


def decode_artifact_bundle(raw: bytes) -> object:
    """Decode a bounded transport bundle; consumers must still validate each artifact."""
    return _decode_bounded(raw, MAX_ARTIFACT_BUNDLE_BYTES, "artifact bundle")


def decode_external_request(raw: bytes) -> object:
    """Decode a bounded external-provider envelope, preserving strict JSON validation."""
    return _decode_bounded(raw, MAX_EXTERNAL_REQUEST_BYTES, "external request")


def _decode_bounded(raw: bytes, maximum: int, label: str) -> object:
    _require(isinstance(raw, bytes) and len(raw) <= maximum, f"{label} must be bounded raw bytes")
    try:
        return json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
    except ContractError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ContractError(f"invalid JSON: {exc}") from exc


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-finite JSON number: {value}")


def encode(value: object) -> bytes:
    """Canonical producer encoding; verification always hashes original received bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _uuid_comparison(value: object) -> bytes:
    """Fold UUID spellings only for comparison; never rewrite authenticated raw bytes."""
    return re.sub(UUID_PATTERN.encode(), lambda match: match[0].lower(), encode(value))


def _ids_equal(actual: object, expected: object) -> bool:
    return _uuid_comparison(actual) == _uuid_comparison(expected)


def _text(value: object, label: str, pattern: str = r"[\s\S]+") -> str:
    _require(isinstance(value, str), f"{label} must be a string")
    text = str(value)
    _require(re.fullmatch(pattern, text) is not None, f"invalid {label}")
    return text


@dataclass(frozen=True)
class Identity:
    resource_id: str
    client_id: str
    principal_id: str
    github_environment: str

    @classmethod
    def parse(cls, value: object) -> Identity:
        item = _object(value, ("resource_id", "client_id", "principal_id", "github_environment"), "identity")
        return cls(
            _text(item["resource_id"], "identity resource_id"),
            _text(item["client_id"], "client_id", UUID_PATTERN),
            _text(item["principal_id"], "principal_id", UUID_PATTERN),
            _text(item["github_environment"], "github_environment"),
        )


@dataclass(frozen=True)
class Backend:
    resource_group_name: str
    storage_account_name: str
    container_name: str
    key: str
    subscription_id: str
    tenant_id: str
    client_id: str
    use_azuread_auth: bool = True
    use_oidc: bool = True
    use_cli: bool = False

    @classmethod
    def parse(cls, value: object) -> Backend:
        fields = tuple(cls.__dataclass_fields__)
        item = _object(value, fields, "backend")
        for key, expected in (("use_azuread_auth", True), ("use_oidc", True), ("use_cli", False)):
            _require(item[key] is expected, f"backend {key} must be {expected}")
        return cls(
            resource_group_name=_text(item["resource_group_name"], "backend resource_group_name"),
            storage_account_name=_text(item["storage_account_name"], "backend storage_account_name"),
            container_name=_text(item["container_name"], "backend container_name"),
            key=_text(item["key"], "backend key"),
            subscription_id=_text(item["subscription_id"], "backend subscription_id"),
            tenant_id=_text(item["tenant_id"], "backend tenant_id"),
            client_id=_text(item["client_id"], "backend client_id"),
        )


@dataclass(frozen=True)
class ExpectedContext:
    environment: str
    tenant_id: str
    subscription_id: str
    project_code: str
    location: str
    vault_name: str
    governance_revision: str
    foundation_revision: str
    policy_revision: str
    bootstrap_sha256: str
    bootstrap_operator_principal_id: str
    bootstrap_encryption_principal_id: str
    foundation: Identity
    backend: Backend

    @classmethod
    def from_bytes(cls, raw: bytes) -> ExpectedContext:
        item = _object(decode(raw), tuple(cls.__dataclass_fields__), "expected context")
        result = cls(
            **{key: _text(item[key], key) for key in tuple(cls.__dataclass_fields__)[:12]},
            foundation=Identity.parse(item["foundation"]),
            backend=Backend.parse(item["backend"]),
        )
        result.validate()
        return result

    def validate(self) -> None:
        _require(self.environment in ("dev", "prd"), "environment must be dev or prd")
        for label, value, pattern in (
            ("tenant", self.tenant_id, UUID_PATTERN),
            ("subscription", self.subscription_id, UUID_PATTERN),
            ("project", self.project_code, r"[a-z0-9]{3,12}"),
            ("location", self.location, r"[a-z][a-z0-9]+"),
            ("vault name", self.vault_name, r"[a-z][a-z0-9-]{1,22}[a-z0-9]"),
            ("governance revision", self.governance_revision, REVISION_PATTERN),
            ("foundation revision", self.foundation_revision, REVISION_PATTERN),
            ("policy revision", self.policy_revision, REVISION_PATTERN),
            ("bootstrap SHA256", self.bootstrap_sha256, DIGEST_PATTERN),
            ("bootstrap operator", self.bootstrap_operator_principal_id, UUID_PATTERN),
            ("bootstrap encryption principal", self.bootstrap_encryption_principal_id, UUID_PATTERN),
        ):
            _text(value, label, pattern)

    @property
    def namespace_name(self) -> str:
        return f"rg-{self.project_code}-{self.environment}-application"

    @property
    def namespace_id(self) -> str:
        return f"/subscriptions/{self.subscription_id}/resourceGroups/{self.namespace_name}"

    @property
    def vault_id(self) -> str:
        return f"{self.namespace_id}/providers/Microsoft.KeyVault/vaults/{self.vault_name}"

    @property
    def vault_uri(self) -> str:
        return f"https://{self.vault_name}.vault.azure.net/"

    @property
    def role_definition_id(self) -> str:
        role_uuid = uuid5(
            NAMESPACE_URL, f"canopex/{self.subscription_id.lower()}/{self.environment}/foundation-application"
        )
        return self.role_id(str(role_uuid))

    def role_id(self, role_uuid: str) -> str:
        return f"/subscriptions/{self.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/{role_uuid}"


@dataclass(frozen=True)
class BootstrapContract:
    foundation: Identity
    workload: Identity
    release: Identity
    foundation_backend: Backend
    raw_sha256: str


def _bootstrap_identities(item: dict[str, object], expected: ExpectedContext) -> tuple[Identity, ...]:
    identities = _object(item["identities"], ("foundation", "workload", "release"), "identities")
    result = tuple(Identity.parse(identities[layer]) for layer in ("foundation", "workload", "release"))
    rg = f"/subscriptions/{expected.subscription_id}/resourceGroups/rg-{expected.project_code}-{expected.environment}-bootstrap"
    for layer, identity in zip(("foundation", "workload", "release"), result, strict=True):
        _require(
            _ids_equal(
                identity.resource_id,
                f"{rg}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-{expected.project_code}-{expected.environment}-{layer}",
            ),
            f"wrong {layer} identity ancestry",
        )
        _require(identity.github_environment == f"{expected.environment}-{layer}", f"wrong {layer} GitHub environment")
    _require(len({identity.principal_id.lower() for identity in result}) == 3, "deployment principals must be distinct")
    _require(len({identity.client_id.lower() for identity in result}) == 3, "deployment client IDs must be distinct")
    exclusions = {expected.bootstrap_operator_principal_id.lower(), expected.bootstrap_encryption_principal_id.lower()}
    _require(
        len(exclusions) == 2 and exclusions.isdisjoint(identity.principal_id.lower() for identity in result),
        "bootstrap custody/encryption principals must be distinct from deployment principals",
    )
    _require(_ids_equal(asdict(result[0]), asdict(expected.foundation)), "foundation principal/context mismatch")
    return result


def _bootstrap_backends(
    item: dict[str, object], identities: tuple[Identity, ...], expected: ExpectedContext
) -> Backend:
    backends = _object(item["backends"], ("foundation", "workload"), "backends")
    parsed = tuple(Backend.parse(backends[layer]) for layer in ("foundation", "workload"))
    for layer, backend, identity in zip(("foundation", "workload"), parsed, identities[:2], strict=True):
        _require(backend.container_name == layer and backend.key == "terraform.tfstate", f"wrong {layer} backend")
        _require(_ids_equal(backend.client_id, identity.client_id), f"wrong {layer} backend principal")
        _require(
            _ids_equal(backend.tenant_id, expected.tenant_id)
            and _ids_equal(backend.subscription_id, expected.subscription_id),
            f"wrong {layer} backend tenant/subscription",
        )
        _require(
            backend.resource_group_name == f"rg-{expected.project_code}-{expected.environment}-bootstrap",
            "wrong backend namespace",
        )
        _text(backend.storage_account_name, "backend storage account", r"[a-z0-9]{3,24}")
    _require(parsed[0].storage_account_name == parsed[1].storage_account_name, "backend accounts differ")
    _require(_ids_equal(asdict(parsed[0]), asdict(expected.backend)), "foundation backend/context mismatch")
    return parsed[0]


def parse_bootstrap(raw: bytes, expected: ExpectedContext) -> BootstrapContract:
    """Validate exact bootstrap v1 bytes and the independently approved foundation context."""
    expected.validate()
    _require(digest(raw) == expected.bootstrap_sha256, "bootstrap raw-byte SHA256 mismatch")
    item = _object(
        decode(raw),
        (
            "schema_version",
            "phase",
            "environment",
            "tenant_id",
            "subscription_id",
            "oidc_enabled",
            "encryption",
            "identities",
            "backends",
        ),
        "bootstrap",
    )
    _require(type(item["schema_version"]) is int and item["schema_version"] == 1, "unsupported bootstrap version")
    _require(item["phase"] == "state", "bootstrap must have reached state phase")
    _require(type(item["oidc_enabled"]) is bool, "oidc_enabled must be boolean")
    for field in ("environment", "tenant_id", "subscription_id"):
        _require(_ids_equal(item[field], asdict(expected)[field]), f"bootstrap {field} mismatch")
    identities = _bootstrap_identities(item, expected)
    backend = _bootstrap_backends(item, identities, expected)
    encryption = _object(item["encryption"], ("vault_uri", "storage_identity_id", "key_uri"), "bootstrap encryption")
    vault_uri = _text(
        encryption["vault_uri"], "bootstrap vault URI", r"https://[a-z][a-z0-9-]{1,22}[a-z0-9]\.vault\.azure\.net/"
    )
    _require(encryption["key_uri"] == f"{vault_uri}keys/bootstrap-state", "wrong bootstrap key ancestry")
    bootstrap_rg = f"/subscriptions/{expected.subscription_id}/resourceGroups/{backend.resource_group_name}"
    _require(
        _ids_equal(
            encryption["storage_identity_id"],
            f"{bootstrap_rg}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-{expected.project_code}-{expected.environment}-state-encryption",
        ),
        "wrong bootstrap encryption identity",
    )
    _require(vault_uri != expected.vault_uri, "application vault must differ from bootstrap vault")
    return BootstrapContract(identities[0], identities[1], identities[2], backend, digest(raw))


@dataclass(frozen=True)
class ApplicationContract:
    stage: Stage
    status: str
    raw_sha256: str
    payload: tuple[tuple[str, str], ...]

    def values(self) -> dict[str, str]:
        """Return a fresh projection, never a mutable reference to the contract."""
        return dict(self.payload)


def actions() -> tuple[str, ...]:
    path = Path(__file__).resolve().parents[1] / "infra/contracts/application-governance/actions.json"
    value = decode(path.read_bytes())
    _require(isinstance(value, list) and all(isinstance(action, str) for action in value), "invalid action allowlist")
    return tuple(value) if isinstance(value, list) else ()


def _namespace(expected: ExpectedContext) -> dict[str, str]:
    return {
        "namespace_id": expected.namespace_id,
        "namespace_name": expected.namespace_name,
        "location": expected.location,
        "vault_id": expected.vault_id,
        "vault_uri": expected.vault_uri,
        "foundation_role_definition_id": expected.role_definition_id,
        "foundation_principal_id": expected.foundation.principal_id,
        "actions_sha256": digest(encode(actions())),
    }


def _envelope(stage: str, expected: ExpectedContext, prior_sha256: str) -> dict[str, object]:
    producer = "governance" if stage in ("namespace", "custody", "encryption") else "foundation"
    revision = expected.governance_revision if producer == "governance" else expected.foundation_revision
    return {
        "schema": SCHEMA,
        "schema_version": 1,
        "stage": stage,
        "status": "declared-not-activated",
        "environment": expected.environment,
        "tenant_id": expected.tenant_id,
        "subscription_id": expected.subscription_id,
        "producer": producer,
        "producer_revision": revision,
        "policy_revision": expected.policy_revision,
        "bootstrap_sha256": expected.bootstrap_sha256,
        "prior_sha256": prior_sha256,
        "namespace": {"id": expected.namespace_id, "name": expected.namespace_name, "location": expected.location},
        "vault": {
            "id": expected.vault_id,
            "uri": expected.vault_uri,
            "rbac_authorization": True,
            "purge_protection_enabled": True,
            "soft_delete_retention_days": 90,
            "network_default_action": "Deny",
        },
        "foundation": asdict(expected.foundation),
        "backend": asdict(expected.backend),
        "excluded_principals": [expected.bootstrap_operator_principal_id, expected.bootstrap_encryption_principal_id],
    }


def _prerequisites(payload: object, expected: ExpectedContext, bootstrap: BootstrapContract) -> dict[str, str]:
    fields = (
        "vault_id",
        "encryption_identity_id",
        "encryption_client_id",
        "encryption_principal_id",
        "audit_workspace_id",
        "vault_diagnostic_id",
    )
    item = _object(payload, fields, "prerequisites payload")
    result = {field: _text(item[field], field) for field in fields}
    _require(_ids_equal(result["vault_id"], expected.vault_id), "foundation must echo governance vault")
    suffix = f"{expected.project_code}-{expected.environment}-application"
    _require(
        _ids_equal(
            result["encryption_identity_id"],
            f"{expected.namespace_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-{suffix}-encryption",
        ),
        "wrong encryption identity ancestry",
    )
    _require(
        _ids_equal(
            result["audit_workspace_id"],
            f"{expected.namespace_id}/providers/Microsoft.OperationalInsights/workspaces/law-{suffix}",
        ),
        "wrong audit workspace ancestry",
    )
    _require(
        _ids_equal(
            result["vault_diagnostic_id"],
            f"{expected.vault_id}/providers/Microsoft.Insights/diagnosticSettings/application-key-audit",
        ),
        "wrong vault diagnostic ancestry",
    )
    identities = (bootstrap.foundation, bootstrap.workload, bootstrap.release)
    for field, forbidden in (
        (
            "encryption_principal_id",
            {identity.principal_id for identity in identities}
            | {expected.bootstrap_operator_principal_id, expected.bootstrap_encryption_principal_id},
        ),
        ("encryption_client_id", {identity.client_id for identity in identities}),
    ):
        _text(result[field], field, UUID_PATTERN)
        _require(
            result[field].lower() not in {value.lower() for value in forbidden},
            f"{field} must differ from deployment identities",
        )
    return result


def _grant(stage: str, expected: ExpectedContext, previous: tuple[ApplicationContract, ...]) -> dict[str, str]:
    if stage == "custody":
        return {
            "scope": expected.vault_id,
            "principal_id": expected.foundation.principal_id,
            "role_definition_id": expected.role_id(CRYPTO_OFFICER),
        }
    return {
        "scope": previous[3].values()["key_id"],
        "principal_id": previous[1].values()["encryption_principal_id"],
        "role_definition_id": expected.role_id(CRYPTO_SERVICE),
    }


def _payload(
    stage: str,
    payload: object,
    expected: ExpectedContext,
    bootstrap: BootstrapContract,
    previous: tuple[ApplicationContract, ...],
) -> dict[str, str]:
    if stage == "prerequisites":
        return _prerequisites(payload, expected, bootstrap)
    if stage == "namespace":
        wanted = _namespace(expected)
    elif stage == "key":
        wanted = {
            "key_id": f"{expected.vault_id}/keys/application-cmk",
            "key_uri": f"{expected.vault_uri}keys/application-cmk",
        }
    else:
        wanted = _grant(stage, expected, previous)
    item = _object(payload, tuple(wanted), f"{stage} payload")
    _require(_ids_equal(item, wanted), f"{stage} payload does not match approved scope/principal/ancestry/role")
    return wanted


def parse_chain(
    bootstrap_raw: bytes, artifacts: tuple[bytes, ...], expected: ExpectedContext, expected_stage: Stage | None
) -> tuple[ApplicationContract, ...]:
    """Validate an unbroken raw-byte-hashed prefix ending at exactly expected_stage."""
    bootstrap = parse_bootstrap(bootstrap_raw, expected)
    _require(expected_stage is None or expected_stage in STAGES, "unsupported expected stage")
    length = 0 if expected_stage is None else STAGES.index(expected_stage) + 1
    _require(len(artifacts) == length, "missing prerequisite artifact or skipped stage")
    result: tuple[ApplicationContract, ...] = ()
    prior = expected.bootstrap_sha256
    for stage, raw in zip(STAGES, artifacts, strict=False):
        wanted = _envelope(stage, expected, prior)
        item = _object(decode(raw), (*wanted, "payload"), f"{stage} artifact")
        _require(type(item["schema_version"]) is int, "schema version must be integer")
        Backend.parse(item["backend"])
        vault = _object(
            item["vault"],
            (
                "id",
                "uri",
                "rbac_authorization",
                "purge_protection_enabled",
                "soft_delete_retention_days",
                "network_default_action",
            ),
            "vault",
        )
        _require(
            vault["rbac_authorization"] is True
            and vault["purge_protection_enabled"] is True
            and type(vault["soft_delete_retention_days"]) is int,
            "vault protections have invalid types",
        )
        _require(
            _ids_equal({key: item[key] for key in wanted}, wanted), f"{stage} envelope/context/revision/digest mismatch"
        )
        payload = _payload(stage, item["payload"], expected, bootstrap, result)
        result = (*result, ApplicationContract(stage, "declared-not-activated", digest(raw), tuple(payload.items())))
        prior = digest(raw)
    return result


def create_artifact(
    stage: Stage,
    payload: Mapping[str, str],
    bootstrap_raw: bytes,
    previous: tuple[bytes, ...],
    expected: ExpectedContext,
) -> bytes:
    """Produce and validate one immutable next-stage artifact; never assert permission readiness."""
    _require(stage in STAGES, "unsupported producer stage")
    index = STAGES.index(stage)
    prior_stage = STAGES[index - 1] if index else None
    contracts = parse_chain(bootstrap_raw, previous, expected, prior_stage)
    supplied: object = dict(payload)
    if stage == "namespace":
        _require(not payload, "namespace takes no caller-supplied resource references")
        supplied = _namespace(expected)
    elif stage in ("custody", "encryption"):
        _require(not payload, "grant references derive only from validated earlier artifacts")
        supplied = _grant(stage, expected, contracts)
    validated = _payload(stage, supplied, expected, parse_bootstrap(bootstrap_raw, expected), contracts)
    prior = digest(previous[-1]) if previous else expected.bootstrap_sha256
    raw = encode({**_envelope(stage, expected, prior), "payload": validated})
    parse_chain(bootstrap_raw, (*previous, raw), expected, stage)
    return raw


def _external(raw: bytes) -> bytes:
    query = _object(decode_external_request(raw), ("context", "bootstrap", "artifacts", "phase"), "external query")
    expected = ExpectedContext.from_bytes(_text(query["context"], "context").encode())
    bootstrap = _text(query["bootstrap"], "bootstrap").encode()
    supplied = decode_artifact_bundle(_text(query["artifacts"], "artifacts").encode())
    _require(
        isinstance(supplied, list) and all(isinstance(item, str) for item in supplied),
        "artifacts must be raw JSON strings",
    )
    previous = tuple(item.encode() for item in supplied) if isinstance(supplied, list) else ()
    phase = _text(query["phase"], "phase")
    _require(phase in ("namespace", "custody", "encryption"), "unsupported governance phase")
    artifact = create_artifact(cast(Stage, phase), {}, bootstrap, previous, expected)
    payload = json.loads(artifact)["payload"]
    return encode(
        {
            "contract": artifact.decode(),
            "scope": payload.get("scope", ""),
            "principal_id": payload.get("principal_id", ""),
            "role_definition_id": payload.get("role_definition_id", ""),
        }
    )


def read_artifact(path: Path) -> bytes:
    """Read a bounded input without allocating an arbitrarily large file."""
    with path.open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    _require(len(raw) <= MAX_BYTES, "artifact exceeds maximum byte size")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("external", "validate", "create"))
    parser.add_argument("--context", type=Path)
    parser.add_argument("--bootstrap", type=Path)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    parser.add_argument("--payload", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "external":
            result = _external(sys.stdin.buffer.read(MAX_EXTERNAL_REQUEST_BYTES + 1))
        else:
            if args.context is None or args.bootstrap is None or args.stage is None:
                raise ContractError("--context, --bootstrap and --stage are required")
            expected = ExpectedContext.from_bytes(read_artifact(args.context))
            bootstrap = read_artifact(args.bootstrap)
            previous = tuple(read_artifact(path) for path in args.artifact)
            if args.command == "validate":
                contracts = parse_chain(bootstrap, previous, expected, args.stage)
                result = encode({"stage": contracts[-1].stage, "sha256": contracts[-1].raw_sha256})
            else:
                supplied = decode(read_artifact(args.payload)) if args.payload else {}
                if not isinstance(supplied, dict):
                    raise ContractError("payload must be an object")
                payload = {key: _text(value, str(key)) for key, value in supplied.items()}
                result = create_artifact(args.stage, payload, bootstrap, previous, expected)
        sys.stdout.buffer.write(result)
        return 0
    except (ContractError, OSError) as exc:
        print(f"contract error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
