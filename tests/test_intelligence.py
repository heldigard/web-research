"""Tests for query profile, focused extract, expand queries. Extracted from the former monolithic test_web_research.py."""

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
