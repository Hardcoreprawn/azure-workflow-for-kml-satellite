"""Run an authenticated end-to-end smoke flow against a deployed API.

Flow:
1) Acquire a bearer token — either provided directly via ``--bearer-token``
   or obtained from a CIAM OIDC endpoint via OAuth2 client credentials flow
   (``--client-id``, ``--client-secret``, ``--token-endpoint``, ``--api-scope``).
2) POST /api/upload/token
3) PUT uploaded KML to returned SAS URL
4) Poll GET /api/orchestrator/{instance_id} until terminal state
5) Verify completed output matches the diagnostics payload shape
6) Optionally verify GET /api/timelapse-data/{instance_id}
7) Write evidence JSON to ``--evidence-file`` (if specified).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx
import requests as _requests

TERMINAL_STATUSES = {"Completed", "Failed", "Canceled", "Terminated"}


def acquire_token_client_credentials(
    *,
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    scope: str,
) -> str:
    """Obtain an access token via OAuth2 client credentials flow.

    Uses a direct POST to the OIDC token endpoint — no external libraries
    required beyond ``requests`` which is already a project dependency.

    Args:
        token_endpoint: Full token endpoint URL, e.g.
            ``https://{tenant}.ciamlogin.com/{tenant}.onmicrosoft.com/oauth2/v2.0/token``
        client_id: OAuth2 client (application) ID.
        client_secret: OAuth2 client secret.
        scope: Space-separated OAuth2 scopes, e.g. ``api://{id}/.default``.

    Returns:
        The access_token string.

    Raises:
        ValueError: If the endpoint returns an error or no access_token.
        requests.HTTPError: On non-2xx HTTP status.
    """
    if not token_endpoint.startswith("https://"):
        raise ValueError("token_endpoint must use HTTPS")

    resp = _requests.post(
        token_endpoint,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        },
        timeout=15,
        allow_redirects=False,
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        error = payload.get("error", "unknown")
        description = payload.get("error_description", "no description")
        raise ValueError(f"Token endpoint did not return access_token: {error} — {description}")
    return token


def bearer_headers(token: str) -> dict[str, str]:
    token_value = token.strip()
    if not token_value:
        raise ValueError("Bearer token is required")
    return {"Authorization": f"Bearer {token_value}"}


def mint_upload_token(
    client: httpx.Client,
    *,
    api_base: str,
    token: str,
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
            **bearer_headers(token),
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
    token: str,
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
            headers=bearer_headers(token),
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
    token: str,
    instance_id: str,
) -> dict[str, Any]:
    response = client.get(
        f"{api_base}/api/timelapse-data/{instance_id}",
        headers=bearer_headers(token),
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
    auth_group = parser.add_mutually_exclusive_group(required=False)
    auth_group.add_argument(
        "--bearer-token",
        default="",
        help="CIAM bearer token.",
    )
    auth_group.add_argument(
        "--client-credentials-flow",
        action="store_true",
        help="Use OAuth2 client credentials flow instead of --bearer-token.",
    )
    parser.add_argument(
        "--client-id",
        default="",
        help="OAuth2 client ID for client credentials token acquisition.",
    )
    parser.add_argument(
        "--client-secret",
        default="",
        help="OAuth2 client secret for client credentials token acquisition.",
    )
    parser.add_argument(
        "--token-endpoint",
        default="",
        help=(
            "Full OIDC token endpoint URL for client credentials flow, e.g. "
            "https://{tenant}.ciamlogin.com/{tenant}.onmicrosoft.com/oauth2/v2.0/token"
        ),
    )
    parser.add_argument(
        "--api-scope",
        default="",
        help="OAuth2 scope string for client credentials flow, e.g. api://{id}/.default",
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
    parser.add_argument(
        "--evidence-file",
        default="",
        help="Path to write the JSON evidence artifact. If omitted, evidence is only printed.",
    )
    parser.add_argument(
        "--image-tag",
        default="",
        help="Docker image tag of the deployed version (included in evidence).",
    )
    parser.add_argument(
        "--commit-sha",
        default="",
        help="Git commit SHA of the deployed version (included in evidence).",
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
        bearer_token = args.bearer_token.strip()
        if args.client_credentials_flow:
            # Attempt client credentials flow
            client_id = args.client_id.strip()
            client_secret = args.client_secret.strip()
            token_endpoint = args.token_endpoint.strip()
            api_scope = args.api_scope.strip()
            if not (client_id and client_secret and token_endpoint and api_scope):
                raise ValueError(
                    "All of --client-id, --client-secret, --token-endpoint, --api-scope"
                    " must be provided when using --client-credentials-flow"
                )
            bearer_token = acquire_token_client_credentials(
                token_endpoint=token_endpoint,
                client_id=client_id,
                client_secret=client_secret,
                scope=api_scope,
            )
        elif not bearer_token:
            raise ValueError("Either --bearer-token or --client-credentials-flow must be provided")

        token_result = mint_upload_token(
            client,
            api_base=args.api_base.rstrip("/"),
            token=bearer_token,
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
                instance_id=submission_id,
            )
            manifest_ok = True

    evidence: dict[str, Any] = {
        "submissionId": submission_id,
        "runtimeStatus": status_payload.get("runtimeStatus"),
        "outputStatus": output_payload.get("status"),
        "artifactCount": len(artifact_paths),
        "manifestVerified": manifest_ok,
    }
    if args.image_tag:
        evidence["imageTag"] = args.image_tag
    if args.commit_sha:
        evidence["commitSha"] = args.commit_sha

    evidence_json = json.dumps(evidence, sort_keys=True)
    print(evidence_json)

    if args.evidence_file:
        evidence_path = Path(args.evidence_file)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(evidence_json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
