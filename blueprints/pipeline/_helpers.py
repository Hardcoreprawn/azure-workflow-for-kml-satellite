"""Pipeline helpers: re-export shim for backward compatibility.

The implementations have been moved to focused modules:
- ``_blob_url``: blob URL validation (``_expected_blob_host``, ``_is_trusted_blob_host``,
  ``_extract_container``, ``_extract_blob_name``, ``_validate_blob_event``)
- ``_status``: Durable Functions status shaping (``_durable_status_payload``,
  ``_reshape_output``)
- ``_payloads``: orchestrator activity payload builders (``_acq_payload``,
  ``_poll_payload``, ``_download_payload``, ``_post_process_payload``,
  ``_collect_enrichment_coords``, ``_collect_per_aoi_coords``,
  ``_build_order_lookups``, ``_split_batch_routing``)
- ``_aggregation``: per-AOI result aggregation (``_aggregate_aoi_results``)

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

from ._aggregation import _aggregate_aoi_results
from ._blob_url import (
    _expected_blob_host,
    _extract_blob_name,
    _extract_container,
    _is_trusted_blob_host,
    _validate_blob_event,
)
from ._payloads import (
    _acq_payload,
    _build_order_lookups,
    _collect_enrichment_coords,
    _collect_per_aoi_coords,
    _download_payload,
    _poll_payload,
    _post_process_payload,
    _split_batch_routing,
)
from ._status import _durable_status_payload, _reshape_output

__all__ = [
    "_acq_payload",
    "_aggregate_aoi_results",
    "_build_order_lookups",
    "_collect_enrichment_coords",
    "_collect_per_aoi_coords",
    "_download_payload",
    "_durable_status_payload",
    "_expected_blob_host",
    "_extract_blob_name",
    "_extract_container",
    "_is_trusted_blob_host",
    "_poll_payload",
    "_post_process_payload",
    "_reshape_output",
    "_split_batch_routing",
    "_validate_blob_event",
]
