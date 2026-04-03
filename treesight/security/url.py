"""Safe URL host matching utilities.

Centralises hostname comparison logic to avoid scattered substring checks
that tools like CodeQL flag as ``py/incomplete-url-substring-sanitization``.

All functions operate on **parsed** hostnames (lowercase, no port, no path)
obtained via ``urllib.parse.urlparse``.  They never use bare ``in`` on a
raw URL string.
"""

from __future__ import annotations

from urllib.parse import urlparse


def host_matches(hostname: str, target: str) -> bool:
    """Return True if *hostname* equals *target* or is a subdomain of it.

    Both values are compared case-insensitively.  The subdomain check uses
    a leading-dot test so that ``evil-target.com`` does **not** match
    ``target.com``.

    >>> host_matches("cdn.example.com", "example.com")
    True
    >>> host_matches("example.com", "example.com")
    True
    >>> host_matches("evil-example.com", "example.com")
    False
    >>> host_matches("", "example.com")
    False
    """
    h = hostname.lower()
    t = target.lower()
    if not h:
        return False
    return h == t or h.endswith(f".{t}")


def parse_host(url_or_token: str) -> str:
    """Extract the lowercase hostname from a URL or CSP source token.

    If *url_or_token* has no scheme (common for CSP directives like
    ``*.example.com``), ``urlparse`` puts everything in the *path*
    component.  In that case, fall back to the raw token stripped and
    lowercased.

    Returns the empty string for values that cannot be parsed.

    >>> parse_host("https://cdn.example.com/path")
    'cdn.example.com'
    >>> parse_host("*.example.com")
    '*.example.com'
    >>> parse_host("'self'")
    "'self'"
    """
    parsed = urlparse(url_or_token)
    return (parsed.hostname or url_or_token.strip()).lower()


def host_in_allowlist(hostname: str, allowed: frozenset[str]) -> bool:
    """Return True if *hostname* matches any entry in *allowed* (exact or subdomain).

    Instead of looping over every allowlist entry with ``host_matches``,
    this walks up the domain hierarchy and does **O(depth)** set lookups
    (where depth is the number of dot-separated labels, typically 2–4).

    >>> allowed = frozenset({"example.com", "other.org"})
    >>> host_in_allowlist("cdn.example.com", allowed)
    True
    >>> host_in_allowlist("example.com", allowed)
    True
    >>> host_in_allowlist("evil-example.com", allowed)
    False
    >>> host_in_allowlist("", allowed)
    False
    """
    h = hostname.lower()
    if not h:
        return False
    if h in allowed:
        return True
    parts = h.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[i:])
        if parent in allowed:
            return True
    return False


def csp_token_matches_host(token: str, host: str) -> bool:
    """Check whether a CSP source-list token matches *host*.

    Handles scheme-prefixed URLs (``https://cdn.example.com``) and bare
    host tokens (``cdn.example.com``) that appear in Content-Security-Policy
    directives.

    >>> csp_token_matches_host("https://cdn.example.com", "example.com")
    True
    >>> csp_token_matches_host("cdn.example.com", "cdn.example.com")
    True
    >>> csp_token_matches_host("'self'", "example.com")
    False
    """
    return host_matches(parse_host(token), host)
