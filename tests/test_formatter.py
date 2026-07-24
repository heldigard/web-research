"""Tests for result formatting. Extracted from the former monolithic test_web_research.py."""

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
