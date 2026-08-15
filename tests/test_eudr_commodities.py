"""Tests for treesight.eudr_commodities (#1384)."""

from __future__ import annotations

import pytest

from treesight.eudr_commodities import EUDR_COMMODITIES, normalize_commodity


class TestEudrCommodities:
    def test_covers_all_seven_regulated_commodities(self):
        """Regulation (EU) 2023/1115 Article 1 names exactly seven commodities."""
        assert set(EUDR_COMMODITIES) == {
            "cattle",
            "cocoa",
            "coffee",
            "oil_palm",
            "rubber",
            "soy",
            "wood",
        }

    def test_every_commodity_has_at_least_one_hs_code(self):
        for key, ref in EUDR_COMMODITIES.items():
            assert ref.hs_codes, f"{key} has no HS codes"

    def test_every_hs_code_entry_has_code_and_description(self):
        for ref in EUDR_COMMODITIES.values():
            for code, description in ref.hs_codes:
                assert code
                assert description

    def test_coffee_includes_heading_0901(self):
        """Verified against Regulation (EU) 2023/1115 Annex I."""
        codes = [code for code, _ in EUDR_COMMODITIES["coffee"].hs_codes]
        assert "0901" in codes

    def test_cocoa_includes_headings_1801_through_1806(self):
        codes = {code for code, _ in EUDR_COMMODITIES["cocoa"].hs_codes}
        assert {"1801", "1802", "1803", "1804", "1805", "1806"} <= codes

    def test_wood_and_rubber_and_oil_palm_are_marked_non_exhaustive(self):
        """Annex I lists many more CN codes for these three than we enumerate."""
        assert EUDR_COMMODITIES["wood"].exhaustive is False
        assert EUDR_COMMODITIES["rubber"].exhaustive is False
        assert EUDR_COMMODITIES["oil_palm"].exhaustive is False

    def test_cattle_coffee_cocoa_soy_are_exhaustive(self):
        assert EUDR_COMMODITIES["cattle"].exhaustive is True
        assert EUDR_COMMODITIES["coffee"].exhaustive is True
        assert EUDR_COMMODITIES["cocoa"].exhaustive is True
        assert EUDR_COMMODITIES["soy"].exhaustive is True


class TestNormalizeCommodity:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("cattle", "cattle"),
            ("Cattle", "cattle"),
            ("  COCOA  ", "cocoa"),
            ("coffee", "coffee"),
            ("oil palm", "oil_palm"),
            ("Oil Palm", "oil_palm"),
            ("palm oil", "oil_palm"),
            ("rubber", "rubber"),
            ("soy", "soy"),
            ("soya", "soy"),
            ("soybean", "soy"),
            ("wood", "wood"),
            ("timber", "wood"),
        ],
    )
    def test_normalizes_known_aliases(self, raw: str, expected: str):
        assert normalize_commodity(raw) == expected

    def test_returns_none_for_unrecognized_commodity(self):
        assert normalize_commodity("banana") is None

    def test_returns_none_for_empty_string(self):
        assert normalize_commodity("") is None
