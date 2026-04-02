"""Azure Batch Spot VM fallback for oversized AOI processing (#315).

When an AOI exceeds ``BATCH_FALLBACK_AREA_HA`` the orchestrator routes
its download + post-process work to an Azure Batch pool instead of
running it on the Functions Consumption plan.  This avoids OOM kills on
lightweight serverless nodes.

Design
------
- **Pool management** is out-of-scope (handled by IaC / manual config).
- Jobs are submitted per-AOI; each job has one task that executes the
  same fulfilment logic but on a Spot VM with more memory.
- The orchestrator polls for completion via a lightweight activity.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from treesight.constants import BATCH_FALLBACK_AREA_HA

logger = logging.getLogger(__name__)


def needs_batch_fallback(area_ha: float, *, threshold: float = BATCH_FALLBACK_AREA_HA) -> bool:
    """Return True if the AOI is large enough to require Azure Batch."""
    return area_ha >= threshold


def _get_batch_config() -> dict[str, str]:
    """Read Azure Batch connection settings from environment."""
    return {
        "account_name": os.environ.get("BATCH_ACCOUNT_NAME", ""),
        "account_key": os.environ.get("BATCH_ACCOUNT_KEY", ""),
        "account_url": os.environ.get("BATCH_ACCOUNT_URL", ""),
        "pool_id": os.environ.get("BATCH_POOL_ID", "treesight-spot-pool"),
    }


def submit_batch_job(
    aoi_ref: str,
    claim_key: str,
    asset_url: str,
    output_container: str,
    project_name: str,
    timestamp: str,
) -> dict[str, Any]:
    """Submit a fulfilment job to Azure Batch.

    Returns a lightweight tracking dict suitable for passing through
    the Durable Functions orchestrator:
    ``{"job_id": ..., "task_id": ..., "aoi_ref": ..., "state": "submitted"}``.

    Raises ``RuntimeError`` if the Batch SDK is not installed or
    required environment variables are missing.
    """
    try:
        from azure.batch import BatchServiceClient  # type: ignore[import-untyped]
        from azure.batch.batch_auth import SharedKeyCredentials  # type: ignore[import-untyped]
        from azure.batch.models import (  # type: ignore[import-untyped]
            JobAddParameter,
            PoolInformation,
            TaskAddParameter,
        )
    except ImportError as exc:
        raise RuntimeError(
            "azure-batch SDK not installed.  Install it with: pip install azure-batch"
        ) from exc

    cfg = _get_batch_config()
    if not cfg["account_url"] or not cfg["account_name"]:
        raise RuntimeError(
            "BATCH_ACCOUNT_URL and BATCH_ACCOUNT_NAME must be set for Azure Batch fallback."
        )

    credentials = SharedKeyCredentials(cfg["account_name"], cfg["account_key"])
    client = BatchServiceClient(credentials, batch_url=cfg["account_url"])

    job_id = f"ts-{aoi_ref[:32]}-{timestamp[:10]}"
    task_id = f"fulfilment-{claim_key[:16]}"

    # Command: invoke the same fulfilment logic as a standalone script.
    # The Batch node has the application package pre-installed.
    command_line = (
        f"python -m treesight.pipeline.fulfilment "
        f"--claim-key {claim_key} "
        f"--asset-url {asset_url} "
        f"--output-container {output_container} "
        f"--project {project_name} "
        f"--timestamp {timestamp}"
    )

    job = JobAddParameter(
        id=job_id,
        pool_info=PoolInformation(pool_id=cfg["pool_id"]),
    )

    try:
        client.job.add(job)
    except Exception:
        # Job may already exist from a retry — that's OK
        logger.info("Batch job %s may already exist, continuing.", job_id)

    task = TaskAddParameter(id=task_id, command_line=command_line)
    client.task.add(job_id, task)

    logger.info("Submitted Batch task %s/%s for AOI %s", job_id, task_id, aoi_ref)

    return {
        "job_id": job_id,
        "task_id": task_id,
        "aoi_ref": aoi_ref,
        "claim_key": claim_key,
        "state": "submitted",
    }


def poll_batch_task(job_id: str, task_id: str) -> dict[str, Any]:
    """Check the status of a Batch task.

    Returns ``{"state": "completed" | "active" | "failed", ...}``.
    """
    try:
        from azure.batch import BatchServiceClient  # type: ignore[import-untyped]
        from azure.batch.batch_auth import SharedKeyCredentials  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("azure-batch SDK not installed.") from exc

    cfg = _get_batch_config()
    credentials = SharedKeyCredentials(cfg["account_name"], cfg["account_key"])
    client = BatchServiceClient(credentials, batch_url=cfg["account_url"])

    task = client.task.get(job_id, task_id)
    state = str(task.state).lower()

    result: dict[str, Any] = {
        "job_id": job_id,
        "task_id": task_id,
        "state": state,
    }

    if state == "completed":
        exec_info = task.execution_info
        if exec_info and exec_info.exit_code != 0:
            result["state"] = "failed"
            result["exit_code"] = exec_info.exit_code

    return result
