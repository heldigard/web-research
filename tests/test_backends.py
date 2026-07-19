"""Tests for backend slice building and settings. Extracted from the former monolithic test_web_research.py."""
from __future__ import annotations

import io  # noqa: F401
import json  # noqa: F401
import os  # noqa: F401
import unittest
import urllib.error  # noqa: F401
from argparse import Namespace  # noqa: F401
from contextlib import redirect_stdout  # noqa: F401
from pathlib import Path  # noqa: F401
from unittest.mock import patch  # noqa: F401

import web_research as wr  # noqa: F401
import web_research.shared.config as _config  # noqa: F401
from web_research.cli_parser import build_parser  # noqa: F401

from ._helpers import (  # noqa: F401
    FakeResponse,
    _cache_file_count,
    _clear_cache,
    _FakeHttpClient,
    _mock_urlopen,
    _noop_handler,
    _ollama_tags,
)


class BackendSliceTests(unittest.TestCase):
    """End-to-end coverage for the new per-backend file layout.

    Asserts the dispatcher wires SearXNG / MiniMax / Z.AI backends through
    the new ``backends/`` package without HTTP. Also exercises
    :func:`build_backend` so adding a new engine fails fast at import time.
    """

    def setUp(self):
        _clear_cache()

    def test_build_backend_returns_classes(self):
        from web_research.features.search.backends import (
            MinimaxBackend,
            SearXNGBackend,
            ZaiBackend,
            build_backend,
        )

        assert isinstance(build_backend("searxng"), SearXNGBackend)
        assert isinstance(build_backend("minimax"), MinimaxBackend)
        assert isinstance(build_backend("zai"), ZaiBackend)
        assert build_backend("bogus") is None

    def test_canonical_url_dedup_via_backends(self):
        """``normalize_url`` strips tracking params + fragment so the
        dispatcher collapses identical pages served via different utm_* tags."""
        from web_research.features.search.backends import normalize_url, tracking_params

        u1 = "https://example.com/p?utm_source=x&id=1"
        u2 = "https://EXAMPLE.com/p/?id=1#frag"
        canon = normalize_url(u1, tracking_params())
        assert canon == normalize_url(u2, tracking_params())

    def test_search_result_to_dict_shape(self):
        """Dataclass projection matches the legacy dict shape consumed by
        formatters (``title`` / ``url`` / ``content`` / ``engine`` / ``source``
        / ``publishedDate``)."""
        from web_research.features.search.backends import SearchResult

        r = SearchResult(
            title="T",
            url="https://e.com",
            content="c",
            engine="searxng",
            source="searxng",
            published_date="2026-01-01",
        ).to_dict()
        assert r == {
            "title": "T",
            "url": "https://e.com",
            "content": "c",
            "engine": "searxng",
            "source": "searxng",
            "publishedDate": "2026-01-01",
        }

    def test_read_build_reader_returns_classes(self):
        from web_research.features.read.backends import (
            FirecrawlReader,
            ZaiReader,
            build_reader,
        )

        assert isinstance(build_reader("firecrawl"), FirecrawlReader)
        assert isinstance(build_reader("zai"), ZaiReader)
        assert build_reader("bogus") is None

    def test_settings_load_round_trip(self):
        """Typed Settings survives a reload + roundtrip; legacy SCREAMING_CASE
        proxy reads from the singleton."""
        from web_research.shared import config
        from web_research.shared.config import get_settings, reload_settings

        reload_settings(timeout=99)
        assert get_settings().timeout == 99
        assert config.TIMEOUT == 99  # legacy alias
        reload_settings()  # restore env-derived default

    def test_cache_invalidation_on_schema_bump(self):
        """Cache entries stamped with prior ``SCHEMA_VERSION`` are invalidated
        automatically when the version is bumped."""
        from web_research.shared import cache
        from web_research.shared.config import SCHEMA_VERSION

        cache.set("probe", {"k": 1}, {"v": "first"}, engine_tag="t1")
        assert cache.get("probe", {"k": 1}, engine_tag="t1") == {"v": "first"}

        # Simulate a schema bump by rewriting the constant and re-checking.
        original = SCHEMA_VERSION
        try:
            cache.SCHEMA_VERSION = original + 1  # type: ignore[attr-defined]
            assert cache.get("probe", {"k": 1}, engine_tag="t1") is None
        finally:
            cache.SCHEMA_VERSION = original  # type: ignore[attr-defined]

