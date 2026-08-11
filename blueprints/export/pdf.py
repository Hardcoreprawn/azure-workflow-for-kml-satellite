"""Basic PDF report builder and helpers (M4 §4.6)."""

from typing import Any

from treesight.constants import EUDR_CUTOFF_DATE


def _safe_text(text: str) -> str:
    """Normalise unicode punctuation to latin-1 safe equivalents for core PDF fonts."""
    return (
        text.replace("\u2014", "--")
        .replace("\u2013", "-")
        .replace("\u2026", "...")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2192", "->")
        .replace("\u2190", "<-")
    )


def _pdf_scene_provenance_section(pdf: Any, frame_plan: list[dict[str, Any]]) -> None:
    """Write a scene-provenance table for every frame in the report (#647).

    Each row records the satellite scene identifier, collection, spatial
    resolution, cloud-cover percentage, and acquisition date so the imagery
    evidence can be independently verified.
    """
    if not frame_plan:
        return

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Scene Provenance", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(
        0,
        5,
        "The table below records the satellite scene used for each analysis "
        "window so that imagery evidence can be independently verified.",
    )
    pdf.ln(3)

    # Column widths (fractions of effective page width)
    col_ratios = [0.18, 0.14, 0.12, 0.28, 0.12, 0.16]
    page_w = pdf.epw
    col_widths = [round(r * page_w, 1) for r in col_ratios]
    headers = ["Label", "Collection", "Res (m)", "Scene ID", "Cloud %", "Acquired"]

    pdf.set_font("Helvetica", "B", 8)
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 6, h, border=1)
    pdf.ln()

    pdf.set_font("Helvetica", "", 7)
    for frame in frame_plan:
        prov = frame.get("provenance") or {}
        scene_id = prov.get("ndvi_scene_id") or prov.get("display_search_id") or "--"
        resolution = prov.get("resolution_m")
        cloud = prov.get("cloud_cover_pct")
        acquired = (prov.get("acquired_at") or "")[:10]
        collection = prov.get("collection") or frame.get("collection") or "--"

        row = [
            _safe_text(frame.get("label", ""))[:18],
            collection[:14],
            str(resolution) if resolution is not None else "--",
            _safe_text(str(scene_id))[:28],
            f"{float(cloud):.1f}" if cloud is not None else "--",
            acquired or "--",
        ]
        for i, val in enumerate(row):
            pdf.cell(col_widths[i], 5, val, border=1)
        pdf.ln()

    pdf.ln(6)


