"""Provider interface and error hierarchy (§5.1, §5.2)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from treesight.models.aoi import AOI
from treesight.models.imagery import ImageryFilters, SearchResult

ProviderConfig = dict[str, str | int | bool | dict[str, str]]


@dataclass
class OrderStatus:
    state: str
    message: str = ""
    progress_pct: float = 0.0
    is_terminal: bool = False


@dataclass
class BlobReference:
    container: str
    blob_path: str
    size_bytes: int
    content_type: str


class ImageryProvider(ABC):
    """Abstract base for all imagery providers (§5.1)."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        """Initialise with optional provider-specific configuration."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def search(self, aoi: AOI, filters: ImageryFilters) -> list[SearchResult]: ...

    @abstractmethod
    def order(self, scene_id: str) -> str: ...

    @abstractmethod
    def poll(self, order_id: str) -> OrderStatus: ...

    @abstractmethod
    def download(self, order_id: str) -> BlobReference: ...
