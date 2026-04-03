"""TreeSight — KML satellite imagery pipeline."""

import contextlib
import importlib.metadata
import os

__version__ = os.environ.get("APP_VERSION") or "0.0.0-dev"
if __version__ == "0.0.0-dev":
    with contextlib.suppress(importlib.metadata.PackageNotFoundError):
        __version__ = importlib.metadata.version("treesight")

__git_sha__ = os.environ.get("GIT_SHA", "unknown")
