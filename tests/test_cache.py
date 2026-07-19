"""Tests for cache roundtrip, variants, and TTL. Extracted from the former monolithic test_web_research.py."""
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


class CacheTests(unittest.TestCase):
    """P2: cache roundtrip."""

    def setUp(self):
        _clear_cache()

    def test_cache_roundtrip(self):
        import web_research.shared.cache as cache

        cache.set("test", {"k": "v"}, {"data": [1, 2]})
        got = cache.get("test", {"k": "v"})
        self.assertEqual(got, {"data": [1, 2]})

    def test_cache_miss_returns_none(self):
        import web_research.shared.cache as cache

        self.assertIsNone(cache.get("test", {"missing": True}))



class CacheVariantTests(unittest.TestCase):
    """Options that alter fetched/ranked artifacts must not share cache entries."""

    def setUp(self):
        _clear_cache()

    def tearDown(self):
        _clear_cache()
        _config.reload_settings()

    @patch("web_research.features.search.command.rerank_results")
    @patch("web_research.features.search.command.search_backends")
    def test_search_cache_separates_rerank_mode(self, search_backends, rerank_results):
        search_backends.return_value = [
            {"title": "T", "url": "https://x", "content": "c", "source": "test"}
        ]
        rerank_results.side_effect = lambda _query, results: results

        with redirect_stdout(io.StringIO()):
            self.assertEqual(wr.main(["search", "cache-key", "--rerank"]), 0)
            self.assertEqual(wr.main(["search", "cache-key"]), 0)

        self.assertEqual(search_backends.call_count, 2)

    @patch("web_research.features.read.command.read_with_fallback")
    def test_read_cache_separates_robots_policy(self, read_with_fallback):
        read_with_fallback.side_effect = lambda _url, **kwargs: (
            "bypassed" if not kwargs["respect_robots"] else "respecting"
        )

        with redirect_stdout(io.StringIO()):
            self.assertEqual(wr.main(["read", "https://example.com", "--no-robots"]), 0)
            self.assertEqual(wr.main(["read", "https://example.com"]), 0)

        self.assertEqual(read_with_fallback.call_count, 2)

    @patch("web_research.features.read.command.read_with_fallback")
    def test_read_cache_separates_zai_timeout(self, read_with_fallback):
        read_with_fallback.side_effect = lambda _url, **kwargs: f"timeout={kwargs['zai_timeout']}"

        with redirect_stdout(io.StringIO()):
            self.assertEqual(wr.main(["read", "https://example.com", "--zai-timeout", "20"]), 0)
            self.assertEqual(wr.main(["read", "https://example.com", "--zai-timeout", "60"]), 0)

        self.assertEqual(read_with_fallback.call_count, 2)



class CacheTTLTests(unittest.TestCase):
    """Cache TTL expiry behavior."""

    def setUp(self):
        _clear_cache()

    def test_expired_entry_returns_none(self):
        import time

        import web_research.shared.cache as cache

        cache.set("ttl", {"k": "v"}, {"data": "old"})
        # Manually backdate the cache file
        cache_dir = Path(_config.CACHE_DIR or Path.home() / ".cache" / "web-research")
        files = list(cache_dir.glob("ttl_*.json"))
        self.assertEqual(len(files), 1)
        import json as _json

        entry = _json.loads(files[0].read_text())
        entry["ts"] = time.time() - _config.CACHE_TTL_SECONDS - 10
        files[0].write_text(_json.dumps(entry))
        with patch("web_research.shared.cache.os.utime") as touch:
            self.assertIsNone(cache.get("ttl", {"k": "v"}))
        touch.assert_not_called()

