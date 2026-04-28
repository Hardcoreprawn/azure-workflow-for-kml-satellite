"""Run an authenticated end-to-end smoke flow against a deployed API.

Flow:
1) POST /api/upload/token
2) PUT uploaded KML to returned SAS URL
3) Poll GET /api/orchestrator/{instance_id} until terminal state
4) Verify completed output matches the diagnostics payload shape
5) Optionally verify GET /api/timelapse-data/{instance_id}
"""

from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx

TERMINAL_STATUSES = {"Completed", "Failed", "Canceled", "Terminated"}


def bearer_headers(token: str) -> dict[str, str]:
    token_value = token.strip()
    if not token_value:
        raise ValueError("Bearer token is required")
    return {"Authorization": f"Bearer {token_value}"}


def principal_headers(principal_header: str, session_token: str | None = None) -> dict[str, str]:
    header_value = principal_header.strip()
    if not header_value:
        raise ValueError("X-MS-CLIENT-PRINCIPAL header is required")
    headers = {"X-MS-CLIENT-PRINCIPAL": header_value}
    if session_token and session_token.strip():
        headers["X-Auth-Session"] = session_token.strip()
    return headers


def auth_headers(
    *,
    token: str | None,
    principal_header: str | None,
    session_token: str | None,
) -> dict[str, str]:
    if token and token.strip():
        return bearer_headers(token)
    if principal_header and principal_header.strip():
        return principal_headers(principal_header, session_token=session_token)
    raise ValueError("Either bearer token or client principal header must be provided")


