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
from email.message import Message
from pathlib import Path
from typing import Literal, TextIO
from unittest.mock import patch

import web_research.shared.config as _config
from web_research.features.intelligence.code_analyze import (
    _count_refs,
    _is_identifier_candidate,
    _parse_location,
    enrich_with_local_code,
    extract_query_symbols,
    lookup_local_symbols,
)
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

    def __exit__(self, *args: object) -> Literal[False]:
        return False


def _headers(**values: str) -> Message:
    headers = Message()
    for name, value in values.items():
        headers[name.replace("_", "-")] = value
    return headers


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

        def side_effect(req: object, **_kwargs: object) -> _FakeResponse:
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

        def side_effect(req: urllib.request.Request, **_kwargs: object) -> object:
            calls["n"] += 1
            raise urllib.error.HTTPError(req.full_url, 404, "Nope", _headers(), None)

        with patch("urllib.request.urlopen", side_effect=side_effect):
            with self.assertRaises(urllib.error.HTTPError):
                UrllibHttpClient().get_bytes("http://x/")
        self.assertEqual(calls["n"], 1)

    def test_429_is_retried(self) -> None:
        calls = {"n": 0}

        def side_effect(req: urllib.request.Request, **_kwargs: object) -> object:
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.HTTPError(req.full_url, 429, "Slow", _headers(), None)
            return _FakeResponse(b"late")

        with patch("urllib.request.urlopen", side_effect=side_effect):
            body = UrllibHttpClient().get_bytes("http://x/")
        self.assertEqual(body, b"late")
        self.assertEqual(calls["n"], 3)

    def test_retry_after_parsed_and_capped(self) -> None:
        e5 = urllib.error.HTTPError("http://x", 429, "Slow", _headers(Retry_After="5"), None)
        self.assertEqual(_retry_after_seconds(e5), 5.0)
        e_huge = urllib.error.HTTPError("http://x", 429, "Slow", _headers(Retry_After="9999"), None)
        self.assertEqual(_retry_after_seconds(e_huge), 30.0)  # capped

    def test_retry_after_absent_or_garbage(self) -> None:
        none_hdr = urllib.error.HTTPError("http://x", 429, "Slow", _headers(), None)
        self.assertIsNone(_retry_after_seconds(none_hdr))
        junk = urllib.error.HTTPError(
            "http://x", 429, "Slow", _headers(Retry_After="Wed, 21 Oct"), None
        )
        self.assertIsNone(_retry_after_seconds(junk))  # HTTP-date form unsupported

    def test_non_http_urls_are_rejected_before_urlopen(self) -> None:
        with patch("urllib.request.urlopen") as mock_open:
            with self.assertRaisesRegex(ValueError, "absolute http"):
                UrllibHttpClient().get_bytes("file:///etc/passwd")
        mock_open.assert_not_called()