def _pdf_header(pdf: Any, manifest: dict[str, Any], instance_id: str) -> None:
    """Write title and metadata section of the PDF."""
    eudr_mode = manifest.get("eudr_mode", False)
    center = manifest.get("center", {})

    pdf.set_font("Helvetica", "B", 18)
    title = "EUDR Due-Diligence Report" if eudr_mode else "Canopex Analysis Report"
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Report ID: {instance_id}", new_x="LMARGIN", new_y="NEXT")
    enriched_at = manifest.get("enriched_at", "")
    if enriched_at:
        pdf.cell(0, 6, f"Generated: {enriched_at[:19]}", new_x="LMARGIN", new_y="NEXT")
    if center:
        pdf.cell(
            0,
            6,
            f"Location: {center.get('lat', 0):.4f}, {center.get('lon', 0):.4f}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    pdf.ln(6)


def _pdf_eudr_section(pdf: Any, manifest: dict[str, Any]) -> None:
    """Write EUDR compliance summary section."""
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "EUDR Compliance Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    cutoff = manifest.get("eudr_date_start", EUDR_CUTOFF_DATE)
    pdf.cell(0, 6, "EUDR cutoff date: 31 December 2020", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0,
        6,
        f"Analysis period: {cutoff} to present",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    wc = manifest.get("worldcover", {})
    if wc.get("available"):
        lc = wc.get("land_cover", {})
        dominant = lc.get("dominant_class", "N/A")
        pdf.cell(
            0,
            6,
            f"ESA WorldCover: {dominant} (dominant)",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        for cls in lc.get("classes", [])[:5]:
            label = cls.get("label") or "Unknown"
            area_pct = cls.get("area_pct")
            try:
                area_pct_str = f"{float(area_pct):.1f}%" if area_pct is not None else "N/A"
            except (TypeError, ValueError):
                area_pct_str = "N/A"
            pdf.cell(
                0,
                5,
                f"  {label}: {area_pct_str}",
                new_x="LMARGIN",
                new_y="NEXT",
            )

    wdpa = manifest.get("wdpa", {})
    if wdpa.get("checked"):
        status = "Yes -- protected area overlap detected" if wdpa.get("is_protected") else "No"
        pdf.cell(
            0,
            6,
            f"Protected area (WDPA): {status}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        for pa in wdpa.get("protected_areas", []):
            pdf.cell(
                0,
                6,
                _safe_text(f"  - {pa.get('name', '')} ({pa.get('designation', '')})"),
                new_x="LMARGIN",
                new_y="NEXT",
            )

    pdf.ln(4)


def _pdf_vegetation_section(
    pdf: Any,
    manifest: dict[str, Any],
) -> None:
    """Write vegetation analysis and frame detail table."""
    frame_plan = manifest.get("frame_plan", [])
    ndvi_stats = manifest.get("ndvi_stats", [])
    change_detection = manifest.get("change_detection", {})

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Vegetation Analysis", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)

    summary = change_detection.get("summary", {})
    if summary:
        trajectory = summary.get("trajectory", "Unknown")
        comparisons = summary.get("comparisons", 0)
        pdf.cell(
            0,
            6,
            f"Trajectory: {trajectory} ({comparisons} year-over-year comparisons)",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    valid_ndvi = [s for s in ndvi_stats if s and s.get("mean") is not None]
    if valid_ndvi:
        means = [s["mean"] for s in valid_ndvi]
        overall_avg = sum(means) / len(means)
        pdf.cell(
            0,
            6,
            f"NDVI observations: {len(valid_ndvi)} frames, "
            f"average: {overall_avg:.3f}, "
            f"range: {min(means):.3f} to {max(means):.3f}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    pdf.ln(4)

    # Frame detail table
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Frame Details", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 8)
    col_ratios = [0.18, 0.11, 0.11, 0.16, 0.16, 0.12, 0.16]
    page_w = pdf.epw  # effective page width (inside margins)
    col_widths = [round(r * page_w, 1) for r in col_ratios]
    headers_row = ["Label", "Year", "Season", "Start", "End", "NDVI Mean", "Collection"]
    for i, h in enumerate(headers_row):
        pdf.cell(col_widths[i], 6, h, border=1)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for idx, frame in enumerate(frame_plan):
        ndvi = ndvi_stats[idx] if idx < len(ndvi_stats) else None
        ndvi_val = f"{ndvi['mean']:.3f}" if ndvi and ndvi.get("mean") is not None else "--"
        row_data = [
            _safe_text(frame.get("label", ""))[:18],
            str(frame.get("year", "")),
            frame.get("season", ""),
            frame.get("start", ""),
            frame.get("end", ""),
            ndvi_val,
            frame.get("collection", ""),
        ]
        for i, val in enumerate(row_data):
            pdf.cell(col_widths[i], 5, val, border=1)
        pdf.ln()

    pdf.ln(6)


def _pdf_per_parcel_sections(pdf: Any, per_aoi: list[dict[str, Any]]) -> None:
    """Write per-parcel EUDR evidence sections (#582)."""
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Per-Parcel Evidence", new_x="LMARGIN", new_y="NEXT")

    for idx, aoi in enumerate(per_aoi):
        name = aoi.get("name", f"Parcel {idx + 1}")

        if "error" in aoi:
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 8, _safe_text(f"{name} -- ERROR"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, 5, "Enrichment failed for this parcel.", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
            continue

        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, _safe_text(name), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)

        # Area and location
        area = aoi.get("area_ha", 0.0)
        center = aoi.get("center", {})
        pdf.cell(
            0,
            5,
            f"Area: {area:.2f} ha | Centre: {center.get('lat', 0):.4f}, {center.get('lon', 0):.4f}",
            new_x="LMARGIN",
            new_y="NEXT",
        )

        # Determination
        det = aoi.get("determination", {})
        status = det.get("status", "unknown")
        confidence = det.get("confidence", "unknown")
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(
            0,
            5,
            f"Determination: {status} (confidence: {confidence})",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font("Helvetica", "", 9)
        for flag in det.get("flags", []):
            pdf.cell(0, 5, _safe_text(f"  - {flag}"), new_x="LMARGIN", new_y="NEXT")

        # WorldCover
        wc = aoi.get("worldcover", {})
        if wc.get("available"):
            lc = wc.get("land_cover", {})
            pdf.cell(
                0,
                5,
                f"WorldCover: {lc.get('dominant_class', 'N/A')} (dominant)",
                new_x="LMARGIN",
                new_y="NEXT",
            )

        # WDPA
        wdpa = aoi.get("wdpa", {})
        if wdpa.get("checked"):
            prot = "Yes" if wdpa.get("is_protected") else "No"
            pdf.cell(
                0,
                5,
                f"Protected area overlap: {prot}",
                new_x="LMARGIN",
                new_y="NEXT",
            )

        # NDVI summary
        ndvi_stats = aoi.get("ndvi_stats", [])
        valid = [s for s in ndvi_stats if s and s.get("mean") is not None]
        if valid:
            means = [s["mean"] for s in valid]
            pdf.cell(
                0,
                5,
                f"NDVI: {len(valid)} observations, latest {means[-1]:.3f}, range {min(means):.3f}-{max(means):.3f}",
                new_x="LMARGIN",
                new_y="NEXT",
            )

        # Change detection
        cd = aoi.get("change_detection", {}).get("summary", {})
        if cd:
            pdf.cell(
                0,
                5,
                f"Change trajectory: {cd.get('trajectory', 'unknown')} ({cd.get('comparisons', 0)} comparisons)",
                new_x="LMARGIN",
                new_y="NEXT",
            )

        pdf.ln(3)


def _build_pdf(manifest: dict[str, Any], instance_id: str = "") -> bytes:
    """Build an audit-quality PDF report from the enrichment manifest.

    Uses fpdf2 (pure Python, no system dependencies).
    """
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    _pdf_header(pdf, manifest, instance_id)

    if manifest.get("eudr_mode", False):
        _pdf_eudr_section(pdf, manifest)

    _pdf_vegetation_section(pdf, manifest)

    # Weather summary
    weather_monthly = manifest.get("weather_monthly")
    if weather_monthly:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Weather Context", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        if isinstance(weather_monthly, list):
            months = [m.get("month", "") for m in weather_monthly]
            temps = [m.get("mean_temp") for m in weather_monthly]
            precips = [m.get("total_precip") for m in weather_monthly]
        else:
            months = weather_monthly.get("months", []) or weather_monthly.get("labels", [])
            temps = weather_monthly.get("avg_temp", []) or weather_monthly.get("temp", [])
            precips = weather_monthly.get("total_precip", []) or weather_monthly.get("precip", [])
        if months:
            pdf.cell(
                0,
                6,
                f"Weather period: {months[0]} to {months[-1]} ({len(months)} months)",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        if temps:
            avg_t = sum(t for t in temps if t is not None) / max(1, len([t for t in temps if t is not None]))
            pdf.cell(0, 6, f"Mean temperature: {avg_t:.1f} C", new_x="LMARGIN", new_y="NEXT")
        if precips:
            total_p = sum(p for p in precips if p is not None)
            pdf.cell(
                0,
                6,
                f"Total precipitation: {total_p:.0f} mm",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        pdf.ln(4)

    # Per-parcel EUDR evidence sections (#582)
    per_aoi = manifest.get("per_aoi_enrichment", [])
    if per_aoi:
        _pdf_per_parcel_sections(pdf, per_aoi)

    # Scene provenance table (#647) — traceability appendix listing scene IDs,
    # resolution and cloud cover for every analysis frame.
    _pdf_scene_provenance_section(pdf, manifest.get("frame_plan", []))

    # Disclaimer
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(
        0,
        4,
        "Disclaimer: This report is generated from satellite imagery analysis and "
        "provides supporting evidence only. It does not constitute a complete EUDR "
        "due-diligence assessment under Regulation (EU) 2023/1115. Operators remain "
        "responsible for fulfilling all regulatory obligations.",
    )

    return bytes(pdf.output())
