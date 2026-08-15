"""EUDR-regulated commodity reference data (#1384).

Reference data for the seven commodities named in Regulation (EU) 2023/1115
Article 1: cattle, cocoa, coffee, oil palm, rubber, soya, wood. HS/CN codes
below are transcribed from the Regulation's Annex I (Combined Nomenclature,
Regulation (EEC) No 2658/87), verified directly against the consolidated
text at eur-lex.europa.eu (CELEX:32023R1115) on 2026-08-14.

Annex I's Harmonised System heading lists are long — several commodities
(oil palm, rubber, wood) list many more subheadings and ``ex`` (partial)
codes than are enumerated here. Codes here are the commodity's defining/
headline headings, sufficient to populate a due diligence statement DRAFT
for a compliance officer to review — they are explicitly NOT a substitute
for checking the full Annex I text for a specific shipment's exact
subheading, and ``exhaustive=False`` marks the commodities where this
matters most.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EudrCommodityRef:
    """Reference data for one EUDR-regulated commodity."""

    display_name: str
    hs_codes: tuple[tuple[str, str], ...]
    exhaustive: bool


EUDR_COMMODITIES: dict[str, EudrCommodityRef] = {
    "cattle": EudrCommodityRef(
        display_name="Cattle",
        hs_codes=(
            ("0102 21 / 0102 29", "Live cattle"),
            ("ex 0201", "Meat of cattle, fresh or chilled"),
            ("ex 0202", "Meat of cattle, frozen"),
            ("ex 0206 10", "Edible offal of cattle, fresh or chilled"),
            ("ex 0206 22", "Edible cattle livers, frozen"),
            ("ex 0206 29", "Edible cattle offal (excluding tongues and livers), frozen"),
            ("ex 1602 50", "Other prepared or preserved meat, meat offal, blood, of cattle"),
            ("ex 4101", "Raw hides and skins of cattle"),
            ("ex 4104", "Tanned or crust hides and skins of cattle, without hair on"),
            ("ex 4107", "Leather of cattle, further prepared after tanning or crusting"),
        ),
        exhaustive=True,
    ),
    "cocoa": EudrCommodityRef(
        display_name="Cocoa",
        hs_codes=(
            ("1801", "Cocoa beans, whole or broken, raw or roasted"),
            ("1802", "Cocoa shells, husks, skins and other cocoa waste"),
            ("1803", "Cocoa paste, whether or not defatted"),
            ("1804", "Cocoa butter, fat and oil"),
            ("1805", "Cocoa powder, not containing added sugar or other sweetening matter"),
            ("1806", "Chocolate and other food preparations containing cocoa"),
        ),
        exhaustive=True,
    ),
    "coffee": EudrCommodityRef(
        display_name="Coffee",
        hs_codes=(
            (
                "0901",
                "Coffee, whether or not roasted or decaffeinated; coffee husks and "
                "skins; coffee substitutes containing coffee in any proportion",
            ),
        ),
        exhaustive=True,
    ),
    "oil_palm": EudrCommodityRef(
        display_name="Oil palm",
        hs_codes=(
            ("1207 10", "Palm nuts and kernels"),
            ("1511", "Palm oil and its fractions, whether or not refined, not chemically modified"),
            ("1513 21", "Crude palm kernel and babassu oil and fractions thereof"),
            ("1513 29", "Palm kernel and babassu oil and fractions (refined, excluding crude)"),
            ("2306 60", "Oilcake and other solid residues of palm nuts or kernels"),
            ("ex 2905 45", "Glycerol, with a purity of 95% or more"),
            ("2915 70", "Palmitic acid, stearic acid, their salts and esters"),
            ("2915 90", "Saturated acyclic monocarboxylic acids and related derivatives"),
        ),
        exhaustive=False,
    ),
    "rubber": EudrCommodityRef(
        display_name="Rubber",
        hs_codes=(
            ("4001", "Natural rubber, balata, gutta-percha, guayule, chicle and similar natural gums"),
            ("ex 4005", "Compounded rubber, unvulcanised, in primary forms or in plates/sheets/strip"),
            ("ex 4006", "Unvulcanised rubber in other forms (rods, tubes, profile shapes) and articles"),
            ("ex 4007", "Vulcanised rubber thread and cord"),
            ("ex 4008", "Plates, sheets, strips, rods and profile shapes of vulcanised rubber"),
            ("ex 4010", "Conveyor or transmission belts or belting, of vulcanised rubber"),
            ("ex 4011", "New pneumatic tyres, of rubber"),
            ("ex 4012", "Retreaded or used pneumatic tyres; solid or cushion tyres"),
            ("ex 4013", "Inner tubes, of rubber"),
            ("ex 4015", "Articles of apparel and clothing accessories of vulcanised rubber"),
        ),
        exhaustive=False,
    ),
    "soy": EudrCommodityRef(
        display_name="Soya",
        hs_codes=(
            ("1201", "Soya beans, whether or not broken"),
            ("1208 10", "Soya bean flour and meal"),
            ("1507", "Soya-bean oil and its fractions, whether or not refined, not chemically modified"),
            ("2304", "Oilcake and other solid residues resulting from the extraction of soya-bean oil"),
        ),
        exhaustive=True,
    ),
    "wood": EudrCommodityRef(
        display_name="Wood",
        hs_codes=(
            ("4401", "Fuel wood, in logs/billets/twigs/faggots; wood chips/particles; sawdust and waste"),
            ("4402", "Wood charcoal (including shell or nut charcoal)"),
            ("4403", "Wood in the rough, whether or not stripped of bark or sapwood"),
            ("4404", "Hoopwood; split poles; piles, pickets and stakes of wood"),
            ("4405", "Wood wool; wood flour"),
            ("4406", "Railway or tramway sleepers (cross-ties) of wood"),
            ("4407", "Wood sawn or chipped lengthwise, of a thickness exceeding 6 mm"),
            ("4408", "Sheets for veneering, plywood, and similar laminated wood"),
        ),
        exhaustive=False,
    ),
}

_ALIASES: dict[str, str] = {
    "palm oil": "oil_palm",
    "oil palm": "oil_palm",
    "soya": "soy",
    "soybean": "soy",
    "soybeans": "soy",
    "timber": "wood",
}


def normalize_commodity(raw: str) -> str | None:
    """Map free-text commodity input to a canonical EUDR_COMMODITIES key.

    Returns ``None`` for unrecognized input rather than raising — this is
    best-effort metadata for a draft export a compliance officer reviews
    and corrects themselves, not a hard validation gate.
    """
    normalized = raw.strip().lower()
    if not normalized:
        return None
    if normalized in EUDR_COMMODITIES:
        return normalized
    return _ALIASES.get(normalized)