class ReaderChainTests(unittest.TestCase):
    """Fallback chain: Firecrawl down -> stdlib HTML reader succeeds."""

    def test_chain_falls_through_to_html(self) -> None:
        html_body = b"<html><head><title>Ex</title></head><body><p>Hi there</p></body></html>"

        def side_effect(req: urllib.request.Request, **_kwargs: object) -> object:
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
        _config.reload_settings()

    def test_evicts_oldest_beyond_cap(self) -> None:
        directory = Path(_config.CACHE_DIR or "~/.cache/web-research").expanduser()
        for i in range(5):
            cache.set("ev", {"i": i}, {"data": i})
            path = directory / cache._cache_key("ev", {"i": i})
            os.utime(path, ns=((i + 1) * 1_000_000_000, (i + 1) * 1_000_000_000))
        remaining = [cache.get("ev", {"i": i}) for i in range(5)]
        present = [i for i, r in enumerate(remaining) if r is not None]
        self.assertEqual(present, [2, 3, 4])

    def test_zero_entry_limit_keeps_multiple_entries_under_byte_budget(self) -> None:
        _config.reload_settings(cache_max_entries=0, cache_max_bytes=10_000_000)

        for i in range(3):
            cache.set("bytes-only", {"i": i}, {"data": i})

        self.assertEqual(
            [cache.get("bytes-only", {"i": i}) for i in range(3)],
            [{"data": 0}, {"data": 1}, {"data": 2}],
        )

    def test_both_disabled_limits_keep_multiple_entries(self) -> None:
        _config.reload_settings(cache_max_entries=0, cache_max_bytes=0)

        for i in range(3):
            cache.set("unlimited", {"i": i}, {"data": i})

        entries, _ = _collect_cache_entries(
            str(Path(_config.CACHE_DIR or "~/.cache/web-research").expanduser())
        )
        self.assertEqual(len(entries), 3)

    def test_cache_hit_promotes_entry_for_lru_eviction(self) -> None:
        _config.reload_settings(cache_max_entries=2, cache_max_bytes=0)
        cache.set("lru", {"key": "a"}, {"value": "a"})
        cache.set("lru", {"key": "b"}, {"value": "b"})
        directory = Path(_config.CACHE_DIR or "~/.cache/web-research").expanduser()
        path_a = directory / cache._cache_key("lru", {"key": "a"})
        path_b = directory / cache._cache_key("lru", {"key": "b"})
        os.utime(path_a, ns=(1_000_000_000, 1_000_000_000))
        os.utime(path_b, ns=(2_000_000_000, 2_000_000_000))

        self.assertEqual(cache.get("lru", {"key": "a"}), {"value": "a"})
        cache.set("lru", {"key": "c"}, {"value": "c"})

        self.assertIsNone(cache.get("lru", {"key": "b"}))
        self.assertEqual(cache.get("lru", {"key": "a"}), {"value": "a"})
        self.assertEqual(cache.get("lru", {"key": "c"}), {"value": "c"})

    def test_cache_hit_survives_recency_update_failure(self) -> None:
        cache.set("touch", {"key": 1}, {"value": "ok"})

        with patch("web_research.shared.cache.os.utime", side_effect=OSError("read-only")):
            self.assertEqual(cache.get("touch", {"key": 1}), {"value": "ok"})

    def test_collect_skips_non_json(self) -> None:
        cache.set("ev", {"k": 1}, {"data": 1})
        bad = Path(_config.CACHE_DIR or os.path.expanduser("~/.cache/web-research")) / "notes.txt"
        bad.write_text("ignore me")
        entries, _ = _collect_cache_entries(str(bad.parent))
        self.assertTrue(all(p.endswith(".json") for p, _, _ in entries))

    def test_failed_write_preserves_previous_complete_entry(self) -> None:
        params = {"k": "stable"}
        cache.set("atomic", params, {"value": "old"})

        def partial_then_fail(entry: object, stream: TextIO) -> None:
            del entry
            stream.write("{")
            raise OSError("simulated interrupted write")

        with (
            patch("web_research.shared.cache._evict_if_needed") as evict,
            patch("web_research.shared.cache.json.dump", side_effect=partial_then_fail),
        ):
            cache.set("atomic", params, {"value": "new"})

        self.assertEqual(cache.get("atomic", params), {"value": "old"})
        evict.assert_not_called()
        directory = Path(_config.CACHE_DIR or os.path.expanduser("~/.cache/web-research"))
        self.assertEqual(list(directory.glob("*.tmp")), [])


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


