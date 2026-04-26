"""Run an authenticated end-to-end smoke flow against a deployed API.

Flow:
1) POST /api/upload/token
2) PUT uploaded KML to returned SAS URL
3) Poll GET /api/orchestrator/{instance_id} until terminal state
4) Verify completed output includes at least one artifact path
5) Optionally verify GET /api/timelapse-data/{instance_id}
"""

from __future__ import annotations

import argparse
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
        headers={**bearer_headers(token), "Content-Type": "application/json"},
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


def verify_output_artifacts(status_payload: dict[str, Any]) -> list[str]:
    runtime_status = status_payload.get("runtimeStatus")
    if runtime_status != "Completed":
        raise ValueError(f"orchestrator finished in non-success state: {runtime_status}")

    output = status_payload.get("output")
    if not isinstance(output, dict):
        raise ValueError("orchestrator output payload missing")

    artifacts = output.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("orchestrator output has no artifacts")

    paths = [value for value in artifacts.values() if isinstance(value, str) and value.strip()]
    if not paths:
        raise ValueError("artifact map has no non-empty artifact paths")
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
    parser.add_argument("--bearer-token", required=True, help="CIAM bearer token")
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
        token_result = mint_upload_token(
            client,
            api_base=args.api_base.rstrip("/"),
            token=args.bearer_token,
            eudr_mode=args.eudr_mode,
            submission_context=submission_context,
        )
        submission_id = token_result["submissionId"]
        sas_url = token_result["sasUrl"]

        upload_kml(client, sas_url=sas_url, kml_bytes=kml_bytes)

        status_payload = poll_orchestrator(
            client,
            api_base=args.api_base.rstrip("/"),
            token=args.bearer_token,
            instance_id=submission_id,
            max_attempts=args.max_attempts,
            poll_interval_seconds=args.poll_interval,
        )
        artifact_paths = verify_output_artifacts(status_payload)

        manifest_ok = False
        if not args.skip_manifest_check:
            verify_manifest(
                client,
                api_base=args.api_base.rstrip("/"),
                token=args.bearer_token,
                instance_id=submission_id,
            )
            manifest_ok = True

    print(
        json.dumps(
            {
                "submissionId": submission_id,
                "runtimeStatus": status_payload.get("runtimeStatus"),
                "artifactCount": len(artifact_paths),
                "manifestVerified": manifest_ok,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
