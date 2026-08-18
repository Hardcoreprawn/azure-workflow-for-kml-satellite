"""DDS export builder — re-exported from ``treesight.exports.eudr`` (M4 §4.6).

Import from this module for backward compatibility; logic lives in the
domain package ``treesight/exports/eudr.py``.
"""

from treesight.exports.eudr import (
    _build_eudr_dds,
    _plot_geolocation,
)

__all__ = ["_build_eudr_dds", "_plot_geolocation"]