class CodeAnalyzeTests(unittest.TestCase):
    """Opt-in codeq fusion: symbol extraction + graceful subprocess paths."""

    def test_is_identifier_candidate(self) -> None:
        self.assertTrue(_is_identifier_candidate("BeautifulSoup"))
        self.assertTrue(_is_identifier_candidate("parse_html"))
        self.assertTrue(_is_identifier_candidate("rerank_results"))
        self.assertFalse(_is_identifier_candidate("requests"))  # pure lowercase prose
        self.assertFalse(_is_identifier_candidate("the"))  # stopword
        self.assertTrue(_is_identifier_candidate("GET"))  # uppercase → identifier-like

    def test_extract_query_symbols_filters_and_dedups(self) -> None:
        syms = extract_query_symbols(
            "How to use rerank_results and BeautifulSoup with rerank_results"
        )
        self.assertEqual(syms, ["rerank_results", "BeautifulSoup"])

    def test_extract_query_symbols_limit(self) -> None:
        syms = extract_query_symbols("Foo Bar Baz Qux Quux Corge", limit=3)
        self.assertEqual(len(syms), 3)

    def test_parse_location_first_file_line(self) -> None:
        out = "src/app.py:42  function  main\nsrc/other.py:7  function  main"
        self.assertEqual(_parse_location(out), "src/app.py:42")

    def test_count_refs_handles_none_and_lines(self) -> None:
        self.assertEqual(_count_refs(None), 0)
        self.assertEqual(_count_refs("a\nb\n\nc\n"), 3)  # blank line skipped

    def test_lookup_local_symbols_filters_unresolved(self) -> None:
        # find resolves for sym A only; sym B returns None (unresolved).
        def fake_run(args: list[str], timeout: float = 5.0) -> str | None:
            if args[0] == "find" and args[1] == "ResolvedSym":
                return "src/app.py:1  function  ResolvedSym"
            if args[0] == "refs" and args[1] == "ResolvedSym":
                return "src/caller.py:3  ResolvedSym()\nsrc/caller.py:9  ResolvedSym()"
            return None

        with patch(
            "web_research.features.intelligence.code_analyze._run_codeq", side_effect=fake_run
        ):
            hits = lookup_local_symbols(["ResolvedSym", "GhostSym"])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["symbol"], "ResolvedSym")
        self.assertEqual(hits[0]["location"], "src/app.py:1")
        self.assertEqual(hits[0]["refs"], 2)

    def test_enrich_empty_when_codeq_absent(self) -> None:
        with patch(
            "web_research.features.intelligence.code_analyze.codeq_available", return_value=None
        ):
            self.assertEqual(enrich_with_local_code("rerank_results"), "")

    def test_enrich_empty_when_no_symbols_resolve(self) -> None:
        with (
            patch(
                "web_research.features.intelligence.code_analyze.codeq_available",
                return_value="/fake/codeq",
            ),
            patch(
                "web_research.features.intelligence.code_analyze.lookup_local_symbols",
                return_value=[],
            ),
        ):
            self.assertEqual(enrich_with_local_code("rerank_results"), "")

    def test_enrich_renders_section_when_hits(self) -> None:
        hits = [{"symbol": "rerank_results", "location": "src/r.py:139", "refs": 10}]
        with (
            patch(
                "web_research.features.intelligence.code_analyze.codeq_available",
                return_value="/fake/codeq",
            ),
            patch(
                "web_research.features.intelligence.code_analyze.lookup_local_symbols",
                return_value=hits,
            ),
        ):
            out = enrich_with_local_code("rerank_results")
        self.assertIn("## Local code context (codeq)", out)
        self.assertIn("**rerank_results**", out)
        self.assertIn("`src/r.py:139`", out)
        self.assertIn("10 refs", out)

    def test_enrich_skips_prose_only_query(self) -> None:
        # Pure lowercase prose → no candidates → empty even if codeq present.
        with patch(
            "web_research.features.intelligence.code_analyze.codeq_available",
            return_value="/fake/codeq",
        ):
            self.assertEqual(enrich_with_local_code("how to use the tool"), "")


class CodeqSubprocessTests(unittest.TestCase):
    """_run_codeq degrades on every failure mode (no real subprocess invoked)."""

    def _proc(self, returncode: int, stdout: str) -> object:
        class _P:
            def __init__(self) -> None:
                self.returncode = returncode
                self.stdout = stdout

        return _P()

    def test_timeout_returns_none(self) -> None:
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="codeq", timeout=5)):
            from web_research.features.intelligence.code_analyze import _run_codeq

            self.assertIsNone(_run_codeq(["find", "x"]))

    def test_not_found_returns_none(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            from web_research.features.intelligence.code_analyze import _run_codeq

            self.assertIsNone(_run_codeq(["find", "x"]))

    def test_nonzero_returncode_returns_none(self) -> None:
        with patch("subprocess.run", return_value=self._proc(1, "")):
            from web_research.features.intelligence.code_analyze import _run_codeq

            self.assertIsNone(_run_codeq(["find", "GhostSym"]))

    def test_success_returns_stdout(self) -> None:
        with patch("subprocess.run", return_value=self._proc(0, "src/a.py:1  function  main\n")):
            from web_research.features.intelligence.code_analyze import _run_codeq

            self.assertEqual(_run_codeq(["find", "main"]), "src/a.py:1  function  main")


if __name__ == "__main__":
    unittest.main()
