#!/usr/bin/env python
"""Verify E2E test input and output blobs in Azure Storage."""

import asyncio
import importlib
import logging
import sys
from datetime import UTC, datetime

from azure.core.exceptions import ClientAuthenticationError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient

_cfg_module = importlib.import_module("scripts.e2e_config" if __package__ else "e2e_config")
LIST_TIMEOUT_SECONDS = _cfg_module.LIST_TIMEOUT_SECONDS
get_container_names = _cfg_module.get_container_names
get_storage_account_url = _cfg_module.get_storage_account_url

logger = logging.getLogger(__name__)


async def _list_blobs(container_client, prefix: str) -> list[tuple[str, int | None, str]]:
    blobs: list[tuple[str, int | None, str]] = []
    async for blob in container_client.list_blobs(name_starts_with=prefix):
        created = blob.creation_time.isoformat() if blob.creation_time else ""
        blobs.append((blob.name, blob.size, created))
    return blobs


def _default_prefix() -> str:
    return f"e2e-sherwood-{datetime.now(UTC).strftime('%Y%m%d')}"


async def check_blobs(prefix: str = _default_prefix()) -> int:
    """Check input and output containers for blobs with the provided prefix."""
    account_url = get_storage_account_url()
    input_container_name, output_container_name = get_container_names()

    try:
        async with (
            DefaultAzureCredential() as credential,
            BlobServiceClient(account_url=account_url, credential=credential) as client,
        ):
            logger.info("=" * 60)
            logger.info("INPUT BLOBS (%s)", input_container_name)
            logger.info("=" * 60)

            try:
                input_container = client.get_container_client(input_container_name)
                input_blobs = await asyncio.wait_for(
                    _list_blobs(input_container, prefix), timeout=LIST_TIMEOUT_SECONDS
                )
            except ClientAuthenticationError as e:
                logger.error("x Authentication failed: %s", e)
                return 1
            except TimeoutError:
                logger.error("x Timed out listing input blobs")
                return 1
            except Exception as e:
                logger.error("x Error listing input blobs: %s", e)
                return 1

            if input_blobs:
                for name, size, created in input_blobs:
                    logger.info("  + %s (%s bytes, created %s)", name, size, created)
            else:
                logger.error("  x No %s blobs found in input container", prefix)

            logger.info("\n%s", "=" * 60)
            logger.info("OUTPUT BLOBS (%s)", output_container_name)
            logger.info("=" * 60)

            try:
                output_container = client.get_container_client(output_container_name)
                output_blobs = await asyncio.wait_for(
                    _list_blobs(output_container, prefix), timeout=LIST_TIMEOUT_SECONDS
                )
            except ClientAuthenticationError as e:
                logger.error("x Authentication failed: %s", e)
                return 1
            except TimeoutError:
                logger.error("x Timed out listing output blobs")
                return 1
            except Exception as e:
                logger.error("x Error listing output blobs: %s", e)
                return 1

            if output_blobs:
                sorted_blobs = sorted(output_blobs, key=lambda item: item[2], reverse=True)
                for name, size, _created in sorted_blobs:
                    ext = name.split(".")[-1].upper()
                    kind = "(TIF)" if ext == "TIF" else "(JSON)" if ext == "JSON" else f"({ext})"
                    logger.info("  + %s (%s bytes) %s", name, f"{size:,}", kind)
                return 0

            logger.error("  x No output blobs found for prefix %s", prefix)
            logger.info("  i Orchestration may still be running or failed")
            return 1
    except Exception as e:
        logger.exception("x Unexpected error: %s", e)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(asyncio.run(check_blobs()))
