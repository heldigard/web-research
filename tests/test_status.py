"""Tests for status/health probes. Extracted from the former monolithic test_web_research.py."""
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


class StatusTests(unittest.TestCase):
    """Operational health probes for the local service stack."""

    def setUp(self):
        _clear_cache()

    def _client(self, *, ollama_up=True, installed_models=None):
        routes: dict[str, bytes | dict] = {
            _config.SEARXNG_URL: b"OK",
            _config.FC_URL: b"OK",
        }
        if ollama_up:
            routes[f"{_config.OLLAMA_URL}/api/tags"] = _ollama_tags(installed_models or [])
        raise_on = () if ollama_up else ("/api/tags",)
        return _FakeHttpClient(routes, raise_on=raise_on)

    def test_payload_shape_and_overall_ok(self):
        from web_research.features.status.engine import status_payload

        installed = [
            _config.OLLAMA_MODEL,
            _config.OLLAMA_SYNTH_MODEL,
            _config.OLLAMA_SYNTH_FALLBACK_MODEL,
            "embeddinggemma:latest",
        ]
        payload = status_payload(client=self._client(installed_models=installed), probe_timeout=1.0)
        self.assertEqual(payload["command"], "status")
        self.assertEqual(payload["schema_version"], _config.SCHEMA_VERSION)
        self.assertTrue(payload["overall_ok"])
        for name in ("searxng", "firecrawl", "ollama"):
            self.assertTrue(payload["services"][name]["ok"], name)
        self.assertFalse(payload["cloud_fallback"]["enabled_by_default"])
        self.assertEqual(
            payload["cloud_fallback"]["opt_in_flag"], "--allow-cloud-fallback"
        )
        # Verbose installed model list must not leak into the service entry.
        self.assertNotIn("models", payload["services"]["ollama"])

    def test_missing_model_flagged(self):
        from web_research.features.status.engine import status_payload

        # Only the primary model is installed; the rest should be MISSING.
        payload = status_payload(
            client=self._client(installed_models=[_config.OLLAMA_MODEL]), probe_timeout=1.0
        )
        models = payload["models"]
        self.assertTrue(models["primary"]["installed"])
        self.assertFalse(models["synth"]["installed"])
        self.assertFalse(models["embed"]["installed"])

    def test_tag_tolerant_match(self):
        # Bare configured name resolves to the implicit :latest tag.
        from web_research.features.status.engine import _installed_match, check_models

        self.assertTrue(_installed_match("embeddinggemma", {"embeddinggemma:latest"}))
        self.assertFalse(_installed_match("embeddinggemma", {"other:latest"}))
        # An explicit configured tag matches verbatim only.
        self.assertTrue(_installed_match("foo:q4", {"foo:q4"}))
        self.assertFalse(_installed_match("foo:q4", {"foo:latest"}))
        result = check_models({"embed": "embeddinggemma"}, ["embeddinggemma:latest"])
        self.assertTrue(result["embed"]["installed"])

    def test_ollama_down_marked_and_exit_nonzero(self):
        from web_research.features.status.command import mode_status
        from web_research.features.status.engine import status_payload

        payload = status_payload(client=self._client(ollama_up=False), probe_timeout=1.0)
        self.assertFalse(payload["services"]["ollama"]["ok"])
        self.assertFalse(payload["overall_ok"])

        # mode_status builds its own payload with the default client; inject the
        # prebuilt down-payload so the exit-code gate is exercised deterministically.
        args = Namespace(json=True, no_cache=False, timeout=None, verbose=False)
        buf = io.StringIO()
        with patch("web_research.features.status.command.status_payload", lambda **_kw: payload):
            with redirect_stdout(buf):
                rc = mode_status(args)
        self.assertEqual(rc, 1)  # non-zero so scripts/agents can gate on it
        out = json.loads(buf.getvalue())
        self.assertFalse(out["overall_ok"])

    def test_human_render_verdict_and_exit_zero(self):
        from web_research.features.status.command import mode_status
        from web_research.features.status.engine import status_payload

        installed = [
            _config.OLLAMA_MODEL,
            _config.OLLAMA_SYNTH_MODEL,
            _config.OLLAMA_SYNTH_FALLBACK_MODEL,
            "embeddinggemma:latest",
        ]
        prebuilt = status_payload(
            client=self._client(installed_models=installed), probe_timeout=1.0
        )
        # mode_status builds its own payload; inject the prebuilt one so the
        # human renderer is exercised without touching the network.
        with patch("web_research.features.status.command.status_payload", lambda **_kw: prebuilt):
            args = Namespace(json=False, no_cache=False, timeout=None, verbose=False)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = mode_status(args)
        self.assertEqual(rc, 0)
        self.assertIn("ALL SERVICES OK", buf.getvalue())