def build_client_principal_header(
    *,
    user_id: str,
    user_details: str,
    roles_csv: str,
) -> str:
    roles = [role.strip() for role in roles_csv.split(",") if role.strip()]
    if not roles:
        raise ValueError("At least one principal role is required")

    payload = {
        "auth_typ": "aad",
        "name_typ": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
        "role_typ": "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
        "claims": [],
        "identityProvider": "aad",
        "userId": user_id,
        "userDetails": user_details,
        "userRoles": roles,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def mint_session_token(
    client: httpx.Client,
    *,
    api_base: str,
    principal_header: str,
) -> str | None:
    response = client.post(
        f"{api_base}/api/auth/session",
        headers={
            "X-MS-CLIENT-PRINCIPAL": principal_header,
            "Content-Type": "application/json",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("hmac_enabled", False):
        return None
    token = payload.get("token")
    if not isinstance(token, str) or not token:
        raise ValueError("auth/session response missing token while hmac_enabled=true")
    return token


def mint_upload_token(
    client: httpx.Client,
    *,
    api_base: str,
    token: str | None = None,
    principal_header: str | None = None,
    session_token: str | None = None,
    eudr_mode: bool,
    submission_context: dict[str, Any],
) -> dict[str, str]:
    payload = {
        "eudr_mode": eudr_mode,
        "submission_context": submission_context,
    }
    response = client.post(
        f"{api_base}/api/upload/token",
        json=payload,
        headers={
            **auth_headers(
                token=token,
                principal_header=principal_header,
                session_token=session_token,
            ),
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    submission_id = data.get("submissionId")
    sas_url = data.get("sasUrl")
    if not isinstance(submission_id, str) or not submission_id:
        raise ValueError("upload/token response missing submissionId")
    if not isinstance(sas_url, str) or not sas_url:
        raise ValueError("upload/token response missing sasUrl")
    return {"submissionId": submission_id, "sasUrl": sas_url}


def upload_kml(client: httpx.Client, *, sas_url: str, kml_bytes: bytes) -> None:
    response = client.put(
        sas_url,
        content=kml_bytes,
        headers={
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": "application/vnd.google-earth.kml+xml",
        },
        timeout=60.0,
    )
    response.raise_for_status()


def poll_orchestrator(
    client: httpx.Client,
    *,
    api_base: str,
    token: str | None = None,
    principal_header: str | None = None,
    session_token: str | None = None,
    instance_id: str,
    max_attempts: int,
    poll_interval_seconds: int,
) -> dict[str, Any]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    last_payload: dict[str, Any] | None = None
    for _ in range(max_attempts):
        response = client.get(
            f"{api_base}/api/orchestrator/{instance_id}",
            headers=auth_headers(
                token=token,
                principal_header=principal_header,
                session_token=session_token,
            ),
            timeout=20.0,
        )
        if response.status_code == 404:
            time.sleep(poll_interval_seconds)
            continue
        response.raise_for_status()
        payload = response.json()
        last_payload = payload
        runtime_status = payload.get("runtimeStatus")
        if runtime_status in TERMINAL_STATUSES:
            return payload
        time.sleep(poll_interval_seconds)

    raise TimeoutError(
        f"orchestrator did not reach terminal state within {max_attempts} attempts"
        f"; last payload={last_payload}"
    )


def verify_completed_output_shape(status_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_status = status_payload.get("runtimeStatus")
    if runtime_status != "Completed":
        raise ValueError(f"orchestrator finished in non-success state: {runtime_status}")

    output = status_payload.get("output")
    if not isinstance(output, dict):
        raise ValueError("orchestrator output payload missing")

    required_types: dict[str, type[Any]] = {
        "status": str,
        "message": str,
        "blobName": str,
        "featureCount": int,
        "aoiCount": int,
        "artifacts": dict,
    }
    for field, expected_type in required_types.items():
        if not isinstance(output.get(field), expected_type):
            raise ValueError(f"orchestrator output field '{field}' has invalid type")

    return output


def collect_artifact_paths(output: dict[str, Any]) -> list[str]:
    artifacts = output.get("artifacts")
    if not isinstance(artifacts, dict):
        return []

    paths: list[str] = []
    for value in artifacts.values():
        if isinstance(value, str) and value.strip():
            paths.append(value)
            continue
        if isinstance(value, list):
            paths.extend(item.strip() for item in value if isinstance(item, str) and item.strip())
    return paths


def verify_manifest(
    client: httpx.Client,
    *,
    api_base: str,
    token: str | None = None,
    principal_header: str | None = None,
    session_token: str | None = None,
    instance_id: str,
) -> dict[str, Any]:
    response = client.get(
        f"{api_base}/api/timelapse-data/{instance_id}",
        headers=auth_headers(
            token=token,
            principal_header=principal_header,
            session_token=session_token,
        ),
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("timelapse-data response must be a JSON object")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base", required=True, help="Base API URL, e.g. https://api.example.com"
    )
    parser.add_argument("--bearer-token", help="Optional CIAM bearer token")
    parser.add_argument(
        "--principal-user-id",
        default="deploy-smoke-user",
        help="Synthetic SWA principal userId when bearer token is not provided",
    )
    parser.add_argument(
        "--principal-user-details",
        default="deploy-smoke@example.com",
        help="Synthetic SWA principal userDetails when bearer token is not provided",
    )
    parser.add_argument(
        "--principal-roles",
        default="authenticated",
        help="Comma-separated principal roles for smoke auth header",
    )
    parser.add_argument(
        "--skip-session-token",
        action="store_true",
        help="Skip auth/session token bootstrap in principal auth mode",
    )
    parser.add_argument(
        "--kml-path", default="tests/fixtures/sample.kml", help="Path to KML fixture"
    )
    parser.add_argument(
        "--poll-interval", type=int, default=5, help="Seconds between orchestrator polls"
    )
    parser.add_argument("--max-attempts", type=int, default=120, help="Max poll attempts")
    parser.add_argument(
        "--eudr-mode", action="store_true", help="Set eudr_mode=true in upload/token"
    )
    parser.add_argument(
        "--skip-manifest-check",
        action="store_true",
        help="Skip /api/timelapse-data verification",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    kml_path = Path(args.kml_path)
    if not kml_path.exists():
        raise FileNotFoundError(f"KML path not found: {kml_path}")

    kml_bytes = kml_path.read_bytes()
    if not kml_bytes:
        raise ValueError("KML file is empty")

    submission_context = {
        "provider_name": "planetary_computer",
        "source": "deploy_smoke",
    }

    with httpx.Client() as client:
        bearer_token = (args.bearer_token or "").strip() or None
        principal_header = None
        session_token = None
        if not bearer_token:
            principal_header = build_client_principal_header(
                user_id=args.principal_user_id,
                user_details=args.principal_user_details,
                roles_csv=args.principal_roles,
            )
            if not args.skip_session_token:
                session_token = mint_session_token(
                    client,
                    api_base=args.api_base.rstrip("/"),
                    principal_header=principal_header,
                )

        token_result = mint_upload_token(
            client,
            api_base=args.api_base.rstrip("/"),
            token=bearer_token,
            principal_header=principal_header,
            session_token=session_token,
            eudr_mode=args.eudr_mode,
            submission_context=submission_context,
        )
        submission_id = token_result["submissionId"]
        sas_url = token_result["sasUrl"]

        upload_kml(client, sas_url=sas_url, kml_bytes=kml_bytes)

        status_payload = poll_orchestrator(
            client,
            api_base=args.api_base.rstrip("/"),
            token=bearer_token,
            principal_header=principal_header,
            session_token=session_token,
            instance_id=submission_id,
            max_attempts=args.max_attempts,
            poll_interval_seconds=args.poll_interval,
        )
        output_payload = verify_completed_output_shape(status_payload)
        artifact_paths = collect_artifact_paths(output_payload)

        manifest_ok = False
        if not args.skip_manifest_check:
            verify_manifest(
                client,
                api_base=args.api_base.rstrip("/"),
                token=bearer_token,
                principal_header=principal_header,
                session_token=session_token,
                instance_id=submission_id,
            )
            manifest_ok = True

    print(
        json.dumps(
            {
                "submissionId": submission_id,
                "runtimeStatus": status_payload.get("runtimeStatus"),
                "outputStatus": output_payload.get("status"),
                "artifactCount": len(artifact_paths),
                "manifestVerified": manifest_ok,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
