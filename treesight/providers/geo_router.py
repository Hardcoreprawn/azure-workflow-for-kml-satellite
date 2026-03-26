"""Geographic routing provider — multi-source imagery aggregation (§5.5).

Selects optimal imagery collections based on AOI geographic location,
aggregating results from the best available free sources on
Microsoft Planetary Computer.

Coverage map::

    Region          │ Collections (priority order)         │ Best GSD
    ────────────────┼──────────────────────────────────────┼─────────
    US Continental  │ NAIP → Sentinel-2 → Landsat          │ 0.6  m
    Tropics (±23.5°)│ Sentinel-2 → Landsat                 │ 10   m
    Europe          │ Sentinel-2 → Landsat                 │ 10   m
    US Alaska       │ Sentinel-2 → Landsat                 │ 10   m
    US Hawaii       │ Sentinel-2 → Landsat                 │ 10   m
    Global fallback │ Sentinel-2 → Landsat                 │ 10   m

Future sources (hooks present, not yet wired):
  - IGN BD ORTHO (France, 0.2 m) via WMS
  - Ordnance Survey Aerial (UK, 0.25 m) via WMTS
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from treesight.log import log_phase
from treesight.models.aoi import AOI
from treesight.models.imagery import ImageryFilters, SearchResult
from treesight.providers.base import BlobReference, ImageryProvider, OrderStatus, ProviderConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Region classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Region:
    """Geographic region with bounding box and imagery source priority."""

    name: str
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    collections: tuple[str, ...]
    best_resolution_m: float

    def contains(self, lat: float, lon: float) -> bool:
        """Return ``True`` if *lat*/*lon* falls inside this region."""
        return self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon


# Checked in order — first match wins.
# Each region lists collections in priority order: best resolution first,
# broadest-coverage fallback last.  Landsat C2 L2 (30 m, back to 1982)
# acts as a universal historical fallback.
REGIONS: list[Region] = [
    # --- Americas ----------------------------------------------------------
    Region("us_conus", 24.0, -125.0, 50.0, -66.0, ("naip", "sentinel-2-l2a", "landsat-c2-l2"), 0.6),
    Region("us_alaska", 51.0, -180.0, 72.0, -130.0, ("sentinel-2-l2a", "landsat-c2-l2"), 10.0),
    Region("us_hawaii", 18.0, -161.0, 23.0, -154.0, ("sentinel-2-l2a", "landsat-c2-l2"), 10.0),
    # --- Tropics (key for EUDR deforestation monitoring) ------------------
    Region(
        "tropics_americas", -23.5, -93.0, 23.5, -34.0, ("sentinel-2-l2a", "landsat-c2-l2"), 10.0
    ),
    Region("tropics_africa", -23.5, -18.0, 23.5, 52.0, ("sentinel-2-l2a", "landsat-c2-l2"), 10.0),
    Region("tropics_asia", -23.5, 52.0, 23.5, 180.0, ("sentinel-2-l2a", "landsat-c2-l2"), 10.0),
    # --- Europe -----------------------------------------------------------
    Region("europe", 35.0, -11.0, 72.0, 40.0, ("sentinel-2-l2a", "landsat-c2-l2"), 10.0),
]

GLOBAL_FALLBACK = Region(
    "global",
    -90.0,
    -180.0,
    90.0,
    180.0,
    ("sentinel-2-l2a", "landsat-c2-l2"),
    10.0,
)


def classify_region(lat: float, lon: float) -> Region:
    """Classify a centroid into the best-matching coverage region."""
    for region in REGIONS:
        if region.contains(lat, lon):
            return region
    return GLOBAL_FALLBACK


# ---------------------------------------------------------------------------
# GeoRoutingProvider
# ---------------------------------------------------------------------------


class GeoRoutingProvider(ImageryProvider):
    """Routes imagery requests to optimal sources based on AOI location.

    Wraps :class:`PlanetaryComputerProvider` internally, selecting the
    most relevant STAC collections per region.  Skips irrelevant
    collections (e.g. NAIP for European AOIs) to reduce API latency.
    """

    def __init__(self, config: ProviderConfig | None = None) -> None:
        super().__init__(config)
        config = config or {}
        self._stub_mode = bool(config.get("stub_mode", False))
        self._pc_config: ProviderConfig = dict(config)

    @property
    def name(self) -> str:
        return "geo_routing"

    # -- internal helpers ---------------------------------------------------

    def _make_pc(self, collections: list[str]) -> Any:
        """Create a :class:`PlanetaryComputerProvider` for *collections*."""
        from treesight.providers.planetary_computer import PlanetaryComputerProvider

        pc_config: ProviderConfig = dict(self._pc_config)
        pc_config["collections"] = collections
        pc_config["fallback"] = True
        return PlanetaryComputerProvider(pc_config)

    def _route(self, aoi: AOI) -> Region:
        """Determine the coverage region for an AOI."""
        lon, lat = aoi.centroid[0], aoi.centroid[1]
        return classify_region(lat, lon)

    # -- ImageryProvider interface ------------------------------------------

    def search(self, aoi: AOI, filters: ImageryFilters) -> list[SearchResult]:
        """Search region-appropriate collections for imagery."""
        region = self._route(aoi)

        log_phase(
            "acquisition",
            "geo_routing_search",
            aoi_name=aoi.feature_name,
            provider=self.name,
            region=region.name,
            collections=",".join(region.collections),
        )

        # Honour explicit caller-specified collections.
        collections = list(filters.collections) if filters.collections else list(region.collections)

        pc = self._make_pc(collections)
        results = pc.search(aoi, filters)

        for r in results:
            r.extra["region"] = region.name
            r.extra["routed_by"] = self.name

        log_phase(
            "acquisition",
            "geo_routing_complete",
            aoi_name=aoi.feature_name,
            region=region.name,
            results_count=len(results),
        )
        return results

    def order(self, scene_id: str) -> str:
        pc = self._make_pc([])
        return pc.order(scene_id)

    def poll(self, order_id: str) -> OrderStatus:
        pc = self._make_pc([])
        return pc.poll(order_id)

    def download(self, order_id: str) -> BlobReference:
        pc = self._make_pc([])
        return pc.download(order_id)

    def composite_search(
        self,
        aoi: AOI,
        filters: ImageryFilters,
        *,
        temporal_count: int = 6,
    ) -> list[SearchResult]:
        """Composite search with region-aware collection selection."""
        region = self._route(aoi)
        pc = self._make_pc(list(region.collections))
        results = pc.composite_search(aoi, filters, temporal_count=temporal_count)

        for r in results:
            r.extra["region"] = region.name
            r.extra["routed_by"] = self.name

        return results
