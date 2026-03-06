#!/usr/bin/env python
"""Direct check of E2E blobs using SDK."""

import asyncio
import importlib
import logging
import sys

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient

_cfg_module = importlib.import_module("scripts.e2e_config" if __package__ else "e2e_config")
LIST_TIMEOUT_SECONDS = _cfg_module.LIST_TIMEOUT_SECONDS
get_container_names = _cfg_module.get_container_names
get_storage_account_url = _cfg_module.get_storage_account_url

logger = logging.getLogger(__name__)


async def _collect_blob_summaries(container_client, prefix: str) -> list[tuple[str, int | None]]:
    items: list[tuple[str, int | None]] = []
    async for blob in container_client.list_blobs(name_starts_with=prefix):
        items.append((blob.name, blob.size))
    return items


async def main(prefix: str = "e2e-sherwood") -> int:
    """Check input/output containers for expected E2E blobs."""
    account_url = get_storage_account_url()
    input_container_name, output_container_name = get_container_names()

    try:
        async with (
            DefaultAzureCredential() as credential,
            BlobServiceClient(
                account_url=account_url,
                credential=credential,
            ) as client,
        ):
            logger.info("=" * 60)
            logger.info("Checking INPUT container (%s)", input_container_name)
            logger.info("=" * 60)

            input_container = client.get_container_client(input_container_name)
            inputs = await asyncio.wait_for(
                _collect_blob_summaries(input_container, prefix),
                timeout=LIST_TIMEOUT_SECONDS,
            )

            for name, size in inputs:
                logger.info("+ Found: %s (%s bytes)", name, f"{size:,}")

            if not inputs:
                logger.error("x No %s blobs in input container", prefix)

            logger.info("\n%s", "=" * 60)
            logger.info("Checking OUTPUT container (%s)", output_container_name)
            logger.info("=" * 60)

            output_container = client.get_container_client(output_container_name)
            outputs = await asyncio.wait_for(
                _collect_blob_summaries(output_container, prefix),
                timeout=LIST_TIMEOUT_SECONDS,
            )

            for name, size in outputs:
                file_type = name.split(".")[-1].upper()
                logger.info(
                    "+ Found: %s (%s bytes, %s)",
                    name,
                    f"{size:,}",
                    file_type,
                )

            if outputs:
                logger.info("\n+ SUCCESS: Found %s output artifacts", len(outputs))
                return 0

            logger.error("\nx PENDING: No output blobs found yet")
            logger.info("  Orchestration may still be running...")
            return 1
    except TimeoutError:
        logger.error("x Timed out while listing blobs")
        return 2
    except Exception as e:
        logger.exception("x Error: %s: %s", type(e).__name__, e)
        return 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(asyncio.run(main()))
