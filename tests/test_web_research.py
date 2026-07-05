#!/usr/bin/env python3
"""Unit/e2e tests for web_research package (network mocked)."""

from __future__ import annotations

import io
import json
import unittest
import urllib.error
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import web_research as wr  # noqa: E402
import web_research.shared.config as _config  # noqa: E402


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


def _mock_urlopen(response_map: dict):
    def side_effect(req, **kwargs):
        url = req.full_url
        for prefix, body in response_map.items():
            if url.startswith(prefix):
                return FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode())
        raise Exception(f"unmocked url: {url}")

    return side_effect


class SearchTests(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    @patch("urllib.request.urlopen")
    def test_searxng_search(self, mock_open):
        mock_open.side_effect = _mock_urlopen(
            {
                "http://localhost:8080/search": {
                    "results": [
                        {
                            "title": "Python 3.12",
                            "url": "https://python.org",
                            "content": "New features.",
                        },
                    ]
                }
            }
        )
        res = wr.searxng_search("python 3.12", num=5)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["source"], "searxng")
        self.assertEqual(res[0]["title"], "Python 3.12")

    @patch("urllib.request.urlopen")
    def test_minimax_search(self, mock_open):
        mock_open.side_effect = _mock_urlopen(
            {
                "https://api.minimax.io/v1/coding_plan/search": {
                    "organic": [
                        {
                            "title": "T",
                            "link": "https://example.com",
                            "snippet": "C",
                            "date": "",
                        },
                    ]
                }
            }
        )
        with patch.object(wr.search, "MINIMAX_API_KEY", "sk-test"):
            res = wr.minimax_search("q", num=2)
        self.assertEqual(res[0]["source"], "minimax")

    @patch("urllib.request.urlopen")
    def test_zai_reader(self, mock_open):
        mock_open.side_effect = _mock_urlopen(
            {
                "https://api.z.ai/api/paas/v4/reader": {
                    "reader_result": {
                        "title": "R",
                        "content": "body",
                        "url": "https://example.com",
                    }
                }
            }
        )
        with patch.object(wr.reader, "ZAI_API_KEY", "sk-test"):
            md = wr.zai_reader("https://example.com")
        self.assertIn("# R", md)
        self.assertIn("body", md)

    @patch("urllib.request.urlopen")
    def test_zai_search(self, mock_open):
        mock_open.side_effect = _mock_urlopen(
            {
                "https://api.z.ai/api/paas/v4/web_search": {
                    "search_result": [
                        {
                            "title": "Z",
                            "link": "https://z.ai",
                            "content": "z result",
                            "media": "news",
                        },
                    ]
                }
            }
        )
        with patch.object(wr.search, "ZAI_API_KEY", "sk-test"):
            res = wr.zai_search("q", num=2)
        self.assertEqual(res[0]["source"], "zai")
        self.assertEqual(res[0]["engine"], "news")

    @patch("urllib.request.urlopen")
    def test_search_backends_dedup(self, mock_open):
        """SearXNG fallback should not duplicate primary engine results."""
        url = "https://example.com/page"
        mock_open.side_effect = _mock_urlopen(
            {
                "https://api.minimax.io/v1/coding_plan/search": {
                    "organic": [{"title": "A", "link": url, "snippet": "x", "date": ""}],
                },
                "http://localhost:8080/search": {
                    "results": [{"title": "B", "url": url, "content": "x"}]
                },
            }
        )
        with patch.object(wr.search, "MINIMAX_API_KEY", "sk-test"):
            res = wr.search_backends(
                "q", num=3, engine="minimax", cat="general", lang="en", time_range=""
            )
        self.assertEqual(len(res), 1)


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


