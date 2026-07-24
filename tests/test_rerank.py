"""Tests for rerank ordering. Extracted from the former monolithic test_web_research.py."""

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
