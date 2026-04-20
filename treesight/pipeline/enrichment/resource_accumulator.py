"""ResourceAccumulator — tracks resource consumption across enrichment phases (#666)."""

from __future__ import annotations

_VALID_COUNTERS = frozenset(
    {
        "sentinel2_scenes_registered",
        "landsat_scenes_sampled",
        "ndvi_computations",
        "change_detection_comparisons",
        "mosaic_registrations",
        "per_aoi_enrichments",
    }
)


class ResourceAccumulator:
    """Accumulates resource usage metrics during enrichment.

    Intended for single-threaded mutation within each phase function.
    Designed to be merged after parallel fan-out (data_sources ∥ imagery).
    """

    def __init__(self) -> None:
        self._sources: list[str] = []
        self._source_set: set[str] = set()
        self._api_calls: dict[str, int] = {}
        self._phase_durations: dict[str, float] = {}
        self._counters: dict[str, int] = dict.fromkeys(_VALID_COUNTERS, 0)

    def add_source(self, source: str) -> None:
        """Record a data source as consulted (deduplicated, order-preserving)."""
        if source not in self._source_set:
            self._source_set.add(source)
            self._sources.append(source)

    def add_api_call(self, service: str, *, count: int = 1) -> None:
        """Increment the API call counter for a service."""
        self._api_calls[service] = self._api_calls.get(service, 0) + count

    def record_phase_duration(self, phase: str, seconds: float) -> None:
        """Record how long a phase took (rounded to 1 decimal)."""
        self._phase_durations[phase] = round(seconds, 1)

    def increment(self, counter: str, amount: int = 1) -> None:
        """Increment a named counter.

        Raises ValueError for unknown counter names.
        """
        if counter not in _VALID_COUNTERS:
            msg = f"Unknown counter: {counter}"
            raise ValueError(msg)
        self._counters[counter] += amount

    def merge(self, other: ResourceAccumulator) -> None:
        """Merge another accumulator into this one (for parallel fan-out)."""
        for source in other._sources:
            self.add_source(source)
        for service, count in other._api_calls.items():
            self._api_calls[service] = self._api_calls.get(service, 0) + count
        for counter, value in other._counters.items():
            self._counters[counter] += value
        for phase, duration in other._phase_durations.items():
            existing = self._phase_durations.get(phase, 0.0)
            self._phase_durations[phase] = max(existing, duration)

    def to_dict(self) -> dict:
        """Return a clean serializable dictionary of accumulated metrics."""
        return {
            "data_sources_queried": list(self._sources),
            "api_calls": dict(self._api_calls),
            "phase_durations": dict(self._phase_durations),
            **self._counters,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ResourceAccumulator:
        """Reconstruct an accumulator from a serialized dict."""
        acc = cls()
        for source in data.get("data_sources_queried", []):
            acc.add_source(source)
        for service, count in data.get("api_calls", {}).items():
            acc.add_api_call(service, count=count)
        for phase, duration in data.get("phase_durations", {}).items():
            acc.record_phase_duration(phase, duration)
        for counter in _VALID_COUNTERS:
            value = data.get(counter, 0)
            if value:
                acc.increment(counter, value)
        return acc

    def estimate_cost_pence(self) -> float:
        """Estimate the platform cost of this run in pence (GBP).

        Uses the indicative unit costs from ``RESOURCE_UNIT_COSTS_PENCE``.
        """
        from treesight.constants import RESOURCE_UNIT_COSTS_PENCE

        total = 0.0
        for counter, value in self._counters.items():
            unit_cost = RESOURCE_UNIT_COSTS_PENCE.get(counter, 0.0)
            total += value * unit_cost
        total_api_calls = sum(self._api_calls.values())
        total += total_api_calls * RESOURCE_UNIT_COSTS_PENCE.get("api_call", 0.0)
        return round(total, 2)
