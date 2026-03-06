#!/usr/bin/env python
"""Test Azure blob upload directly."""

import asyncio
import logging
import sys
from datetime import UTC, datetime

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient
from e2e_config import (
    UPLOAD_TIMEOUT_SECONDS,
    get_container_names,
    get_storage_account_url,
)

logger = logging.getLogger(__name__)

TEST_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>E2E Test</name>
    <Folder>
      <name>Features</name>
      <Placemark>
        <name>Test Polygon</name>
        <Polygon>
          <outerBoundaryIs>
            <LinearRing>
              <coordinates>
                -1.2,53.2,0 -1.0,53.2,0 -1.0,53.0,0 -1.2,53.0,0 -1.2,53.2,0
              </coordinates>
            </LinearRing>
          </outerBoundaryIs>
        </Polygon>
      </Placemark>
    </Folder>
  </Document>
</kml>
"""


async def test_upload() -> int:
    """Upload test KML to blob storage."""
    logger.info("Testing Azure Blob upload...")
    logger.info("KML size: %s bytes\n", len(TEST_KML))

    account_url = get_storage_account_url()
    input_container_name, _ = get_container_names()
    logger.info("Using account: %s\n", account_url)

    try:
        async with DefaultAzureCredential() as cred:
            logger.info("✓ DefaultAzureCredential initialized")

            async with BlobServiceClient(account_url=account_url, credential=cred) as client:
                logger.info("✓ BlobServiceClient created")

                run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
                kml_name = f"test-{run_id}.kml"

                input_container = client.get_container_client(input_container_name)
                logger.info("✓ Container client created")

                blob = input_container.get_blob_client(kml_name)
                logger.info("✓ Blob client created for: %s\n", kml_name)
                logger.info("Uploading...")

                try:
                    await asyncio.wait_for(
                        blob.upload_blob(TEST_KML, overwrite=True),
                        timeout=UPLOAD_TIMEOUT_SECONDS,
                    )
                    logger.info(
                        "✓ Upload successful: %s/%s",
                        input_container_name,
                        kml_name,
                    )
                    return 0
                except TimeoutError:
                    logger.error("✗ TIMEOUT")
                    logger.error(
                        "✗ Upload took longer than %s seconds",
                        UPLOAD_TIMEOUT_SECONDS,
                    )
                    return 1
    except Exception as e:
        logger.exception("✗ Error: %s: %s", type(e).__name__, e)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(asyncio.run(test_upload()))
