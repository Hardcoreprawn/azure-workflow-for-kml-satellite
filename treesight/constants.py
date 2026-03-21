"""Pipeline-wide constants (Appendix A of SYSTEM_SPEC).

Coordinate convention
---------------------
All coordinate pairs in this project are **[longitude, latitude]** (x, y),
consistent with GeoJSON (RFC 7946), KML, STAC, and GDAL/Fiona.  This is the
opposite of the colloquial "lat/lon" order used by Google Maps and everyday
speech.  Every function, model, test fixture, and data contract must follow
this convention.
"""

# --- Size limits ---
MAX_KML_FILE_SIZE_BYTES = 10_485_760  # 10 MiB
PAYLOAD_OFFLOAD_THRESHOLD_BYTES = 49_152  # 48 KiB

# --- Imagery defaults ---
DEFAULT_IMAGERY_RESOLUTION_TARGET_M = 0.5
DEFAULT_IMAGERY_MAX_CLOUD_COVER_PCT = 20.0
DEFAULT_AOI_BUFFER_M = 100.0
DEFAULT_AOI_MAX_AREA_HA = 10_000.0
DEFAULT_MAX_OFF_NADIR_DEG = 30.0
MAX_OFF_NADIR_DEG_LIMIT = 45.0
MIN_RESOLUTION_M = 0.01

# --- Polling / batching ---
DEFAULT_POLL_INTERVAL_SECONDS = 30
DEFAULT_POLL_TIMEOUT_SECONDS = 1_800
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_SECONDS = 5
DEFAULT_POLL_BATCH_SIZE = 10
DEFAULT_DOWNLOAD_BATCH_SIZE = 10
DEFAULT_POST_PROCESS_BATCH_SIZE = 10

# --- API ---
API_CONTRACT_VERSION = "2026-03-15.1"

# --- Storage containers ---
DEFAULT_INPUT_CONTAINER = "kml-input"
DEFAULT_OUTPUT_CONTAINER = "kml-output"
PIPELINE_PAYLOADS_CONTAINER = "pipeline-payloads"

# --- Geodesy ---
METRES_PER_DEGREE_LATITUDE = 111_320.0
EARTH_RADIUS_M = 6_371_000.0

# --- Metadata schema ---
AOI_METADATA_SCHEMA = "aoi-metadata-v2"
AOI_METADATA_SCHEMA_VERSION = "2.0.0"

# --- HTTP ---
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0
