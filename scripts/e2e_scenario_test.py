#!/usr/bin/env python
"""E2E scenario: Upload KML → Trigger orchestration → Verify TIF output."""

import asyncio
import logging
import sys
from datetime import UTC, datetime

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient
from e2e_config import (
    LIST_TIMEOUT_SECONDS,
    MAX_POLL_ATTEMPTS,
    POLL_INTERVAL_SECONDS,
    TOTAL_TEST_TIMEOUT_SECONDS,
    UPLOAD_TIMEOUT_SECONDS,
    get_container_names,
    get_storage_account_url,
)

logger = logging.getLogger(__name__)

# Test KML (Sherwood Forest area)
TEST_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>E2E Test: Sherwood Forest</name>
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
  </Document>
</kml>
"""

STORAGE_ACCOUNT = get_storage_account_url()
INPUT_CONTAINER, OUTPUT_CONTAINER = get_container_names()


async def main() -> int:
    """Run E2E test: KML upload → orchestration → TIF verification."""
    try:
        async with (
            DefaultAzureCredential() as credential,
            BlobServiceClient(account_url=STORAGE_ACCOUNT, credential=credential) as client,
        ):
            run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            kml_name = f"e2e-test-{run_id}.kml"
            expected_prefix = f"e2e-test-{run_id}"

            # Step 1: Upload KML
            logger.info("=" * 70)
            logger.info("STEP 1: Upload test KML")
            logger.info("=" * 70)
            logger.info("File: %s (%s bytes)", kml_name, len(TEST_KML))

            try:
                input_container = client.get_container_client(INPUT_CONTAINER)
                blob = input_container.get_blob_client(kml_name)
                await asyncio.wait_for(
                    blob.upload_blob(TEST_KML, overwrite=True),
                    timeout=UPLOAD_TIMEOUT_SECONDS,
                )
                logger.info("✓ %s/%s", INPUT_CONTAINER, kml_name)
            except TimeoutError:
                logger.error("✗ Upload timeout after %ss", UPLOAD_TIMEOUT_SECONDS)
                return 1
            except Exception as e:
                logger.error("✗ Upload failed: %s: %s", type(e).__name__, e)
                return 1

            # Step 2: Poll for outputs
            logger.info("\n%s", "=" * 70)
            logger.info("STEP 2: Poll for orchestration outputs")
            logger.info("=" * 70)
            logger.info("Prefix: %s", expected_prefix)

            output_container = client.get_container_client(OUTPUT_CONTAINER)
            found_outputs = []

            for poll_num in range(MAX_POLL_ATTEMPTS):
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

                try:

                    async def list_blobs():
                        blobs = []
                        async for blob in output_container.list_blobs(
                            name_starts_with=expected_prefix
                        ):
                            blobs.append((blob.name, blob.size))
                        return blobs

                    blobs = await asyncio.wait_for(list_blobs(), timeout=LIST_TIMEOUT_SECONDS)
                except Exception:
                    if (poll_num + 1) % 10 == 0:
                        logger.info(
                            "  ... still waiting (%ss)",
                            (poll_num + 1) * POLL_INTERVAL_SECONDS,
                        )
                    continue

                if blobs:
                    found_outputs = blobs
                    elapsed = (poll_num + 1) * POLL_INTERVAL_SECONDS
                    logger.info("✓ Found outputs after %ss:", elapsed)
                    for name, size in blobs:
                        logger.info("  %s (%s bytes)", name, f"{size:,}")
                    break
                elif (poll_num + 1) % 10 == 0:
                    logger.info(
                        "  ... waiting (%ss)",
                        (poll_num + 1) * POLL_INTERVAL_SECONDS,
                    )

            if not found_outputs:
                logger.error(
                    "✗ No outputs after %ss",
                    MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS,
                )
                return 1

            # Step 3: Validate TIF
            logger.info("\n%s", "=" * 70)
            logger.info("STEP 3: Validate output")
            logger.info("=" * 70)

            has_tif = any(n.lower().endswith(".tif") for n, _ in found_outputs)
            has_json = any(n.lower().endswith(".json") for n, _ in found_outputs)

            logger.info("TIF:      %s", "✓" if has_tif else "✗")
            logger.info("Metadata: %s", "✓" if has_json else "✗")

            if not has_tif:
                logger.error("✗ No TIF output")
                return 1

            # Get TIF properties
            tif_name = next(n for n, _ in found_outputs if n.lower().endswith(".tif"))
            tif_blob = output_container.get_blob_client(tif_name)

            try:
                props = await asyncio.wait_for(
                    tif_blob.get_blob_properties(), timeout=LIST_TIMEOUT_SECONDS
                )
                logger.info("\nTIF Details:")
                logger.info("  Name: %s", tif_name)
                logger.info("  Size: %s bytes", f"{props.size:,}")
            except Exception:
                logger.info("\nTIF: %s", tif_name)

            # Success
            logger.info("\n%s", "=" * 70)
            logger.info("✓ E2E SCENARIO COMPLETE")
            logger.info("=" * 70)
            logger.info("Input:  %s/%s", INPUT_CONTAINER, kml_name)
            logger.info("Output: %s/%s", OUTPUT_CONTAINER, tif_name)

            return 0

    except Exception as e:
        logger.error("✗ Error: %s: %s", type(e).__name__, e)
        return 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        result = asyncio.run(asyncio.wait_for(main(), timeout=TOTAL_TEST_TIMEOUT_SECONDS))
        sys.exit(result)
    except TimeoutError:
        logger.error("✗ Test timeout (%ss)", TOTAL_TEST_TIMEOUT_SECONDS)
        sys.exit(1)
