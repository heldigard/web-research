#!/usr/bin/env python3
"""Tests for the zero-dependency enhancement batch (2026-07-08).

Covers, per feature, with the network mocked or via pure functions:
  - HTTP retry/backoff (stdlib)
  - Authority-domain data-file loader
  - Stopword/punctuation-aware tokenization
  - Tolerant structured-JSON extraction
  - Size-bound LRU cache eviction
  - robots.txt fail-open gate
  - Stdlib HTML reader
  - TEI cross-encoder rerank client
  - DuckDuckGo HTML backend (redirect unwrap + parsing)
"""

from __future__ import annotations

import os
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import web_research.shared.config as _config
from web_research.features.ranking import tei_rerank
from web_research.features.ranking.engine import (
    _load_authority_domains,
    _maybe_tei_rerank,
    _tokenize,
    query_word_overlap,
)
from web_research.features.read.backends.html import _html_to_markdown
from web_research.features.read.engine import read_with_fallback
from web_research.features.search.backends.duckduckgo import (
    _DDGResultParser,
    _decode_ddg_href,
)
from web_research.features.synthesis.engine import _extract_json_object
from web_research.shared import cache
from web_research.shared.cache import _collect_cache_entries
from web_research.shared.http import UrllibHttpClient, _backoff_seconds, _retry_after_seconds
from web_research.shared.robots import is_allowed


def _clear_cache() -> None:
    from shutil import rmtree

    cache_dir = Path(_config.CACHE_DIR or Path.home() / ".cache" / "web-research")
    if cache_dir.exists():
        rmtree(cache_dir)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class HttpRetryTests(unittest.TestCase):
    """Stdlib exponential-backoff retry on transient failures."""

    def setUp(self) -> None:
        _config.reload_settings(http_max_retries=2, http_backoff_base=0.0)

    def test_backoff_caps_and_zero(self) -> None:
        self.assertEqual(_backoff_seconds(0, 0.0), 0.0)
        self.assertEqual(_backoff_seconds(0, 0.4), 0.4)
        self.assertAlmostEqual(_backoff_seconds(2, 0.4), 1.6)
        self.assertLessEqual(_backoff_seconds(10, 0.4), 10.0)

    def test_urlerror_then_success_returns_body(self) -> None:
        calls = {"n": 0}

        def side_effect(req: object, **kw: object) -> _FakeResponse:
            i = calls["n"]
            calls["n"] += 1
            if i == 0:
                raise urllib.error.URLError("boom")
            return _FakeResponse(b"OK")

        with patch("urllib.request.urlopen", side_effect=side_effect):
            body = UrllibHttpClient().get_bytes("http://x/")
        self.assertEqual(body, b"OK")
        self.assertEqual(calls["n"], 2)

    def test_persistent_urlerror_raises_after_retries(self) -> None:
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(urllib.error.URLError):
                UrllibHttpClient().get_bytes("http://x/")

    def test_4xx_not_retried(self) -> None:
        calls = {"n": 0}

        def side_effect(req: urllib.request.Request, **kw: object) -> object:
            calls["n"] += 1
            raise urllib.error.HTTPError(req.full_url, 404, "Nope", {}, None)

        with patch("urllib.request.urlopen", side_effect=side_effect):
            with self.assertRaises(urllib.error.HTTPError):
                UrllibHttpClient().get_bytes("http://x/")
        self.assertEqual(calls["n"], 1)

    def test_429_is_retried(self) -> None:
        calls = {"n": 0}

        def side_effect(req: urllib.request.Request, **kw: object) -> object:
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.HTTPError(req.full_url, 429, "Slow", {}, None)
            return _FakeResponse(b"late")

        with patch("urllib.request.urlopen", side_effect=side_effect):
            body = UrllibHttpClient().get_bytes("http://x/")
        self.assertEqual(body, b"late")
        self.assertEqual(calls["n"], 3)

    def test_retry_after_parsed_and_capped(self) -> None:
        e5 = urllib.error.HTTPError("http://x", 429, "Slow", {"Retry-After": "5"}, None)
        self.assertEqual(_retry_after_seconds(e5), 5.0)
        e_huge = urllib.error.HTTPError("http://x", 429, "Slow", {"Retry-After": "9999"}, None)
        self.assertEqual(_retry_after_seconds(e_huge), 30.0)  # capped

    def test_retry_after_absent_or_garbage(self) -> None:
        none_hdr = urllib.error.HTTPError("http://x", 429, "Slow", {}, None)
        self.assertIsNone(_retry_after_seconds(none_hdr))
        junk = urllib.error.HTTPError("http://x", 429, "Slow", {"Retry-After": "Wed, 21 Oct"}, None)
        self.assertIsNone(_retry_after_seconds(junk))  # HTTP-date form unsupported


