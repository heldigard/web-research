"""Tests for scrape backends, fallback, and scrape caching. Extracted from the former monolithic test_web_research.py."""

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


class ScrapeTests(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    @patch("urllib.request.urlopen")
    def test_firecrawl_scrape(self, mock_open):
        mock_open.side_effect = _mock_urlopen(
            {
                "http://localhost:3002/v1/scrape": {
                    "success": True,
                    "data": {"markdown": "# Hello\n\nWorld."},
                }
            }
        )
        md = wr.firecrawl_scrape("https://example.com")
        self.assertIn("Hello", md)


class FallbackTests(unittest.TestCase):
    """scrape_with_fallback: Firecrawl down -> Z.AI reader."""

    @patch("urllib.request.urlopen")
    def test_scrape_with_fallback_uses_zai(self, mock_open):
        mock_open.side_effect = _mock_urlopen(
            {
                "https://api.z.ai/api/paas/v4/reader": {
                    "reader_result": {
                        "title": "Z",
                        "content": "zai body",
                        "url": "https://example.com",
                    }
                }
            }
        )
        with patch.object(wr.reader, "ZAI_API_KEY", "sk-test"):
            # Firecrawl will fail (unmocked URL), Z.AI should succeed
            md = wr.scrape_with_fallback("https://example.com")
        self.assertIn("zai body", md)

    def test_scrape_with_fallback_no_keys_returns_empty(self):
        with patch.object(wr.reader, "ZAI_API_KEY", ""):
            with patch("urllib.request.urlopen", side_effect=Exception("down")):
                md = wr.scrape_with_fallback("https://example.com")
        self.assertEqual(md, "")


class ResearchScrapeCacheTests(unittest.TestCase):
    """``_scrape_cached`` caches research's most expensive phase (scrape)."""

    def setUp(self) -> None:
        _clear_cache()

    @patch("web_research.features.research.command.scrape_with_fallback")
    def test_second_call_hits_cache(self, mock_scrape):
        from web_research.features.research.command import _scrape_cached

        mock_scrape.return_value = "evidence markdown"
        first = _scrape_cached("https://x.test/a", respect_robots=False, no_cache=False)
        second = _scrape_cached("https://x.test/a", respect_robots=False, no_cache=False)
        self.assertEqual(first, "evidence markdown")
        self.assertEqual(second, "evidence markdown")  # served from cache
        self.assertEqual(mock_scrape.call_count, 1)  # only the miss hit the network

    @patch("web_research.features.research.command.scrape_with_fallback")
    def test_no_cache_bypasses_read_and_write(self, mock_scrape):
        from web_research.features.research.command import _scrape_cached

        mock_scrape.return_value = "evidence markdown"
        _scrape_cached("https://x.test/b", respect_robots=False, no_cache=True)
        _scrape_cached("https://x.test/b", respect_robots=False, no_cache=True)
        self.assertEqual(mock_scrape.call_count, 2)  # no caching at all

    @patch("web_research.features.research.command.scrape_with_fallback")
    def test_empty_result_not_cached(self, mock_scrape):
        from web_research.features.research.command import _scrape_cached

        mock_scrape.return_value = ""
        _scrape_cached("https://x.test/c", respect_robots=False, no_cache=False)
        _scrape_cached("https://x.test/c", respect_robots=False, no_cache=False)
        self.assertEqual(mock_scrape.call_count, 2)  # empty not cached -> retried

    @patch("web_research.features.research.command.scrape_with_fallback")
    def test_cache_separates_robots_policy(self, mock_scrape):
        from web_research.features.research.command import _scrape_cached

        mock_scrape.side_effect = lambda url, respect_robots=False: (
            "robots-enforced" if respect_robots else "robots-bypassed"
        )
        enforced = _scrape_cached("https://x.test/d", respect_robots=True, no_cache=False)
        bypassed = _scrape_cached("https://x.test/d", respect_robots=False, no_cache=False)
        self.assertEqual(enforced, "robots-enforced")
        self.assertEqual(bypassed, "robots-bypassed")
        self.assertEqual(mock_scrape.call_count, 2)  # distinct cache keys


if __name__ == "__main__":
    unittest.main()
