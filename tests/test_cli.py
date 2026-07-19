"""Tests for CLI commands and config flags. Extracted from the former monolithic test_web_research.py."""

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


class CLITests(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    @patch("urllib.request.urlopen")
    @patch("ollama_client.is_alive")
    def test_cli_search_json(self, mock_alive, mock_open):
        mock_alive.return_value = False
        mock_open.side_effect = _mock_urlopen(
            {
                "http://localhost:8080/search": {
                    "results": [{"title": "Python", "url": "https://py", "content": "cool"}]
                }
            }
        )
        f = io.StringIO()
        with redirect_stdout(f):
            rc = wr.main(["search", "python", "-n", "2", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(f.getvalue())
        self.assertEqual(len(data), 1)

    @patch("ollama_client.is_alive", return_value=False)
    def test_cli_research_json_emits_provenance_envelope(self, _mock_client_alive):
        import web_research.features.research.command as research_cmd

        result = {
            "title": "Primary docs",
            "url": "https://docs.example.test/feature",
            "content": "search snippet",
            "engine": "searxng",
            "source": "docs.example.test",
            "publishedDate": "2026-07-08",
        }
        search_meta = {
            "engine_requested": "searxng",
            "engine_used": "searxng",
            "engines_tried": ["searxng"],
            "escalated": False,
        }
        with (
            patch.object(
                research_cmd, "search_with_escalation", return_value=([result], search_meta)
            ),
            patch.object(research_cmd, "scrape_with_fallback", return_value="scraped evidence"),
            patch.object(research_cmd, "synthesize", return_value="Grounded answer [1]."),
            patch.object(research_cmd, "is_alive", return_value=False),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = wr.main(["research", "feature", "--json", "--scrape", "1"])

        self.assertEqual(rc, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["cache_hit"])
        self.assertEqual(payload["scraping"]["requested"], 1)
        self.assertEqual(payload["scraping"]["succeeded"], 1)
        self.assertEqual(payload["pipeline"]["search"]["engine_used"], "searxng")
        self.assertEqual(payload["sources"][0]["engine"], "searxng")
        self.assertEqual(payload["sources"][0]["published_date"], "2026-07-08")
        self.assertEqual(payload["evidence"][0]["text"], "scraped evidence")
        self.assertEqual(payload["answer"], "Grounded answer [1].")
        self.assertIn("generated_at", payload)

    @patch("ollama_client.is_alive", return_value=False)
    def test_cli_research_json_keeps_search_evidence_when_scrape_is_zero(self, _mock_client_alive):
        import web_research.features.research.command as research_cmd

        result = {
            "title": "Search-only docs",
            "url": "https://docs.example.test/search-only",
            "content": "search evidence",
            "engine": "searxng",
            "source": "docs.example.test",
            "publishedDate": "",
        }
        search_meta = {
            "engine_requested": "searxng",
            "engine_used": "searxng",
            "engines_tried": ["searxng"],
            "escalated": False,
        }
        with (
            patch.object(
                research_cmd, "search_with_escalation", return_value=([result], search_meta)
            ),
            patch.object(research_cmd, "is_alive", return_value=False),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = wr.main(["research", "feature", "--json", "--scrape", "0"])

        payload = json.loads(output.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["scraping"]["requested"], 0)
        self.assertEqual(payload["scraping"]["succeeded"], 0)
        self.assertFalse(payload["sources"][0]["scraped"])
        self.assertEqual(payload["evidence"][0]["text"], "search evidence")

    @patch("urllib.request.urlopen")
    @patch("ollama_client.is_alive")
    def test_cli_json_strips_internal_keys(self, mock_alive, mock_open):
        """P1.1: --json must not leak _quality/_score/_v internal metadata."""
        mock_alive.return_value = False
        mock_open.side_effect = _mock_urlopen(
            {
                "http://localhost:8080/search": {
                    "results": [
                        {
                            "title": "T",
                            "url": "https://docs.python.org/x",
                            "content": "a" * 100,
                        }
                    ]
                }
            }
        )
        f = io.StringIO()
        with redirect_stdout(f):
            wr.main(["search", "q", "-n", "2", "--json", "--smart"])
        data = json.loads(f.getvalue())
        self.assertTrue(data)
        for r in data:
            self.assertNotIn("_quality", r)
            self.assertNotIn("_score", r)
            self.assertNotIn("_v", r)

    @patch("urllib.request.urlopen")
    @patch("ollama_client.is_alive")
    def test_cli_search_does_not_cache_empty_on_failure(self, mock_alive, mock_open):
        """P0.1: a failed (empty) search must not poison the cache.

        Exit code 1 signals no results to controllers (after free→paid cascade).
        """
        mock_alive.return_value = False
        mock_open.side_effect = urllib.error.URLError("searxng down")
        before = _cache_file_count()
        f = io.StringIO()
        with redirect_stdout(f):
            rc = wr.main(["search", "searxng-down-q", "-n", "3"])
        self.assertEqual(rc, 1)
        self.assertEqual(_cache_file_count(), before)

    @patch("urllib.request.urlopen")
    @patch("ollama_client.is_alive")
    def test_cli_cache_hit_returns_list(self, mock_alive, mock_open):
        """P1.2: cache hit must return the result LIST, not the wrapper dict.
        Guards the bug where `results = cached` (a dict) was assigned."""
        mock_alive.return_value = False
        mock_open.side_effect = _mock_urlopen(
            {
                "http://localhost:8080/search": {
                    "results": [{"title": "Cached", "url": "https://x", "content": "c"}]
                }
            }
        )
        f1 = io.StringIO()
        with redirect_stdout(f1):
            wr.main(["search", "cached-q", "-n", "2"])
        self.assertIn("Cached", f1.getvalue())
        # Second call: backend now down — must serve cache without crashing.
        mock_open.side_effect = urllib.error.URLError("down")
        f2 = io.StringIO()
        with redirect_stdout(f2):
            rc = wr.main(["search", "cached-q", "-n", "2"])
        self.assertEqual(rc, 0)
        self.assertIn("Cached", f2.getvalue())

    @patch("urllib.request.urlopen")
    @patch("ollama_client.is_alive")
    def test_cli_no_cache_bypass(self, mock_alive, mock_open):
        """P3: --no-cache must not write a cache file."""
        mock_alive.return_value = False
        mock_open.side_effect = _mock_urlopen(
            {
                "http://localhost:8080/search": {
                    "results": [{"title": "T", "url": "https://x", "content": "c"}]
                }
            }
        )
        before = _cache_file_count()
        f = io.StringIO()
        with redirect_stdout(f):
            wr.main(["search", "q", "-n", "2", "--no-cache"])
        self.assertEqual(_cache_file_count(), before)

    @patch("urllib.request.urlopen")
    @patch("ollama_client.is_alive")
    def test_cli_smart_search_shows_profile(self, mock_alive, mock_open):
        """P1.3: smart search renders the rule-based query profile header."""
        mock_alive.return_value = False
        mock_open.side_effect = _mock_urlopen(
            {
                "http://localhost:8080/search": {
                    "results": [{"title": "T", "url": "https://x", "content": "c"}]
                }
            }
        )
        f = io.StringIO()
        with redirect_stdout(f):
            wr.main(["search", "docs api reference", "-n", "2", "--smart"])
        self.assertIn("Intent: docs", f.getvalue())

    @patch("urllib.request.urlopen")
    def test_cli_read(self, mock_open):
        mock_open.side_effect = _mock_urlopen(
            {
                "http://localhost:3002/v1/scrape": {
                    "success": True,
                    "data": {"markdown": "# Title\nBody."},
                }
            }
        )
        f = io.StringIO()
        with redirect_stdout(f):
            rc = wr.main(["read", "https://example.com"])
        self.assertEqual(rc, 0)
        self.assertIn("Title", f.getvalue())

    @patch("urllib.request.urlopen")
    @patch("ollama_client.is_alive")
    def test_cli_read_does_not_cache_empty_on_failure(self, mock_alive, mock_open):
        """P0.1: a failed read must not poison the cache."""
        mock_alive.return_value = False
        mock_open.side_effect = urllib.error.URLError("down")
        before = _cache_file_count()
        with patch.object(wr.reader, "ZAI_API_KEY", ""):
            with redirect_stdout(io.StringIO()):
                rc = wr.main(["read", "https://example.com"])
        self.assertEqual(rc, 1)
        self.assertEqual(_cache_file_count(), before)

    @patch("urllib.request.urlopen")
    def test_cli_read_zai(self, mock_open):
        mock_open.side_effect = _mock_urlopen(
            {
                "https://api.z.ai/api/paas/v4/reader": {
                    "reader_result": {
                        "title": "Z",
                        "content": "z body",
                        "url": "https://example.com",
                    }
                }
            }
        )
        f = io.StringIO()
        with patch.object(wr.reader, "ZAI_API_KEY", "sk-test"):
            with redirect_stdout(f):
                rc = wr.main(["read", "https://example.com", "--engine", "zai"])
        self.assertEqual(rc, 0)
        self.assertIn("z body", f.getvalue())

    @patch("urllib.request.urlopen")
    def test_cli_read_firecrawl_down_fallback_zai(self, mock_open):
        """When Firecrawl fails and Z.AI key is present, reader falls back to Z.AI."""
        mock_open.side_effect = _mock_urlopen(
            {
                "https://api.z.ai/api/paas/v4/reader": {
                    "reader_result": {
                        "title": "Fallback",
                        "content": "zai body",
                        "url": "https://example.com",
                    }
                }
            }
        )
        f = io.StringIO()
        with patch.object(wr.reader, "ZAI_API_KEY", "sk-test"):
            with redirect_stdout(f):
                rc = wr.main(["read", "https://example.com"])
        self.assertEqual(rc, 0)
        self.assertIn("Fallback", f.getvalue())
        self.assertIn("zai body", f.getvalue())

    @patch("urllib.request.urlopen")
    @patch("ollama_client.is_alive")
    def test_cli_research_partial_scrape_failure(self, mock_alive, mock_open):
        """P2: ThreadPoolExecutor must tolerate one URL failing mid-batch."""
        mock_alive.return_value = False

        def side(req, **_kwargs):
            url = req.full_url
            if "localhost:8080/search" in url:
                return FakeResponse(
                    json.dumps(
                        {
                            "results": [
                                {"title": "A", "url": "https://a.com", "content": "ca"},
                                {"title": "B", "url": "https://b.com", "content": "cb"},
                            ]
                        }
                    ).encode()
                )
            # Firecrawl sends the target URL in the POST body, not the request URL.
            body = req.data.decode() if req.data else ""
            if "localhost:3002/v1/scrape" in url and "a.com" in body:
                return FakeResponse(
                    json.dumps({"success": True, "data": {"markdown": "md A"}}).encode()
                )
            raise Exception("b.com fails")

        mock_open.side_effect = side
        f = io.StringIO()
        with patch.object(wr.reader, "ZAI_API_KEY", ""):
            with patch.object(wr.synthesis, "cheap_complete", None):
                with redirect_stdout(f):
                    rc = wr.main(["research", "q", "-n", "2", "--scrape", "2"])
        self.assertEqual(rc, 0)
        self.assertIn("md A", f.getvalue())  # A scraped despite B failure


class ConfigFlagTests(unittest.TestCase):
    """P3: --timeout/--verbose push into module config."""

    def setUp(self):
        _clear_cache()

    def tearDown(self):
        _config.reload_settings()

    def test_apply_common_sets_timeout_and_verbose(self):
        from web_research.shared.cli_helpers import apply_common

        with patch.dict(os.environ, {"WEB_RESEARCH_TIMEOUT": "41", "WEB_RESEARCH_VERBOSE": "0"}):
            apply_common(Namespace(timeout=99, verbose=True))
            self.assertEqual(_config.TIMEOUT, 99)
            self.assertTrue(_config.VERBOSE)

            apply_common(Namespace(timeout=None, verbose=False))
            self.assertEqual(_config.TIMEOUT, 41)
            self.assertFalse(_config.VERBOSE)

    def test_apply_common_without_flags_preserves_environment_defaults(self):
        from web_research.shared.cli_helpers import apply_common

        with patch.dict(os.environ, {"WEB_RESEARCH_TIMEOUT": "17", "WEB_RESEARCH_VERBOSE": "1"}):
            apply_common(Namespace(timeout=None, verbose=False))
            self.assertEqual(_config.TIMEOUT, 17)
            self.assertTrue(_config.VERBOSE)
