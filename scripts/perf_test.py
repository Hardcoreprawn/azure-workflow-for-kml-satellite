"""Performance and quality validation for the Planetary Computer pipeline.

Runs the pipeline components directly (no Azure Functions / Durable overhead)
to measure real-world search latency, download throughput, and imagery quality.

Usage:
    uv run python scripts/perf_test.py                         # defaults
    uv run python scripts/perf_test.py --asset-key visual      # large true-colour
    uv run python scripts/perf_test.py --asset-key B04         # red band only
    uv run python scripts/perf_test.py --kml tests/fixtures/multi_polygon.kml
    uv run python scripts/perf_test.py --max-items 3 --max-cloud 20
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so treesight imports resolve.
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from treesight.geo import prepare_aoi  # noqa: E402
from treesight.models.imagery import ImageryFilters, SearchResult  # noqa: E402
from treesight.parsers import parse_kml_lxml  # noqa: E402
from treesight.providers.planetary_computer import PlanetaryComputerProvider  # noqa: E402

DEFAULT_KML = "tests/fixtures/sample.kml"
DEFAULT_ASSET_KEY = "visual"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hr_bytes(n: int) -> str:
    """Human-readable byte size."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


def _hr_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.2f} s"


def _validate_tiff_header(data: bytes) -> dict[str, Any]:
    """Check TIFF magic bytes and extract basic info."""
    info: dict[str, Any] = {"valid_tiff": False, "byte_order": "", "size_bytes": len(data)}
    if len(data) < 8:
        info["error"] = "Too small for a TIFF"
        return info

    magic = data[:2]
    if magic == b"II":
        info["byte_order"] = "little-endian"
        fmt = "<H"
    elif magic == b"MM":
        info["byte_order"] = "big-endian"
        fmt = ">H"
    else:
        info["error"] = f"Bad magic: {magic!r}"
        return info

    version = struct.unpack(fmt, data[2:4])[0]
    if version == 42:
        info["valid_tiff"] = True
        info["tiff_type"] = "Classic TIFF"
    elif version == 43:
        info["valid_tiff"] = True
        info["tiff_type"] = "BigTIFF"
    else:
        info["error"] = f"Unknown TIFF version: {version}"

    return info


def _validate_geotiff_rasterio(data: bytes) -> dict[str, Any]:
    """Use rasterio (if importable) to extract CRS, dimensions, bands, dtype."""
    try:
        from rasterio.io import MemoryFile

        with MemoryFile(data) as memfile:
            ds = memfile.open()
            return {
                "width": ds.width,
                "height": ds.height,
                "bands": ds.count,
                "dtype": str(ds.dtypes[0]),
                "crs": str(ds.crs) if ds.crs else None,
                "bounds": list(ds.bounds),
                "transform": list(ds.transform)[:6],
                "nodata": ds.nodata,
                "driver": ds.driver,
                "profile_ok": True,
            }
    except Exception as exc:
        return {"profile_ok": False, "rasterio_error": str(exc)}


# ---------------------------------------------------------------------------
# Pipeline steps (called directly, no Durable Functions)
# ---------------------------------------------------------------------------


def step_parse_kml(kml_path: Path) -> list[dict[str, Any]]:
    """Parse KML → Features → AOIs."""
    features = parse_kml_lxml(kml_path.read_bytes(), source_file=kml_path.name)
    aois = [prepare_aoi(f) for f in features]
    return [
        {
            "feature_name": a.feature_name,
            "bbox": a.bbox,
            "buffered_bbox": a.buffered_bbox,
            "area_ha": a.area_ha,
            "centroid": a.centroid,
            "aoi": a,
        }
        for a in aois
    ]


def step_search(
    provider: PlanetaryComputerProvider,
    aoi_info: dict[str, Any],
    filters: ImageryFilters,
) -> list[SearchResult]:
    """Search PC STAC for a single AOI."""
    return provider.search(aoi_info["aoi"], filters)


