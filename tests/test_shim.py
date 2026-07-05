from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def test_ecosystem_shim_imports_with_isolated_home(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/web-research-isolated-home")
    monkeypatch.delenv("WEB_RESEARCH_HOME", raising=False)

    shim = Path(__file__).resolve().parents[1] / "shims" / "web-research.py"
    spec = importlib.util.spec_from_file_location("web_research_ecosystem_shim", shim)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.main)
    assert os.environ["HOME"] == "/tmp/web-research-isolated-home"
