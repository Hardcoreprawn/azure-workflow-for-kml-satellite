"""Durable Functions orchestrator functions.

Manages the end-to-end workflow for KML processing:
1. Parse KML → extract features
2. Fan-out per polygon → prepare AOI + acquire imagery + post-process
3. Fan-in → collect results + write summary
"""
