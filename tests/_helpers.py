"""Shared test doubles and cache helpers for web_research tests.

Extracted verbatim from the former monolithic test_web_research.py so every
feature-slice test module can import the same fakes and cache utilities.
"""
from __future__ import annotations

import io  # noqa: F401
import json  # noqa: F401
import os  # noqa: F401
import unittest  # noqa: F401
import urllib.error  # noqa: F401
from argparse import Namespace  # noqa: F401
from contextlib import redirect_stdout  # noqa: F401
from pathlib import Path  # noqa: F401
from unittest.mock import patch  # noqa: F401

import web_research.shared.config as _config  # noqa: F401


def _clear_cache() -> None:
    from shutil import rmtree

    cache_dir = Path(_config.CACHE_DIR or Path.home() / ".cache" / "web-research")
    if cache_dir.exists():
        rmtree(cache_dir)
    # Reset the is_alive() TTL cache so mock_alive patches don't bleed across tests.
    from web_research.shared.ollama_api import _bust_alive_cache

    _bust_alive_cache()



def _cache_file_count() -> int:
    """Number of JSON cache files currently on disk."""
    cache_dir = Path(_config.CACHE_DIR or Path.home() / ".cache" / "web-research")
    return len(list(cache_dir.glob("*.json"))) if cache_dir.exists() else 0



class FakeResponse:
    def __init__(self, body: bytes, code: int = 200):
        self._body = body
        self.code = code

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False



class _FakeHttpClient:
    """Minimal HttpClient double for status probes (no network)."""

    def __init__(self, routes: dict[str, bytes | dict], raise_on: tuple[str, ...] = ()):
        # routes: url-substring -> bytes (raw) or dict (json)
        self._routes = routes
        self._raise_on = raise_on

    def _resolve_bytes(self, url: str) -> bytes:
        for marker in self._raise_on:
            if marker in url:
                raise ConnectionError(f"refused: {url}")
        for prefix, body in self._routes.items():
            if url.startswith(prefix):
                return body if isinstance(body, bytes) else json.dumps(body).encode()
        raise ConnectionError(f"unmocked url: {url}")

    def get_bytes(self, url, *, timeout=None, headers=None):
        return self._resolve_bytes(url)

    def get_json(self, url, *, timeout=None, headers=None):
        return json.loads(self._resolve_bytes(url))

    def post_json(self, url, payload, *, timeout=None, headers=None):
        return json.loads(self._resolve_bytes(url))



def _mock_urlopen(response_map: dict):
    def side_effect(req, **_kwargs):
        url = req.full_url
        for prefix, body in response_map.items():
            if url.startswith(prefix):
                return FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode())
        raise Exception(f"unmocked url: {url}")

    return side_effect



def _noop_handler(_args):
    return 0



def _ollama_tags(names: list[str]) -> dict:
    return {"models": [{"name": n, "size": 1000} for n in names]}

