"""Tests for synthesis, render-structured, and compact. Extracted from the former monolithic test_web_research.py."""
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

