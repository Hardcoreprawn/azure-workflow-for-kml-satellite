"""Annex-II-structured due diligence statement (DDS) export draft (#1384).

Builds a JSON document structured to Regulation (EU) 2023/1115 Annex II's
six required fields, for a compliance officer to review, complete, and
submit themselves via EU TRACES NT. This is a DRAFT export, not an
automated submission — see docs/PERSONA_DEEP_DIVE.md #8.8 and issue #1385
for why direct TRACES NT API submission is a separate, deliberately
deferred item.
"""

from typing import Any

from treesight.eudr_commodities import EUDR_COMMODITIES, normalize_commodity

# Verbatim from Regulation (EU) 2023/1115, Annex II, item 5.
_DDS_DECLARATION_TEXT = (
    "By submitting this due diligence statement the operator confirms that "
    "due diligence in accordance with Regulation (EU) 2023/1115 was carried "
    "out and that no or only a negligible risk was found that the relevant "
    "products do not comply with Article 3, point (a) or (b), of that "
    "Regulation."
)

_DDS_DISCLAIMER = (
    "DRAFT export for review only. This document is not a submitted due "
    "diligence statement and has not been transmitted to EU TRACES NT. The "
    "operator remains responsible for verifying every field (HS/CN code, "
    "quantity, country of production, legality evidence) and for formally "
    "submitting the statement themselves."
)


def _operator_block(manifest: dict[str, Any]) -> dict[str, Any]:
    """Annex II item 1: operator's name, address, and EORI number."""
    return {
        "name": manifest.get("operator_name") or "",
        "address": manifest.get("operator_address") or "",
        "eori": manifest.get("operator_eori") or "",
    }


def _product_block(manifest: dict[str, Any]) -> dict[str, Any]:
    """Annex II item 2: HS code, description, quantity."""
    raw_commodity = manifest.get("commodity") or ""
    normalized = normalize_commodity(raw_commodity)
    hs_codes = list(EUDR_COMMODITIES[normalized].hs_codes) if normalized else []
    return {
        "commodity": raw_commodity,
        "commodity_recognized": normalized is not None,
        "hs_codes": hs_codes,
        "description": manifest.get("product_description") or "",
        "scientific_name": manifest.get("scientific_name") or "",
        "quantity_kg": manifest.get("quantity_kg"),
    }


def _plot_geolocation(aoi: dict[str, Any], *, is_cattle: bool) -> dict[str, Any]:
    """Article 2(28): point for cattle establishments or plots <=4 ha, else polygon."""
    center = aoi.get("center", {})
    point = [center.get("lon"), center.get("lat")]
    area_ha = aoi.get("area_ha", 0.0)
    if is_cattle or area_ha <= 4.0:
        return {"geolocation_type": "point", "coordinates": point}
    return {"geolocation_type": "polygon", "coordinates": list(aoi.get("coords", []))}


def _production_block(manifest: dict[str, Any]) -> dict[str, Any]:
    """Annex II item 3: country of production and geolocation of all plots.

    Failed AOIs are included with an ``error`` marker and no geolocation,
    rather than silently omitted — a shorter plot list must not be mistaken
    for a smaller, fully-enriched supply chain (matches the eudr-geojson/
    eudr-csv exports, which surface failures the same way).
    """
    is_cattle = normalize_commodity(manifest.get("commodity") or "") == "cattle"
    per_aoi = manifest.get("per_aoi_enrichment", [])
    plots: list[dict[str, Any]] = []
    for aoi in per_aoi:
        if "error" in aoi:
            plots.append({"name": aoi.get("name", ""), "error": aoi["error"]})
            continue
        plot = {"name": aoi.get("name", ""), "area_ha": aoi.get("area_ha", 0.0)}
        plot.update(_plot_geolocation(aoi, is_cattle=is_cattle))
        plots.append(plot)
    return {
        "country_of_production": manifest.get("country_of_production") or "",
        "plots": plots,
    }


def _reference_block(manifest: dict[str, Any]) -> dict[str, Any]:
    """Annex II item 4: reference number of an existing DDS, if referring to one."""
    return {"reference_number": manifest.get("existing_dds_reference")}


def _signature_block() -> dict[str, str]:
    """Annex II item 6: blank signature template — filled in by the operator."""
    return {
        "signed_for_and_on_behalf_of": "",
        "date": "",
        "name_and_function": "",
        "signature": "",
    }


def _build_eudr_dds(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build an Annex-II-structured DDS export draft from the enrichment manifest."""
    return {
        "dds_annex_ii": {
            "1_operator": _operator_block(manifest),
            "2_product": _product_block(manifest),
            "3_production": _production_block(manifest),
            "4_reference_to_existing_statement": _reference_block(manifest),
            "5_declaration": _DDS_DECLARATION_TEXT,
            "6_signature": _signature_block(),
        },
        "_disclaimer": _DDS_DISCLAIMER,
    }