class ReaderChainTests(unittest.TestCase):
    """Fallback chain: Firecrawl down -> stdlib HTML reader succeeds."""

    def test_chain_falls_through_to_html(self) -> None:
        html_body = b"<html><head><title>Ex</title></head><body><p>Hi there</p></body></html>"

        def side_effect(req: urllib.request.Request, **kw: object) -> object:
            url = req.full_url
            if "localhost:3002" in url:  # Firecrawl POST
                raise urllib.error.URLError("firecrawl down")
            if "example.com" in url:  # plain GET for the HTML reader
                return _FakeResponse(html_body)
            raise Exception(f"unmocked: {url}")

        with patch("urllib.request.urlopen", side_effect=side_effect):
            with patch.object(
                __import__("web_research.features.read.engine", fromlist=["ZAI_API_KEY"]),
                "ZAI_API_KEY",
                "",
            ):
                md = read_with_fallback(
                    "https://example.com", engine="firecrawl", respect_robots=False
                )
        self.assertIn("# Ex", md)
        self.assertIn("Hi there", md)


class AuthorityDataTests(unittest.TestCase):
    """Authority domains loaded from the packaged data file."""

    def test_loads_known_domains(self) -> None:
        domains = _load_authority_domains()
        self.assertIn("docs.python.org", domains)
        self.assertIn("stackoverflow.com", domains)
        self.assertGreater(len(domains), 20)

    def test_loader_is_cached(self) -> None:
        first = _load_authority_domains()
        second = _load_authority_domains()
        self.assertIs(first, second)


class TokenizeTests(unittest.TestCase):
    """Overlap ignores punctuation and stopwords."""

    def test_strips_punctuation(self) -> None:
        self.assertEqual(_tokenize("Rust? rust, RUST!"), {"rust"})

    def test_drops_stopwords_and_single_chars(self) -> None:
        tokens = _tokenize("how to use the a I")
        self.assertNotIn("how", tokens)
        self.assertNotIn("the", tokens)
        self.assertNotIn("a", tokens)
        self.assertIn("use", tokens)

    def test_overlap_normalized(self) -> None:
        # Same word, different case + punctuation → full overlap.
        self.assertAlmostEqual(query_word_overlap("How to use Rust?", "use rust the language"), 1.0)
        self.assertEqual(query_word_overlap("", "content"), 0.0)


class JsonExtractorTests(unittest.TestCase):
    """_extract_json_object tolerates fences, prose, and braces inside strings."""

    def test_clean_object(self) -> None:
        self.assertEqual(_extract_json_object('{"answer": "A"}'), {"answer": "A"})

    def test_fenced(self) -> None:
        self.assertEqual(_extract_json_object('```json\n{"answer": "X"}\n```'), {"answer": "X"})

    def test_prose_wrapped(self) -> None:
        text = 'Sure! Here it is:\n{"answer": "Y", "unknowns": ["z"]}\nDone.'
        self.assertEqual(_extract_json_object(text), {"answer": "Y", "unknowns": ["z"]})

    def test_brace_inside_string(self) -> None:
        self.assertEqual(_extract_json_object('{"a": "b}c", "d": 1}'), {"a": "b}c", "d": 1})

    def test_rejects_plain_text_and_lists(self) -> None:
        self.assertIsNone(_extract_json_object("just text no braces"))
        self.assertIsNone(_extract_json_object("[1, 2, 3]"))


class CacheEvictionTests(unittest.TestCase):
    """Size-bound LRU eviction on every set()."""

    def setUp(self) -> None:
        _clear_cache()
        _config.reload_settings(cache_max_entries=3, cache_max_bytes=0)

    def tearDown(self) -> None:
        _clear_cache()

    def test_evicts_oldest_beyond_cap(self) -> None:
        import time

        for i in range(5):
            cache.set("ev", {"i": i}, {"data": i})
            time.sleep(0.02)
        remaining = [cache.get("ev", {"i": i}) for i in range(5)]
        present = [i for i, r in enumerate(remaining) if r is not None]
        self.assertEqual(present, [2, 3, 4])

    def test_collect_skips_non_json(self) -> None:
        cache.set("ev", {"k": 1}, {"data": 1})
        bad = Path(_config.CACHE_DIR or os.path.expanduser("~/.cache/web-research")) / "notes.txt"
        bad.write_text("ignore me")
        entries, _ = _collect_cache_entries(str(bad.parent))
        self.assertTrue(all(p.endswith(".json") for p, _, _ in entries))


