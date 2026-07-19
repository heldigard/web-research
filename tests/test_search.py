"""Tests for search backends (searxng/minimax/zai) and dedup. Extracted from the former monolithic test_web_research.py."""
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
                "status": _noop_handler,
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
        self.assertEqual(set(by_name), {"search", "read", "research", "capabilities", "status"})
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

