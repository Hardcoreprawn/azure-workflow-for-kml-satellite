"""In-memory per-IP rate limiter for API endpoints.

Uses a sliding-window counter. Suitable for single-instance deployments
(Azure Functions on Container Apps). For multi-instance, swap to a
Redis/Table Storage backed store.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Thread-safe sliding-window rate limiter keyed by arbitrary string (e.g. IP)."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """Return True if the request is within the rate limit, False otherwise."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            timestamps = self._hits.get(key, [])
            # Prune expired entries
            timestamps = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self._max:
                self._hits[key] = timestamps
                return False
            timestamps.append(now)
            self._hits[key] = timestamps
            return True

    def reset(self) -> None:
        """Clear all rate limit state (for testing)."""
        with self._lock:
            self._hits.clear()


# Pre-configured limiters for different endpoint tiers
# Form submission endpoints: 5 requests per 60 seconds per IP
form_limiter = RateLimiter(max_requests=5, window_seconds=60)

# Pipeline status polling: 30 requests per 60 seconds per IP
pipeline_limiter = RateLimiter(max_requests=30, window_seconds=60)

# CORS proxy: 60 requests per 60 seconds per IP
proxy_limiter = RateLimiter(max_requests=60, window_seconds=60)


def get_client_ip(req) -> str:
    """Extract client IP from Azure Functions request headers.

    Prefers Azure-specific headers, then uses the rightmost
    X-Forwarded-For entry (set by the last trusted proxy) to
    resist header spoofing.
    """
    # Azure-specific header (set by SWA / Container Apps)
    azure_ip = req.headers.get("X-Azure-ClientIP", "")
    if azure_ip:
        return azure_ip.strip()

    forwarded = req.headers.get("X-Forwarded-For", "")
    if forwarded:
        # Rightmost entry is set by the last trusted proxy (Azure
        # Container Apps / SWA append the real client IP as the final
        # entry).  This resists spoofing by ignoring client-supplied
        # entries earlier in the chain.
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]

    return (req.headers.get("X-Real-IP") or "unknown").strip()
