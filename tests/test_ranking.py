"""Tests for source-quality ranking. Extracted from the former monolithic test_web_research.py."""
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

