"""KML Satellite Imagery Acquisition Pipeline.

Automated Azure workflow that ingests KML files containing agricultural
field boundaries, extracts polygon geometry, acquires high-resolution
satellite imagery, and stores outputs in Azure Blob Storage.
"""

__version__ = "0.1.0"
