#!/usr/bin/env python3
"""Unit/e2e tests for web_research package (network mocked)."""

from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

# Hermetic: the host shell may export SEARXNG_URL/FC_URL/OLLAMA_URL (e.g.
# 127.0.0.1 loopback binds); tests mock the canonical localhost URLs, so the
# ambient env must not leak into the settings singleton before import.
for _env in ("SEARXNG_URL", "FC_URL", "OLLAMA_URL"):
    os.environ.pop(_env, None)

import web_research as wr  # noqa: E402
import web_research.shared.config as _config  # noqa: E402
from web_research.cli_parser import build_parser  # noqa: E402


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


def _noop_handler(_args):
    return 0


def _mock_urlopen(response_map: dict):
    def side_effect(req, **_kwargs):
        url = req.full_url
        for prefix, body in response_map.items():
            if url.startswith(prefix):
                return FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode())
        raise Exception(f"unmocked url: {url}")

    return side_effect


class SearchTests(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    def test_version_fallback_not_zero(self):
        self.assertEqual(wr.__version__, "0.2.0")

    def test_cli_version_uses_package_version(self):
        parser = build_parser(
            {
                "search": _noop_handler,
                "research": _noop_handler,
                "read": _noop_handler,
                "capabilities": _noop_handler,
            }
        )
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, redirect_stdout(buf):
            parser.parse_args(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("web-research 0.2.0", buf.getvalue())

    def test_cli_capabilities_contract(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = wr.main(["capabilities", "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["command"], "capabilities")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["version"], "0.2.0")
        by_name = {item["name"]: item for item in payload["capabilities"]}
        self.assertEqual(set(by_name), {"search", "read", "research", "capabilities"})
        self.assertFalse(by_name["capabilities"]["open_world"])
        self.assertEqual(by_name["search"]["engines"], ["searxng", "minimax", "zai", "duckduckgo"])
        self.assertEqual(by_name["read"]["engines"], ["firecrawl", "zai", "html"])
        self.assertEqual(
            by_name["research"]["engines"], ["searxng", "minimax", "zai", "duckduckgo"]
        )
        self.assertEqual(by_name["capabilities"]["engines"], [])
        self.assertEqual(
            by_name["search"]["options"]["cache"],
            {"flag": "--no-cache", "default": False, "effect": "bypass_disk_cache"},
        )
        self.assertEqual(
            by_name["search"]["options"]["verbose"], {"flag": "--verbose", "default": False}
        )
        self.assertEqual(
            by_name["search"]["options"]["count"], {"flag": "-n", "type": "integer", "default": 8}
        )
        self.assertEqual(
            by_name["search"]["options"]["time"],
            {"flag": "--time", "values": ["day", "week", "month", "year"]},
        )
        self.assertEqual(
            by_name["read"]["options"],
            {
                "cache": {"flag": "--no-cache", "default": False, "effect": "bypass_disk_cache"},
                "timeout": {"flag": "--timeout", "type": "integer", "unit": "seconds"},
                "verbose": {"flag": "--verbose", "default": False},
                "engine": {"flag": "--engine", "default": "firecrawl"},
                "robots": {"default": "enforce", "bypass_flag": "--no-robots"},
                "wait": {"flag": "--wait", "type": "integer", "unit": "seconds", "default": 0},
                "zai_timeout": {
                    "flag": "--zai-timeout",
                    "type": "integer",
                    "unit": "seconds",
                    "default": 20,
                },
                "max_chars": {"flag": "--max-chars", "type": "integer", "default": 12000},
            },
        )
        self.assertEqual(
            by_name["research"]["options"]["code_analyze"],
            {
                "flag": "--code-analyze",
                "default": False,
                "dependency": "codeq",
                "unavailable": "no_op",
                "structured_output": "local_code_context",
            },
        )
        self.assertEqual(
            by_name["research"]["options"]["robots"],
            {"default": "enforce", "bypass_flag": "--no-robots"},
        )
        self.assertEqual(
            by_name["research"]["options"]["verbose"], {"flag": "--verbose", "default": False}
        )
        self.assertEqual(
            by_name["research"]["options"]["count"], {"flag": "-n", "type": "integer", "default": 6}
        )
        self.assertEqual(buf.getvalue().count("\n"), 1, "router manifest stays compact")

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
        with patch.object(wr.search.backends.minimax, "MINIMAX_API_KEY", "sk-test"):
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
        with patch.object(wr.search.backends.zai, "ZAI_API_KEY", "sk-test"):
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
        with patch.object(wr.search.backends.minimax, "MINIMAX_API_KEY", "sk-test"):
            res = wr.search_backends(
                "q", num=3, engine="minimax", cat="general", lang="en", time_range=""
            )
        self.assertEqual(len(res), 1)

    @patch("urllib.request.urlopen")
    def test_search_backends_canonical_url_dedup(self, mock_open):
        """Tracking params and fragments should not create duplicate results."""
        mock_open.side_effect = _mock_urlopen(
            {
                "http://localhost:8080/search": {
                    "results": [
                        {
                            "title": "A",
                            "url": "https://example.com/page?utm_source=x#frag",
                            "content": "x",
                        },
                        {
                            "title": "B",
                            "url": "https://example.com/page",
                            "content": "x",
                        },
                    ]
                }
            }
        )
        res = wr.search_backends(
            "q", num=3, engine="searxng", cat="general", lang="en", time_range=""
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
        mock_embed.side_effect = lambda text, **_kwargs: (
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

    def test_search_queries_adds_bounded_preferred_sites(self):
        prof = {
            "expand_queries": ["q exact", "q alternative"],
            "preferred_sites": ["site:docs.example.com", "not-a-site", "site:github.com"],
        }
        out = wr.search_queries("q", prof, max_queries=4)
        self.assertEqual(
            out,
            ["q", "q exact", "q alternative", "q site:docs.example.com"],
        )

    @patch("web_research.features.intelligence.engine.generate")
    @patch("web_research.features.intelligence.engine.is_alive")
    def test_query_profile_normalizes_malformed_llm_fields(self, mock_alive, mock_generate):
        mock_alive.return_value = True
        mock_generate.return_value = json.dumps(
            {
                "intent": 42,
                "needs_recency": "false",
                "preferred_sites": "site:invalid.example",
                "expected_format": "spreadsheet",
                "expand_queries": [1, None, "  valid query  "],
                "ignored": "field",
            }
        )

        profile = wr.query_profile("docs api reference")

        self.assertEqual(profile["intent"], "docs")
        self.assertFalse(profile["needs_recency"])
        self.assertEqual(profile["expected_format"], "paragraph")
        self.assertEqual(profile["expand_queries"], ["valid query"])
        self.assertNotIn("ignored", profile)

    def test_query_helpers_skip_non_string_profile_values(self):
        profile = {
            "expand_queries": [1, None, "  q alternative  "],
            "preferred_sites": [object(), "site:docs.example.com"],
        }

        self.assertEqual(wr.expand_queries("q", profile), ["q", "q alternative"])
        self.assertEqual(
            wr.search_queries("q", profile, max_queries=3),
            ["q", "q alternative", "q site:docs.example.com"],
        )

    @patch("web_research.features.intelligence.engine.generate")
    @patch("web_research.features.intelligence.engine.is_alive")
    def test_query_profile_preserves_valid_empty_preferred_sites(self, mock_alive, mock_generate):
        mock_alive.return_value = True
        mock_generate.return_value = json.dumps(
            {
                "intent": "docs",
                "needs_recency": False,
                "preferred_sites": [],
                "expected_format": "paragraph",
                "expand_queries": ["docs api reference"],
            }
        )

        profile = wr.query_profile("docs api reference")

        self.assertEqual(profile["preferred_sites"], [])


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

    @patch("ollama_client.generate")
    @patch("ollama_client.is_alive")
    def test_synthesize_caches_result(self, mock_alive, mock_gen):
        """A second identical synthesis is served from cache (no Ollama call)."""
        mock_alive.return_value = True
        mock_gen.return_value = "Cached answer."
        docs = [{"title": "D", "url": "https://d", "text": "body"}]
        first = wr.synthesize("cache-q", docs)
        second = wr.synthesize("cache-q", docs)
        self.assertEqual(first, "Cached answer.")
        self.assertEqual(second, "Cached answer.")
        self.assertEqual(mock_gen.call_count, 1, "second call should hit cache, not Ollama")

    @patch("ollama_client.generate")
    @patch("ollama_client.is_alive")
    def test_synthesize_no_cache_bypasses(self, mock_alive, mock_gen):
        """no_cache=True skips both read and write."""
        mock_alive.return_value = True
        mock_gen.return_value = "Fresh answer."
        docs = [{"title": "D", "url": "https://d", "text": "body"}]
        wr.synthesize("nc-q", docs, no_cache=True)
        wr.synthesize("nc-q", docs, no_cache=True)
        self.assertEqual(mock_gen.call_count, 2, "no_cache must not serve cached result")

    @patch("ollama_client.generate")
    @patch("ollama_client.is_alive")
    def test_synthesize_cache_invalidates_on_doc_change(self, mock_alive, mock_gen):
        """A different source set (same URL, new content) must miss."""
        mock_alive.return_value = True
        mock_gen.return_value = "Answer."
        wr.synthesize("q", [{"title": "D", "url": "https://d", "text": "body-one"}])
        wr.synthesize("q", [{"title": "D", "url": "https://d", "text": "body-two"}])
        self.assertEqual(mock_gen.call_count, 2, "changed source content must bypass cache")

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

    def test_compact_source_text_marks_truncation(self):
        from web_research.features.synthesis.engine import _compact_source_text

        text = "paragraph one\n\n" + "x" * 2000 + "\n\nparagraph three"
        out = _compact_source_text(text, 300)
        self.assertLessEqual(len(out), 300)
        self.assertIn("[content truncated]", out)

    # ---------------------------------------------------------------
    # 2026-07-09 wiring regression: PRIMARY (TeichAI/Fable-5-v1) +
    # FALLBACK (xentriom/Q8_0) must match ~/ollama-bench/RANKING.md.
    # Earlier audit found FALLBACK slot entirely absent.
    # ---------------------------------------------------------------
    def test_synth_model_wiring_matches_ranking(self):
        from web_research.shared.config import (
            _OLLAMA_DEFAULT_SYNTH_FALLBACK_MODEL,
            _OLLAMA_DEFAULT_SYNTH_MODEL,
            OLLAMA_SYNTH_FALLBACK_MODEL,
            OLLAMA_SYNTH_MODEL,
            load_settings,
        )

        # PRIMARY per RANKING.md web_synth #1 (validated 2026-07-09)
        self.assertEqual(
            _OLLAMA_DEFAULT_SYNTH_MODEL,
            "hf.co/TeichAI/Qwen3.5-9B-Fable-5-v1-GGUF:Q4_K_M",
            "web_synth PRIMARY drifted from RANKING.md",
        )
        # FALLBACK per RANKING.md web_synth #2
        self.assertEqual(
            _OLLAMA_DEFAULT_SYNTH_FALLBACK_MODEL,
            "xentriom/gemma-4-12B-agentic-fable5-composer2.5-v2:Q8_0",
            "web_synth FALLBACK drifted from RANKING.md (or is missing)",
        )
        # Legacy SCREAMING_CASE proxy resolves the modern settings field
        # (PRIMARY + FALLBACK must be distinct)
        self.assertNotEqual(OLLAMA_SYNTH_FALLBACK_MODEL, OLLAMA_SYNTH_MODEL)
        self.assertEqual(OLLAMA_SYNTH_FALLBACK_MODEL, _OLLAMA_DEFAULT_SYNTH_FALLBACK_MODEL)
        self.assertEqual(OLLAMA_SYNTH_MODEL, _OLLAMA_DEFAULT_SYNTH_MODEL)
        # Load with no env override — defaults apply
        s = load_settings()
        self.assertEqual(s.ollama_synth_model, _OLLAMA_DEFAULT_SYNTH_MODEL)
        self.assertEqual(s.ollama_synth_fallback_model, _OLLAMA_DEFAULT_SYNTH_FALLBACK_MODEL)
        # Env override flows through
        with patch.dict(os.environ, {"OLLAMA_SYNTH_FALLBACK_MODEL": "tiny:1b"}):
            s2 = load_settings()
        self.assertEqual(s2.ollama_synth_fallback_model, "tiny:1b")

    @patch("ollama_client.generate")
    @patch("ollama_client.is_alive")
    def test_synthesize_falls_back_to_local_fallback(self, mock_alive, mock_gen):
        """If PRIMARY returns empty/None, synthesize() must try the FALLBACK
        model before giving up to cloud. Pins the chain order to RANKING.md."""
        mock_alive.return_value = True
        # First call (PRIMARY) returns empty; second call (FALLBACK) returns text.
        mock_gen.side_effect = ["", "Fallback answer."]
        from web_research.shared.config import get_settings, load_settings

        load_settings()  # reset module singleton with current defaults
        s = get_settings()
        # sanity: fallback is wired and distinct from primary
        self.assertNotEqual(s.ollama_synth_model, s.ollama_synth_fallback_model)
        docs = [{"title": "D", "url": "https://d", "text": "body"}]
        out = wr.synthesize("q", docs)
        self.assertEqual(out, "Fallback answer.")
        # Both PRIMARY + FALLBACK must have been called (chain length ≥ 2).
        self.assertGreaterEqual(mock_gen.call_count, 2, "PRIMARY → FALLBACK chain skipped")
        # The second call must use the FALLBACK model.
        fallback_call = mock_gen.call_args_list[1]
        called_model = fallback_call.kwargs.get("model") or fallback_call.args[0]
        self.assertIn(
            "xentriom", called_model, f"FALLBACK slot called wrong model: {called_model!r}"
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
        with (
            patch.object(research_cmd, "search_backends", return_value=[result]),
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
        self.assertEqual(payload["scraping"], {"requested": 1, "succeeded": 1})
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
        with (
            patch.object(research_cmd, "search_backends", return_value=[result]),
            patch.object(research_cmd, "is_alive", return_value=False),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = wr.main(["research", "feature", "--json", "--scrape", "0"])

        payload = json.loads(output.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["scraping"], {"requested": 0, "succeeded": 0})
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


class RenderStructuredTests(unittest.TestCase):
    """Structured synthesis rendering: contradictions, facts, unknowns."""

    def test_contradictions_sources_formatted_as_citations(self):
        from web_research.features.synthesis.engine import _render_structured

        payload = json.dumps(
            {
                "answer": "A",
                "contradictions": [{"claim_a": "X works", "claim_b": "X fails", "sources": [1, 3]}],
            }
        )
        out = _render_structured(payload)
        self.assertIn("[1, 3]", out)
        self.assertNotIn("[1,3]", out)  # no raw list repr

    def test_contradictions_empty_sources_no_brackets(self):
        from web_research.features.synthesis.engine import _render_structured

        payload = json.dumps({"contradictions": [{"claim_a": "A", "claim_b": "B", "sources": []}]})
        out = _render_structured(payload)
        self.assertIn("A vs B", out)
        self.assertNotIn("[]", out)

    def test_contradictions_missing_sources_no_crash(self):
        from web_research.features.synthesis.engine import _render_structured

        payload = json.dumps({"contradictions": [{"claim_a": "A", "claim_b": "B"}]})
        out = _render_structured(payload)
        self.assertIn("A vs B", out)

    def test_full_structured_roundtrip(self):
        from web_research.features.synthesis.engine import _render_structured

        payload = json.dumps(
            {
                "answer": "The answer",
                "facts": [
                    {"claim": "fact1", "source": 1, "confidence": "high"},
                    {"claim": "fact2", "source": 2, "confidence": "low"},
                ],
                "contradictions": [{"claim_a": "A", "claim_b": "B", "sources": [1, 2]}],
                "unknowns": ["what about X?"],
                "recommended_next_search": "search for X",
            }
        )
        out = _render_structured(payload)
        self.assertIn("The answer", out)
        self.assertIn("Key facts", out)
        self.assertIn("(high) fact1 [1]", out)
        self.assertIn("(low) fact2 [2]", out)
        self.assertIn("Contradictions", out)
        self.assertIn("[1, 2]", out)
        self.assertIn("Unknowns", out)
        self.assertIn("what about X?", out)
        self.assertIn("Suggested next search", out)
        self.assertIn("search for X", out)


class DomainMatchTests(unittest.TestCase):
    """source_quality_score domain matching edge cases."""

    def test_exact_domain_match(self):
        score = wr.source_quality_score("https://docs.python.org/3/", "Title", "x" * 100)
        self.assertGreaterEqual(score, 0.4)

    def test_subdomain_match(self):
        score = wr.source_quality_score("https://docs.python.org/dev/", "Title", "x" * 100)
        self.assertGreaterEqual(score, 0.4)

    def test_evil_subdomain_no_match(self):
        """evil-docs.python.org must NOT match docs.python.org."""
        score = wr.source_quality_score("https://evil-docs.python.org/phish", "T", "short")
        self.assertLess(score, 0.4)

    def test_similar_but_different_domain(self):
        score = wr.source_quality_score("https://notpython.org/docs/", "T", "short")
        self.assertLess(score, 0.4)

    def test_stackoverflow_exact(self):
        score = wr.source_quality_score("https://stackoverflow.com/q/123", "Title", "x" * 100)
        self.assertGreaterEqual(score, 0.4)

    def test_fake_stackoverflow_no_match(self):
        score = wr.source_quality_score("https://evil-stackoverflow.com/q/1", "T", "short")
        self.assertLess(score, 0.4)


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


class QueryProfileRuleTests(unittest.TestCase):
    """query_profile rule-based classification edge cases."""

    def setUp(self):
        # is_alive() caches its result for 30s; bust it so the per-test
        # ``is_alive=False`` mock is honored instead of a stale True value
        # left by an earlier test (which would route into the LLM path).
        from web_research.shared.ollama_api import _bust_alive_cache

        _bust_alive_cache()

    @patch("ollama_client.is_alive")
    def test_news_keywords_set_recency(self, mock_alive):
        mock_alive.return_value = False
        prof = wr.query_profile("latest python 3.13 release announced")
        self.assertTrue(prof["needs_recency"])
        self.assertEqual(prof["intent"], "news")

    @patch("ollama_client.is_alive")
    def test_docs_keywords_set_sites(self, mock_alive):
        mock_alive.return_value = False
        prof = wr.query_profile("flask api reference method")
        self.assertEqual(prof["intent"], "docs")
        self.assertTrue(any("docs.python.org" in s for s in prof["preferred_sites"]))

    @patch("ollama_client.is_alive")
    def test_general_fallback(self, mock_alive):
        mock_alive.return_value = False
        prof = wr.query_profile("random unrelated topic")
        self.assertEqual(prof["intent"], "general")
        self.assertFalse(prof["needs_recency"])


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
