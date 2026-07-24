"""Pytest config for web_research tests.

Runs before any test module is imported so the hermetic env pop happens before
the web_research settings singleton is built.
"""

import atexit
import os
import shutil
import tempfile

# Hermetic: the host shell may export SEARXNG_URL/FC_URL/OLLAMA_URL (e.g.
# 127.0.0.1 loopback binds); tests mock the canonical localhost URLs, so the
# ambient env must not leak into the settings singleton before import.
for _env in ("SEARXNG_URL", "FC_URL", "OLLAMA_URL"):
    os.environ.pop(_env, None)

# Never read, clear, or populate the user's real web-research cache. A unique
# directory per pytest process also keeps parallel Python-version runs from
# observing each other's files.
_TEST_CACHE_DIR = tempfile.mkdtemp(prefix="web-research-tests-")
os.environ["WEB_RESEARCH_CACHE_DIR"] = _TEST_CACHE_DIR
atexit.register(shutil.rmtree, _TEST_CACHE_DIR, ignore_errors=True)
