"""TreeSight — KML satellite imagery pipeline."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("treesight")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0-dev"