class RobotsTests(unittest.TestCase):
    """robots.txt gate fails open when unreachable."""

    def setUp(self) -> None:
        from web_research.shared import robots

        robots.bust_cache()

    def test_unreachable_robots_allows(self) -> None:
        with patch("urllib.request.urlopen", side_effect=Exception("no net")):
            self.assertTrue(is_allowed("https://example.com/page"))

    def test_non_absolute_url_rejected(self) -> None:
        self.assertFalse(is_allowed("not-a-url"))
        self.assertFalse(is_allowed("/relative/path"))


class HtmlReaderTests(unittest.TestCase):
    """Stdlib HTML reader extracts title + visible text, strips noise."""

    def test_extracts_title_and_body(self) -> None:
        html = (
            "<html><head><title>My Page</title><style>x{}</style></head>"
            "<body><script>bad</script><h1>Hi</h1><p>Hello <b>world</b>.</p>"
            "<nav>menu</nav></body></html>"
        )
        md = _html_to_markdown(html)
        self.assertIn("# My Page", md)
        self.assertIn("Hello world.", md)
        self.assertNotIn("bad", md)  # script stripped
        self.assertNotIn("menu", md)  # nav stripped
        self.assertNotIn("{}", md)  # style stripped

    def test_empty_body_returns_empty(self) -> None:
        self.assertEqual(_html_to_markdown("<html><body></body></html>"), "")


class TeiRerankTests(unittest.TestCase):
    """TEI cross-encoder client degrades gracefully when disabled."""

    def setUp(self) -> None:
        _config.reload_settings(tei_rerank_url="")

    def test_disabled_returns_none(self) -> None:
        self.assertFalse(tei_rerank.tei_enabled())
        self.assertIsNone(tei_rerank.rerank("q", ["a", "b"]))

    def test_parse_scores_sorts_desc(self) -> None:
        data = {
            "results": [
                {"index": 2, "score": 0.9},
                {"index": 0, "score": 0.3},
                {"index": 1, "score": 0.7},
            ]
        }
        self.assertEqual(
            tei_rerank._parse_tei_scores(data),
            [(2, 0.9), (1, 0.7), (0, 0.3)],
        )

    def test_maybe_tei_noop_when_disabled(self) -> None:
        kept = [{"title": "a", "content": "x"}, {"title": "b", "content": "y"}]
        self.assertIs(_maybe_tei_rerank("q", kept), kept)

    def test_maybe_tei_reorders_when_enabled(self) -> None:
        _config.reload_settings(tei_rerank_url="http://tei:8081")
        kept = [{"title": "a", "content": "x"}, {"title": "b", "content": "y"}]
        scored = [(1, 0.9), (0, 0.2)]
        with patch("web_research.features.ranking.tei_rerank.rerank", return_value=scored):
            out = _maybe_tei_rerank("q", kept)
        self.assertEqual(out, [kept[1], kept[0]])


class DuckDuckGoTests(unittest.TestCase):
    """DDG redirect unwrap + HTML parsing."""

    def test_decode_uddg_redirect(self) -> None:
        href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc"
        self.assertEqual(_decode_ddg_href(href), "https://example.com/page")

    def test_decode_direct_url(self) -> None:
        self.assertEqual(
            _decode_ddg_href("https://plain.example.org/x"), "https://plain.example.org/x"
        )

    def test_parser_extracts_results(self) -> None:
        html = (
            '<div class="result">'
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2Fjson">Python json</a>'
            '<a class="result__snippet">JSON encoder and decoder.</a>'
            "</div>"
            '<div class="result">'
            '<a class="result__a" href="https://blog.example.org/post">Blog</a>'
            '<a class="result__snippet">A <b>short</b> snippet.</a>'
            "</div>"
        )
        parser = _DDGResultParser()
        parser.feed(html)
        parser.close()
        self.assertEqual(len(parser.results), 2)
        self.assertEqual(parser.results[0]["url"], "https://docs.python.org/json")
        self.assertEqual(parser.results[0]["title"], "Python json")
        self.assertIn("short", parser.results[1]["snippet"])


if __name__ == "__main__":
    unittest.main()