class RerankTests(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    @patch("ollama_client.embed")
    @patch("ollama_client.is_alive")
    def test_rerank_orders_by_similarity(self, mock_alive, mock_embed):
        mock_alive.return_value = True
        # query vector points toward second result.
        qv = [1.0, 0.0]
        v1 = [0.0, 1.0]
        v2 = [1.0, 0.1]
        mock_embed.side_effect = lambda text, **kw: (
            qv if text == "q" else (v2 if "second" in text else v1)
        )
        results = [
            {"title": "first", "url": "https://a", "content": "irrelevant"},
            {"title": "second", "url": "https://b", "content": "matches query"},
        ]
        ordered = wr.rerank_results("q", results)
        self.assertEqual(ordered[0]["title"], "second")


class IntelligenceTests(unittest.TestCase):
    """P0.3: is_alive guard + P2: query intelligence coverage."""

    def setUp(self):
        _clear_cache()

    @patch("ollama_client.generate")
    @patch("ollama_client.is_alive")
    def test_query_profile_no_llm_when_down(self, mock_alive, mock_gen):
        """When Ollama is down, query_profile returns rule-based default
        WITHOUT calling generate (the old `if not generate` was dead code)."""
        mock_alive.return_value = False
        prof = wr.query_profile("compare django versus flask")
        self.assertEqual(prof["intent"], "comparison")
        self.assertEqual(prof["expected_format"], "table")
        mock_gen.assert_not_called()

    @patch("ollama_client.generate")
    @patch("ollama_client.is_alive")
    def test_query_profile_troubleshooting_rule(self, mock_alive, mock_gen):
        mock_alive.return_value = False
        prof = wr.query_profile("fix error traceback nullpointer")
        self.assertEqual(prof["intent"], "troubleshooting")
        self.assertTrue(prof["needs_recency"])
        mock_gen.assert_not_called()

    @patch("ollama_client.generate")
    @patch("ollama_client.is_alive")
    def test_focused_extract_heuristic_when_down(self, mock_alive, mock_gen):
        """When Ollama is down, focused_extract falls back to heuristic
        WITHOUT calling generate."""
        mock_alive.return_value = False
        text = "intro\n\n" + ("fastapi middleware " * 50) + "\n\nunrelated " * 20
        out = wr.focused_extract(text, "fastapi middleware")
        self.assertTrue(out)
        mock_gen.assert_not_called()

    @patch("ollama_client.generate")
    @patch("ollama_client.is_alive")
    def test_focused_extract_llm_path(self, mock_alive, mock_gen):
        """When Ollama is up, focused_extract uses the LLM extraction."""
        mock_alive.return_value = True
        mock_gen.return_value = "Relevant extracted answer."
        out = wr.focused_extract("x" * 1000, "query")
        self.assertIn("Relevant extracted answer", out)

    def test_expand_queries_dedup(self):
        prof = {"expand_queries": ["q", "q", "q2"]}
        out = wr.expand_queries("q", prof)
        self.assertEqual(out, ["q", "q2"])


class RankingTests(unittest.TestCase):
    """P2: source_quality_score coverage."""

    def test_source_quality_authority_domain(self):
        high = wr.source_quality_score("https://docs.python.org/3/library/", "Title", "x" * 100)
        self.assertGreaterEqual(high, 0.4)

    def test_source_quality_random_low(self):
        low = wr.source_quality_score("https://random-example.xyz/post", "T", "short")
        self.assertLess(low, 0.5)

    def test_source_quality_empty_url(self):
        self.assertEqual(wr.source_quality_score("", "T", "c"), 0.0)


class FormatterTests(unittest.TestCase):
    """P2: formatter coverage + P1.3: profile/summary rendering."""

    def test_fmt_results_empty(self):
        self.assertEqual(wr.fmt_results([]), "_No results._")

    def test_fmt_smart_results_with_profile_and_summary(self):
        results = [{"title": "T", "url": "https://x", "content": "c" * 200, "_quality": 0.8}]
        prof = {
            "intent": "docs",
            "needs_recency": False,
            "expected_format": "paragraph",
        }
        out = wr.fmt_smart_results(results, "q", profile=prof, summary="### Key facts\n- a fact")
        self.assertIn("Intent: docs", out)
        self.assertIn("evergreen", out)
        self.assertIn("Key facts", out)
        self.assertIn("⭐", out)

    def test_fmt_smart_results_backwards_compatible(self):
        """Old callers passing just (results, query) still work."""
        results = [{"title": "T", "url": "https://x", "content": "c", "_quality": 0.2}]
        out = wr.fmt_smart_results(results, "q")
        self.assertIn("Smart search", out)
        self.assertNotIn("Intent:", out)  # no profile -> no header


class SynthesisTests(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    @patch("ollama_client.generate")
    @patch("ollama_client.is_alive")
    def test_synthesize_uses_local_first(self, mock_alive, mock_gen):
        mock_alive.return_value = True
        mock_gen.return_value = "Local answer."
        docs = [{"title": "D", "url": "https://d", "text": "body"}]
        out = wr.synthesize("q", docs)
        self.assertEqual(out, "Local answer.")

    @patch.object(wr.synthesis, "cheap_complete")
    @patch("ollama_client.is_alive")
    def test_synthesize_falls_back_cloud(self, mock_alive, mock_cloud):
        mock_alive.return_value = False
        mock_cloud.return_value = {"text": "Cloud answer."}
        docs = [{"title": "D", "url": "https://d", "text": "body"}]
        out = wr.synthesize("q", docs)
        self.assertEqual(out, "Cloud answer.")

    def test_render_structured_parses_json(self):
        from web_research.features.synthesis.engine import _render_structured

        payload = (
            '{"answer":"A","facts":[{"claim":"c","source":1,"confidence":"high"}],'
            '"unknowns":["u"],"recommended_next_search":"next"}'
        )
        out = _render_structured(payload)
        self.assertIn("A", out)
        self.assertIn("Key facts", out)
        self.assertIn("(high)", out)
        self.assertIn("u", out)
        self.assertIn("next", out)

    def test_render_structured_invalid_json_passthrough(self):
        from web_research.features.synthesis.engine import _render_structured

        out = _render_structured("not json at all")
        self.assertEqual(out, "not json at all")


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
        """P0.1: a failed (empty) search must not poison the cache."""
        mock_alive.return_value = False
        mock_open.side_effect = urllib.error.URLError("searxng down")
        before = _cache_file_count()
        f = io.StringIO()
        with redirect_stdout(f):
            rc = wr.main(["search", "searxng-down-q", "-n", "3"])
        self.assertEqual(rc, 0)
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

        def side(req, **kwargs):
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

    def test_apply_common_sets_timeout_and_verbose(self):
        from web_research.shared.cli_helpers import apply_common

        orig_t, orig_v = _config.TIMEOUT, _config.VERBOSE
        try:
            apply_common(Namespace(timeout=99, verbose=True))
            self.assertEqual(_config.TIMEOUT, 99)
            self.assertTrue(_config.VERBOSE)
        finally:
            _config.TIMEOUT, _config.VERBOSE = orig_t, orig_v

    def test_apply_common_none_keeps_defaults(self):
        from web_research.shared.cli_helpers import apply_common

        orig_t, orig_v = _config.TIMEOUT, _config.VERBOSE
        try:
            apply_common(Namespace(timeout=None, verbose=False))
            self.assertEqual(_config.TIMEOUT, orig_t)
            self.assertFalse(_config.VERBOSE)
        finally:
            _config.TIMEOUT, _config.VERBOSE = orig_t, orig_v


if __name__ == "__main__":
    unittest.main()
