"""Tests for domain matching. Extracted from the former monolithic test_web_research.py."""

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
