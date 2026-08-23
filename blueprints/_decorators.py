"""Composable HTTP route decorators for Azure Functions blueprints.

These decorators centralise cross-cutting concerns that previously were
copy-pasted into every route handler:

    - CORS preflight       →  handled by ``require_auth`` (from _helpers)
    - Authentication gate  →  handled by ``require_auth`` (from _helpers)
    - Rate limiting        →  ``rate_limit(limiter)``
    - Body size validation →  ``validate_body_size(max_bytes)``
    - All-in-one           →  ``authenticated_http_route(...)``

Stacking order (outermost to innermost, nearest to the ``@bp.route`` line):

    @bp.route(...)
    @authenticated_http_route(rate_limiter=..., max_body_bytes=...)
    def my_handler(req, *, user_id, auth_claims):
        ...

Or composable:

    @bp.route(...)
    @require_auth
    @rate_limit(limiter)
    @validate_body_size(32_768)
    def my_handler(req, *, user_id, auth_claims):
        ...

``rate_limit`` and ``validate_body_size`` pass all keyword arguments (including
``user_id`` and ``auth_claims`` injected by ``require_auth``) straight through
to the wrapped function, so they can be placed inside ``@require_auth`` without
any changes to the handler signature.

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
The Azure Functions worker inspects function signatures at import time and
``from __future__ import annotations`` turns all annotations into strings,
which breaks binding resolution.
"""

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

import azure.functions as func

from blueprints._helpers import error_response, require_auth

logger = logging.getLogger(__name__)


def rate_limit(limiter: Any) -> Callable:
    """Decorator factory: return 429 if *limiter* rejects the request.

    Place *inside* (below) ``@require_auth`` so the rate-limit check runs
    after the caller has already been authenticated::

        @require_auth
        @rate_limit(get_pipeline_limiter())
        def handler(req, *, user_id, auth_claims): ...

    All keyword arguments (e.g. ``user_id``, ``auth_claims``) are forwarded
    transparently to the wrapped function.
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(req: func.HttpRequest, **kwargs: Any) -> func.HttpResponse:
            from treesight.security.rate_limit import get_client_ip

            if not limiter.is_allowed(get_client_ip(req)):
                return error_response(
                    429,
                    "Too many requests \u2014 please wait before trying again",
                    req=req,
                )
            return fn(req, **kwargs)

        return wrapper

    return decorator


def validate_body_size(max_bytes: int) -> Callable:
    """Decorator factory: return 400 if the request body exceeds *max_bytes*.

    Place *inside* (below) ``@require_auth`` and optionally ``@rate_limit``::

        @require_auth
        @rate_limit(limiter)
        @validate_body_size(32_768)
        def handler(req, *, user_id, auth_claims): ...

    All keyword arguments are forwarded transparently.
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(req: func.HttpRequest, **kwargs: Any) -> func.HttpResponse:
            if len(req.get_body()) > max_bytes:
                return error_response(
                    400,
                    f"Request body too large (max {max_bytes} bytes)",
                    req=req,
                )
            return fn(req, **kwargs)

        return wrapper

    return decorator


def authenticated_http_route(
    *,
    rate_limiter: Any = None,
    max_body_bytes: int | None = None,
) -> Callable:
    """Unified decorator combining CORS, auth, optional rate-limit, and body-size.

    Equivalent to stacking (outermost first)::

        @require_auth
        [@rate_limit(rate_limiter)]          # only when rate_limiter is not None
        [@validate_body_size(max_body_bytes)] # only when max_body_bytes is not None

    On success the handler receives ``user_id`` and ``auth_claims`` as keyword
    arguments (the same contract as ``@require_auth``).

    Example::

        @bp.route(...)
        @authenticated_http_route(
            rate_limiter=get_pipeline_limiter(),
            max_body_bytes=32_768,
        )
        def my_handler(req, *, user_id, auth_claims):
            ...
    """

    def decorator(fn: Callable) -> Callable:
        wrapped: Callable = fn
        if max_body_bytes is not None:
            wrapped = validate_body_size(max_body_bytes)(wrapped)
        if rate_limiter is not None:
            wrapped = rate_limit(rate_limiter)(wrapped)
        # require_auth handles OPTIONS/CORS + auth and deletes __wrapped__
        # to hide injected parameters from the Azure Functions worker.
        wrapped = require_auth(wrapped)
        # Restore the original function's identity so Azure Functions can
        # resolve the route binding by function name.
        wrapped.__name__ = fn.__name__
        wrapped.__module__ = fn.__module__
        return wrapped

    return decorator
