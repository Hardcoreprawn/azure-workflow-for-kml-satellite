"""Pipeline-wide constants (Appendix A of SYSTEM_SPEC).

Coordinate convention
---------------------
All coordinate pairs in this project are **[longitude, latitude]** (x, y),
consistent with GeoJSON (RFC 7946), KML, STAC, and GDAL/Fiona.  This is the
opposite of the colloquial "lat/lon" order used by Google Maps and everyday
speech.  Every function, model, test fixture, and data contract must follow
this convention.
"""

import os

# --- Size limits ---
MAX_KML_FILE_SIZE_BYTES = 10_485_760  # 10 MiB
MAX_FEATURES_PER_KML = 500
PAYLOAD_OFFLOAD_THRESHOLD_BYTES = 49_152  # 48 KiB

# --- KMZ decompression safety ---
MAX_KMZ_DECOMPRESSED_BYTES = 50_000_000  # 50 MiB — reject zip bombs
MAX_KMZ_COMPRESSION_RATIO = 100  # compressed-to-decompressed ratio ceiling
MAX_KMZ_FILE_COUNT = 50  # max entries in a KMZ archive

# --- Imagery defaults ---
DEFAULT_IMAGERY_RESOLUTION_TARGET_M = 0.5
DEFAULT_IMAGERY_MAX_CLOUD_COVER_PCT = 20.0
DEFAULT_AOI_BUFFER_M = 100.0
DEFAULT_AOI_MAX_AREA_HA = 10_000.0
BATCH_FALLBACK_AREA_HA = 50_000.0  # AOIs above this route to Azure Batch Spot VMs
DEFAULT_MAX_OFF_NADIR_DEG = 30.0
MAX_OFF_NADIR_DEG_LIMIT = 45.0
MIN_RESOLUTION_M = 0.01
DEFAULT_PROVIDER = "planetary_computer"

# --- Polling / batching ---
DEFAULT_POLL_INTERVAL_SECONDS = 30
DEFAULT_POLL_TIMEOUT_SECONDS = 1_800
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_SECONDS = 5
MAX_POLL_ITERATIONS = 120  # hard upper bound on poll loop iterations (safety net)
DEFAULT_POLL_BATCH_SIZE = 10
DEFAULT_DOWNLOAD_BATCH_SIZE = 10
DEFAULT_POST_PROCESS_BATCH_SIZE = 10
DEFAULT_ACQUISITION_BATCH_SIZE = 25
BATCH_POLL_INTERVAL_SECONDS = 60
try:
    DEFAULT_ENRICHMENT_CONCURRENCY = int(os.environ.get("ENRICHMENT_CONCURRENCY", "8"))
except (ValueError, TypeError):
    DEFAULT_ENRICHMENT_CONCURRENCY = 8

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

# --- AI inference ---
AI_MAX_TOKENS = 1000
AI_AZURE_TIMEOUT_SECONDS = 60.0
AI_OLLAMA_TIMEOUT_SECONDS = 150.0

# --- Rate limiting (requests per window) ---
RATE_LIMIT_FORM_MAX = 5
RATE_LIMIT_FORM_WINDOW = 60
RATE_LIMIT_PIPELINE_MAX = 30
RATE_LIMIT_PIPELINE_WINDOW = 60
RATE_LIMIT_PROXY_MAX = 60
RATE_LIMIT_PROXY_WINDOW = 60

# --- EUDR (EU Deforestation Regulation) ---
# Article 2 cutoff date: land must have been forest on 31 Dec 2020.
# Analysis frames start from 2021-01-01 onward.
EUDR_CUTOFF_DATE = "2020-12-31"

# --- Billing ---
DEMO_TIER_RUN_LIMIT = 3
FREE_TIER_RUN_LIMIT = 5
STARTER_TIER_RUN_LIMIT = 15
PRO_TIER_RUN_LIMIT = 50
TEAM_TIER_RUN_LIMIT = 200
ENTERPRISE_TIER_RUN_LIMIT = 10_000
SUPPORTED_CURRENCIES = ("GBP", "USD", "EUR")
DEFAULT_CURRENCY = "GBP"
SUBSCRIPTIONS_PREFIX = "subscriptions"

# --- Rate limiting (demo) ---
# RATE_LIMIT_DEMO_MAX caps API requests per window (HTTP rate-limiter);
# DEMO_TIER_RUN_LIMIT caps total pipeline runs (billing quota).
RATE_LIMIT_DEMO_MAX = 3
RATE_LIMIT_DEMO_WINDOW = 3600  # 1 hour
