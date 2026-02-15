"""Durable Functions activity functions.

Each activity performs a single unit of work within the orchestration:
- parse_kml: Extract features and geometry from KML files
- prepare_aoi: Compute bounding box, buffer, area, centroid
- acquire_imagery: Search, order, and download satellite imagery
- post_process: Clip, reproject, store imagery and metadata
"""