def step_download(url: str, bbox: list[float] | None = None) -> tuple[bytes, float]:
    """Download imagery via COG windowed read if *bbox* provided, else full file."""
    from treesight.pipeline.fulfilment import cog_windowed_read, fetch_asset_bytes

    start = time.monotonic()
    data = cog_windowed_read(url, bbox) if bbox else fetch_asset_bytes(url)
    elapsed = time.monotonic() - start
    return data, elapsed


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_search_result(r: SearchResult, rank: int) -> None:
    print(f"  [{rank}] {r.scene_id}")
    print(f"      date       : {r.acquisition_date.strftime('%Y-%m-%d')}")
    print(f"      cloud      : {r.cloud_cover_pct:.1f} %")
    print(f"      resolution : {r.spatial_resolution_m} m")
    print(f"      off-nadir  : {r.off_nadir_deg:.1f}°")
    print(f"      crs        : {r.crs}")
    platform = r.extra.get("platform", "")
    collection = r.extra.get("collection", "")
    asset_key = r.extra.get("asset_key", "")
    if platform:
        print(f"      platform   : {platform}")
    if collection:
        print(f"      collection : {collection}")
    if asset_key:
        print(f"      asset      : {asset_key}")
    if r.asset_url:
        print(f"      url        : {r.asset_url[:100]}...")


