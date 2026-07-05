"""Simple on-disk cache for search/read operations."""

from __future__ import annotations

import hashlib
import json
import os
import time

from .config import CACHE_DIR, CACHE_TTL_SECONDS


def _cache_dir() -> str:
    """Return cache directory, creating it if necessary."""
    directory = CACHE_DIR or os.path.expanduser("~/.cache/web-research")
    os.makedirs(directory, exist_ok=True)
    return directory


def _cache_key(prefix: str, params: dict) -> str:
    """Deterministic cache key from parameters."""
    payload = json.dumps(params, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}.json"


def get(prefix: str, params: dict) -> dict | None:
    """Return cached value if present and not expired."""
    path = os.path.join(_cache_dir(), _cache_key(prefix, params))
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        if time.time() - entry.get("ts", 0) > CACHE_TTL_SECONDS:
            os.remove(path)
            return None
        return entry.get("data")
    except (OSError, json.JSONDecodeError):
        return None


def set(prefix: str, params: dict, data: dict) -> None:
    """Store value in cache."""
    path = os.path.join(_cache_dir(), _cache_key(prefix, params))
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "data": data}, f)
    except OSError:
        pass
