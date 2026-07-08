"""HTTP client port + stdlib implementation.

Defines the ``HttpClient`` protocol every backend depends on, the default
``UrllibHttpClient`` (stdlib-only, CLI-agnostic), and a module-level
``default_client`` singleton that backends resolve at call time.

The protocol surface is intentionally minimal (``get_json`` / ``post_json``
/ ``get_bytes``). The default ``UrllibHttpClient`` is wired as the module
singleton; a future ``httpx`` swap is one new ``HttpClient`` class + editing
the ``_client`` assignment (or reintroducing a setter then).
"""

# vs-soft-allow  — HTTP method signatures (Protocol + impl pair) are cohesive
# interface declarations; the (url, payload, timeout, headers) shape is fixed
# by HTTP semantics, not parameter sprawl. Wrapping in an ``HttpRequest`` DTO
# would force every backend through a 30-line adapter for zero readability gain.

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

from . import config

_USER_AGENT = "web-research/0.1 (+https://github.com/heldigard/web-research)"


def _backoff_seconds(attempt: int, base: float, cap: float = 10.0) -> float:
    """Exponential backoff: ``base * 2**attempt`` capped at ``cap`` seconds."""
    if base <= 0:
        return 0.0
    return min(cap, base * (2**attempt))


def _retry_after_seconds(err: urllib.error.HTTPError, cap: float = 30.0) -> float | None:
    """Parse a ``Retry-After`` header (seconds form only) to a wait in seconds.

    Returns ``None`` when absent or unparseable. HTTP-date form is intentionally
    not converted (no tz-safe parser in stdlib); only integer-second values are
    honored. Capped so a hostile header can't stall the engine.
    """
    headers = getattr(err, "headers", None)
    raw = headers.get("Retry-After") if headers else None
    if not raw:
        return None
    try:
        return min(cap, float(raw))
    except (TypeError, ValueError):
        return None


class HttpClient(Protocol):
    """Minimal HTTP port used by every backend.

    Backends receive a client (or read ``default_client()`` at call time) so
    tests can inject a fake without monkey-patching ``urllib.request``.
    """

    def get_json(
        self, url: str, *, timeout: float | None = None, headers: dict | None = None
    ) -> dict: ...

    def post_json(
        self,
        url: str,
        payload: dict,
        *,
        timeout: float | None = None,
        headers: dict | None = None,
    ) -> dict: ...

    def get_bytes(
        self, url: str, *, timeout: float | None = None, headers: dict | None = None
    ) -> bytes: ...


class UrllibHttpClient:
    """Stdlib HTTP client. Zero external deps; respects ``config.TIMEOUT``."""

    def __init__(self, user_agent: str = _USER_AGENT) -> None:
        self._ua = user_agent

    def _request(
        self,
        url: str,
        data: bytes | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
    ) -> bytes:
        effective_timeout = config.TIMEOUT if timeout is None else timeout
        h = {"User-Agent": self._ua}
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, data=data, headers=h)
        # nosemgrep: dynamic-urllib-use-detected — URLs come from CLI args
        # (user-supplied) or from backend response JSON (already-validated
        # upstream at the SearXNG/Z.AI boundary). Internal code never
        # constructs URLs from untrusted string concat.
        settings = config.get_settings()
        max_retries = max(0, settings.http_max_retries)
        base = max(0.0, settings.http_backoff_base)
        for attempt in range(max_retries + 1):
            wait = _backoff_seconds(attempt, base)
            try:
                with urllib.request.urlopen(req, timeout=effective_timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as e:
                # Retry only rate-limit + server-side errors; 4xx (except 429)
                # is a caller bug and must surface immediately.
                retryable = e.code == 429 or 500 <= e.code < 600
                if not retryable or attempt == max_retries:
                    raise
                # Honor Retry-After on 429/503 when the server sends it; cap so
                # a hostile header can't stall the engine for minutes.
                ra = _retry_after_seconds(e)
                if ra is not None:
                    wait = ra
            except urllib.error.URLError:
                # Connection reset / timeout / DNS hiccup — all worth a retry.
                if attempt == max_retries:
                    raise
            # Back off before the next attempt. No jitter: deterministic for
            # tests; production spread comes from per-host timing anyway.
            time.sleep(wait)
        # Unreachable: every terminal path raises above. A fall-through here
        # would be a logic bug (e.g. max_retries configured negative), so
        # surface it explicitly rather than raising a possibly-None exception.
        raise RuntimeError("retry loop exited without result or exception")  # pragma: no cover

    def get_json(
        self, url: str, *, timeout: float | None = None, headers: dict | None = None
    ) -> dict:
        merged = {"Accept": "application/json"}
        if headers:
            merged.update(headers)
        return json.loads(self.get_bytes(url, timeout=timeout, headers=merged))

    def post_json(
        self,
        url: str,
        payload: dict,
        *,
        timeout: float | None = None,
        headers: dict | None = None,
    ) -> dict:
        merged = {"Content-Type": "application/json"}
        if headers:
            merged.update(headers)
        body = json.dumps(payload).encode("utf-8")
        return json.loads(self._request(url, data=body, headers=merged, timeout=timeout))

    def get_bytes(
        self, url: str, *, timeout: float | None = None, headers: dict | None = None
    ) -> bytes:
        return self._request(url, headers=headers, timeout=timeout)


_client: HttpClient = UrllibHttpClient()


def default_client() -> HttpClient:
    """Return the process-wide default client (module singleton)."""
    return _client


# -- Logging helpers (unchanged surface, port-injected clients don't touch these) ----


def warn(tag: str, msg: str) -> None:
    """Emit a backend error line to stderr (always shown)."""
    print(f"[{tag}] {msg}", file=sys.stderr)


def debug(tag: str, msg: str) -> None:
    """Emit a diagnostic line to stderr only when verbose mode is on."""
    if config.VERBOSE:
        print(f"[{tag}] {msg}", file=sys.stderr)


# Legacy underscored aliases — kept so existing call sites
# (``from .http import _warn, _debug``) keep working.
_warn = warn
_debug = debug

# Public alias for ``urllib.parse.urlencode`` — backends import this
# rather than reach into stdlib directly (consistent with HttpClient usage).
urlencode = urllib.parse.urlencode
