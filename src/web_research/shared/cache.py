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
import tempfile
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
    """Atomically store a schema-stamped value without exposing partial JSON."""
    directory = _cache_dir()
    path = os.path.join(directory, _cache_key(prefix, params, engine_tag))
    entry = {
        "schema": SCHEMA_VERSION,
        "ts": time.time(),
        "tag": engine_tag or "",
        "data": data,
    }
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            temp_path = f.name
            json.dump(entry, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        temp_path = None
    except (OSError, TypeError, ValueError):
        pass
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
    _evict_if_needed()


def _evict_if_needed() -> None:
    """Drop oldest cache files until both entry-count and byte budgets hold.

    Runs after every write so the cache directory never grows unbounded
    (the old implementation only expired individual entries on read). LRU by
    file mtime; non-``.json`` files are left alone. A limit of 0 means
    "no limit" for that axis.
    """
    settings = get_settings()
    max_entries = settings.cache_max_entries
    max_bytes = settings.cache_max_bytes
    if max_entries <= 0 and max_bytes <= 0:
        return
    entries, total = _collect_cache_entries(_cache_dir())
    if len(entries) <= max(max_entries, 1) and (max_bytes <= 0 or total <= max_bytes):
        return
    # Oldest first (lowest mtime) — that is the LRU victim order.
    entries.sort(key=lambda item: item[1])
    count = len(entries)
    running_total = total
    for path, _mtime, size in entries:
        if count <= max(max_entries, 1) and (max_bytes <= 0 or running_total <= max_bytes):
            break
        try:
            os.remove(path)
        except OSError:
            continue
        count -= 1
        running_total -= size


def _collect_cache_entries(directory: str) -> tuple[list[tuple[str, float, int]], int]:
    """Return ``(entries, total_bytes)`` for ``*.json`` files in ``directory``.

    Each entry is ``(path, mtime, size)``. Swallows OS errors per-file so a
    single unreadable entry never aborts the eviction sweep.
    """
    entries: list[tuple[str, float, int]] = []
    total = 0
    try:
        scan = list(os.scandir(directory))
    except OSError:
        return entries, total
    for e in scan:
        if not (e.is_file() and e.name.endswith(".json")):
            continue
        try:
            st = e.stat()
        except OSError:
            continue
        entries.append((e.path, st.st_mtime, st.st_size))
        total += st.st_size
    return entries, total


def clear() -> None:
    """Erase the entire cache directory. Used by tests."""
    import shutil

    directory = config.CACHE_DIR or os.path.expanduser(_DEFAULT_CACHE_HOME)
    if os.path.isdir(directory):
        shutil.rmtree(directory, ignore_errors=True)
