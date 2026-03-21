"""KML parsing (§7)."""

import zipfile
from io import BytesIO


def ensure_closed(ring: list[list[float]]) -> list[list[float]]:
    """Ensure a coordinate ring is closed (first == last).

    Appends a copy of the first coordinate if the ring has ≥ 3 vertices
    and is not already closed.
    """
    if len(ring) >= 3 and ring[0] != ring[-1]:
        ring.append(ring[0][:])
    return ring


# ZIP local-file-header magic bytes (PK\x03\x04)
_ZIP_MAGIC = b"PK\x03\x04"


def maybe_unzip(data: bytes) -> bytes:
    """If *data* is a KMZ (ZIP archive), extract and return ``doc.kml``.

    Falls back to the first ``*.kml`` entry if ``doc.kml`` is absent.
    Returns *data* unchanged if it is not a ZIP archive.

    Raises ``ValueError`` if the archive contains no KML file.
    """
    if not data.startswith(_ZIP_MAGIC):
        return data

    with zipfile.ZipFile(BytesIO(data)) as zf:
        # Prefer the canonical KMZ entry
        if "doc.kml" in zf.namelist():
            return zf.read("doc.kml")

        # Fall back to first .kml file found
        for name in zf.namelist():
            if name.lower().endswith(".kml"):
                return zf.read(name)

    raise ValueError("KMZ archive contains no .kml file")


from treesight.parsers.fiona_parser import parse_kml_fiona  # noqa: E402
from treesight.parsers.lxml_parser import parse_kml_lxml  # noqa: E402

__all__ = ["ensure_closed", "maybe_unzip", "parse_kml_fiona", "parse_kml_lxml"]
