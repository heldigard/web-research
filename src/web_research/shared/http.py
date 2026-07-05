"""Minimal HTTP helpers (stdlib only, CLI-agnostic)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from . import config


def _warn(tag: str, msg: str) -> None:
    """Emit a backend error line to stderr (always shown)."""
    print(f"[{tag}] {msg}", file=sys.stderr)


def _debug(tag: str, msg: str) -> None:
    """Emit a diagnostic line to stderr only when verbose mode is on."""
    if config.VERBOSE:
        print(f"[{tag}] {msg}", file=sys.stderr)


def _http(
    url: str,
    data: bytes | None = None,
    headers: dict | None = None,
    timeout: float | None = None,
) -> bytes:
    """Fetch bytes from a URL."""
    if timeout is None:
        timeout = config.TIMEOUT
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _post_json(
    url: str,
    payload: dict,
    headers: dict | None = None,
    timeout: float | None = None,
) -> dict:
    """POST JSON and return parsed JSON."""
    body = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    return json.loads(_http(url, data=body, headers=h, timeout=timeout))


def _get_json(url: str, timeout: float | None = None) -> dict:
    """GET JSON and return parsed JSON."""
    return json.loads(_http(url, headers={"Accept": "application/json"}, timeout=timeout))


def _encode_query(params: dict[str, str]) -> str:
    """URL-encode query parameters."""
    return urllib.parse.urlencode(params)
