"""Canopex — KML satellite imagery pipeline."""

import os

__version__ = os.environ.get("APP_VERSION", "0.0.0-dev")
__git_sha__ = os.environ.get("GIT_SHA", "unknown")