def print_imagery_report(data: bytes, elapsed: float, result: SearchResult) -> None:
    """Validate and report on downloaded imagery."""
    size = len(data)
    speed = size / elapsed if elapsed > 0 else 0

    print("\n  --- Imagery quality report ---")
    print(f"  scene     : {result.scene_id}")
    print(f"  size      : {_hr_bytes(size)}")
    print(f"  download  : {_hr_duration(elapsed)}  ({_hr_bytes(int(speed))}/s)")

    # TIFF header check
    hdr = _validate_tiff_header(data)
    if hdr["valid_tiff"]:
        print(f"  tiff      : {hdr['tiff_type']} ({hdr['byte_order']})")
    else:
        print(f"  tiff      : INVALID — {hdr.get('error', 'unknown')}")
        return

    # Rasterio deep inspection
    geo = _validate_geotiff_rasterio(data)
    if geo.get("profile_ok"):
        print(f"  dimensions: {geo['width']} x {geo['height']} px")
        print(f"  bands     : {geo['bands']}")
        print(f"  dtype     : {geo['dtype']}")
        print(f"  crs       : {geo['crs']}")
        print(f"  driver    : {geo['driver']}")
        bounds = geo["bounds"]
        print(f"  bounds    : [{bounds[0]:.6f}, {bounds[1]:.6f}, {bounds[2]:.6f}, {bounds[3]:.6f}]")
        if geo["nodata"] is not None:
            print(f"  nodata    : {geo['nodata']}")

        # Compute pixel coverage of AOI
        px_area_m2 = abs(geo["transform"][0] * geo["transform"][4])  # pixel_w * pixel_h
        total_px = geo["width"] * geo["height"]
        total_area_ha = (total_px * px_area_m2) / 10_000
        print(f"  pixel size: {abs(geo['transform'][0]):.2f} x {abs(geo['transform'][4]):.2f} m")
        print(f"  coverage  : ~{total_area_ha:.1f} ha ({total_px:,} pixels)")
    else:
        print(f"  rasterio  : {geo.get('rasterio_error', 'unavailable')}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Performance & quality test for Planetary Computer pipeline"
    )
    parser.add_argument("--kml", default=DEFAULT_KML, help="KML file to process")
    parser.add_argument("--asset-key", default=DEFAULT_ASSET_KEY, help="PC asset key to download")
    parser.add_argument("--max-items", type=int, default=5, help="Max STAC results per AOI")
    parser.add_argument("--max-cloud", type=float, default=30.0, help="Max cloud cover %%")
    parser.add_argument(
        "--date-range",
        type=int,
        default=90,
        help="Look back N days from today for imagery",
    )
    parser.add_argument(
        "--download-top",
        type=int,
        default=1,
        help="Download the top N results per AOI (0 = search only)",
    )
    parser.add_argument(
        "--compare-assets",
        action="store_true",
        help="Search with multiple asset keys and compare availability/sizes",
    )
    args = parser.parse_args()

    kml_path = Path(args.kml)
    if not kml_path.exists():
        print(f"ERROR: {kml_path} not found")
        sys.exit(1)

    overall_start = time.monotonic()

    # -----------------------------------------------------------------------
    # Phase 1: Parse KML → AOIs
    # -----------------------------------------------------------------------
    print_section("Phase 1 — KML Ingestion")
    t0 = time.monotonic()
    aoi_infos = step_parse_kml(kml_path)
    t_parse = time.monotonic() - t0
    print(f"  Parsed {len(aoi_infos)} features from {kml_path.name} in {_hr_duration(t_parse)}")
    for info in aoi_infos:
        print(
            f"    • {info['feature_name']}  "
            f"area={info['area_ha']:.2f} ha  "
            f"centroid=[{info['centroid'][0]:.4f}, {info['centroid'][1]:.4f}]"
        )

    # -----------------------------------------------------------------------
    # Phase 2: STAC Search
    # -----------------------------------------------------------------------
    print_section("Phase 2 — STAC Search (Planetary Computer)")

    date_end = datetime.now(UTC)
    date_start = date_end - timedelta(days=args.date_range)
    filters = ImageryFilters(
        max_cloud_cover_pct=args.max_cloud,
        date_start=date_start,
        date_end=date_end,
    )
    print(
        f"  Filters: cloud < {args.max_cloud}%, dates {date_start:%Y-%m-%d} → {date_end:%Y-%m-%d}"
    )
    print(f"  Asset key: {args.asset_key}, max items: {args.max_items}")

    provider = PlanetaryComputerProvider(
        config={
            "asset_key": args.asset_key,
            "max_items": args.max_items,
        }
    )

    all_results: dict[str, list[SearchResult]] = {}
    search_times: dict[str, float] = {}

    for info in aoi_infos:
        name = info["feature_name"]
        print(f"\n  Searching for: {name} ...")
        t0 = time.monotonic()
        results = step_search(provider, info, filters)
        t_search = time.monotonic() - t0
        search_times[name] = t_search
        all_results[name] = results

        print(f"  Found {len(results)} scenes in {_hr_duration(t_search)}")
        for i, r in enumerate(results, 1):
            print_search_result(r, i)

    # -----------------------------------------------------------------------
    # Phase 2b (optional): Compare asset keys
    # -----------------------------------------------------------------------
    if args.compare_assets:
        print_section("Phase 2b — Asset Key Comparison")
        compare_keys = ["visual", "B02", "B03", "B04", "B08", "SCL"]
        # Use first AOI for comparison
        info = aoi_infos[0]
        compare_filters = ImageryFilters(
            max_cloud_cover_pct=args.max_cloud,
            date_start=date_start,
            date_end=date_end,
        )
        for key in compare_keys:
            p = PlanetaryComputerProvider(config={"asset_key": key, "max_items": 3})
            t0 = time.monotonic()
            results = step_search(p, info, compare_filters)
            t_s = time.monotonic() - t0
            print(f"  {key:8s}: {len(results)} scenes in {_hr_duration(t_s)}")
            if results:
                r = results[0]
                media = r.extra.get("media_type", "?")
                print(
                    f"            top scene: {r.scene_id}  cloud: {r.cloud_cover_pct:.1f}%  "
                    f"media: {media}"
                )

    # -----------------------------------------------------------------------
    # Phase 3: Download & Validate
    # -----------------------------------------------------------------------
    download_count = args.download_top
    total_bytes = 0
    total_dl_time = 0.0
    download_counter = 0
    if download_count > 0:
        print_section("Phase 3 — Download & Validate Imagery")

        # Build a lookup of aoi name → buffered_bbox
        bbox_lookup = {info["feature_name"]: info["buffered_bbox"] for info in aoi_infos}

        for aoi_name, results in all_results.items():
            to_download = results[:download_count]
            if not to_download:
                print(f"\n  {aoi_name}: No scenes to download")
                continue

            bbox = bbox_lookup.get(aoi_name)
            for r in to_download:
                if not r.asset_url:
                    print(f"\n  {aoi_name} / {r.scene_id}: No asset URL — skipping")
                    continue

                download_counter += 1
                print(f"\n  [{download_counter}] Downloading {aoi_name} / {r.scene_id} ...")
                if bbox:
                    print(f"      COG windowed read  bbox={[round(b, 4) for b in bbox]}")
                try:
                    data, elapsed = step_download(r.asset_url, bbox=bbox)
                    total_bytes += len(data)
                    total_dl_time += elapsed
                    print_imagery_report(data, elapsed, r)
                except Exception as exc:
                    print(f"  DOWNLOAD FAILED: {exc}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    overall_time = time.monotonic() - overall_start
    print_section("Summary")
    print(f"  KML parsing   : {_hr_duration(t_parse)}")
    for name, t in search_times.items():
        print(f"  Search [{name}]: {_hr_duration(t)}")
    if download_count > 0 and total_dl_time > 0:
        avg_speed = total_bytes / total_dl_time
        print(f"  Downloads     : {download_counter} files, {_hr_bytes(total_bytes)} total")
        print(f"  Download time : {_hr_duration(total_dl_time)}")
        print(f"  Avg throughput: {_hr_bytes(int(avg_speed))}/s")
    print(f"  Total elapsed : {_hr_duration(overall_time)}")
    print()


if __name__ == "__main__":
    main()
