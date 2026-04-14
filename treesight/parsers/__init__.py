"""KML parsing (§7)."""

import re
import zipfile
from io import BytesIO

from treesight.constants import (
    MAX_KMZ_COMPRESSION_RATIO,
    MAX_KMZ_DECOMPRESSED_BYTES,
    MAX_KMZ_FILE_COUNT,
)


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

# KML namespace URIs we accept
_KML_NAMESPACES = {
    "http://www.opengis.net/kml/2.2",
    "http://earth.google.com/kml/2.2",
    "http://earth.google.com/kml/2.1",
    "http://earth.google.com/kml/2.0",
}


def maybe_unzip(data: bytes) -> bytes:
    """If *data* is a KMZ (ZIP archive), extract and return ``doc.kml``.

    Falls back to the first ``*.kml`` entry if ``doc.kml`` is absent.
    Returns *data* unchanged if it is not a ZIP archive.

    Raises ``ValueError`` if the archive fails safety checks or contains
    no KML file.
    """
    if not data.startswith(_ZIP_MAGIC):
        return data

    with zipfile.ZipFile(BytesIO(data)) as zf:
        entries = zf.infolist()

        # --- safety checks ---
        if len(entries) > MAX_KMZ_FILE_COUNT:
            raise ValueError(f"KMZ file count {len(entries)} exceeds limit of {MAX_KMZ_FILE_COUNT}")

        for info in entries:
            if info.file_size > MAX_KMZ_DECOMPRESSED_BYTES:
                raise ValueError(
                    f"Decompressed size of '{info.filename}' "
                    f"({info.file_size:,} bytes) exceeds limit "
                    f"of {MAX_KMZ_DECOMPRESSED_BYTES:,} bytes"
                )
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > MAX_KMZ_COMPRESSION_RATIO:
                    raise ValueError(
                        f"Compression ratio of '{info.filename}' "
                        f"({ratio:.0f}:1) exceeds limit "
                        f"of {MAX_KMZ_COMPRESSION_RATIO}:1"
                    )

        # --- extract the KML entry ---
        # Prefer the canonical KMZ entry
        if "doc.kml" in zf.namelist():
            return zf.read("doc.kml")

        # Fall back to first .kml file found
        for name in zf.namelist():
            if name.lower().endswith(".kml"):
                return zf.read(name)

    raise ValueError("KMZ archive contains no .kml file")


_DOCTYPE_RE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)


def validate_kml_bytes(data: bytes) -> None:
    """Validate raw KML bytes for structural safety before parsing.

    Checks:
    1. Well-formed XML (can be parsed at all).
    2. No DOCTYPE declaration (blocks XXE and entity-expansion attacks).
    3. Root element uses a recognised KML namespace.

    Raises ``ValueError`` on any violation.
    """
    # Fast pre-flight: reject DOCTYPE before even touching the XML parser
    if _DOCTYPE_RE.search(data[:4096]):
        raise ValueError(
            "KML contains a DOCTYPE declaration — DTD/entity declarations are not permitted"
        )

    from lxml import etree

    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Malformed XML: {exc}") from exc

    # Verify KML namespace on root element
    ns = etree.QName(root).namespace or ""
    if ns not in _KML_NAMESPACES:
        raise ValueError(f"Root element namespace '{ns}' is not a recognised KML namespace")


from treesight.parsers.fiona_parser import parse_kml_fiona  # noqa: E402
from treesight.parsers.lxml_parser import parse_kml_lxml  # noqa: E402


def count_kml_features(kml_bytes: bytes) -> int:
    """Count Placemark elements containing at least one Polygon.

    This is a lightweight pre-parse check for AOI limit enforcement.
    It does *not* validate geometry — just counts features that would
    produce AOIs in a full parse.

    Raises ``ValueError`` on malformed XML.
    """
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, dtd_validation=False)
    try:
        root = etree.fromstring(kml_bytes, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Malformed XML: {exc}") from exc

    count = 0
    # Check all recognised KML namespaces
    for ns in _KML_NAMESPACES:
        ns_prefix = f"{{{ns}}}"
        for placemark in root.iter(f"{ns_prefix}Placemark"):
            if placemark.find(f".//{ns_prefix}Polygon") is not None:
                count += 1
    return count


__all__ = [
    "count_kml_features",
    "ensure_closed",
    "maybe_unzip",
    "parse_kml_fiona",
    "parse_kml_lxml",
    "validate_kml_bytes",
]
