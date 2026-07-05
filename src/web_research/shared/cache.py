"""Versioned on-disk cache for search/read operations.

Cache entries are stamped with ``SCHEMA_VERSION`` (from ``config``). Bumping
the version invalidates every prior entry automatically — no orphaning of
old responses when the engine changes shape, prompt templates, or model
identifiers.

Optional engine-version stamping: callers can pass an ``engine_tag`` (e.g.
the synthesis model name) so changing the tag forces a cache miss without
needing a full schema bump.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

from . import config
from .config import SCHEMA_VERSION, get_settings

_DEFAULT_CACHE_HOME = "~/.cache/web-research"


def _cache_dir() -> str:
    """Return cache directory, creating it if necessary."""
    directory = config.CACHE_DIR or os.path.expanduser(_DEFAULT_CACHE_HOME)
    os.makedirs(directory, exist_ok=True)
    return directory


def _cache_key(prefix: str, params: dict, engine_tag: str | None = None) -> str:
    """Deterministic cache key. Includes schema + engine version stamps."""
    envelope = {
        "schema": SCHEMA_VERSION,
        "tag": engine_tag or "",
        "params": params,
    }
    payload = json.dumps(envelope, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}.json"


def get(prefix: str, params: dict, engine_tag: str | None = None) -> dict[str, Any] | None:
    """Return cached value if present, schema-valid, and not expired.

    Entries whose ``schema`` field does not match the current
    ``SCHEMA_VERSION`` are deleted on read and treated as a miss.
    """
    path = os.path.join(_cache_dir(), _cache_key(prefix, params, engine_tag))
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    if entry.get("schema") != SCHEMA_VERSION:
        try:
            os.remove(path)
        except OSError:
            pass
        return None

    if time.time() - entry.get("ts", 0) > get_settings().cache_ttl_seconds:
        try:
            os.remove(path)
        except OSError:
            pass
        return None

    return entry.get("data")


def set(prefix: str, params: dict, data: dict[str, Any], engine_tag: str | None = None) -> None:
    """Store value in cache. Stamped with current schema + engine tag."""
    path = os.path.join(_cache_dir(), _cache_key(prefix, params, engine_tag))
    entry = {
        "schema": SCHEMA_VERSION,
        "ts": time.time(),
        "tag": engine_tag or "",
        "data": data,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f)
    except OSError:
        pass


def clear() -> None:
    """Erase the entire cache directory. Used by tests."""
    import shutil

    directory = config.CACHE_DIR or os.path.expanduser(_DEFAULT_CACHE_HOME)
    if os.path.isdir(directory):
        shutil.rmtree(directory, ignore_errors=True)
