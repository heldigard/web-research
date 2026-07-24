"""Pytest config for web_research tests.

Runs before any test module is imported so the hermetic env pop happens before
the web_research settings singleton is built.
"""

import os

# Hermetic: the host shell may export SEARXNG_URL/FC_URL/OLLAMA_URL (e.g.
# 127.0.0.1 loopback binds); tests mock the canonical localhost URLs, so the
# ambient env must not leak into the settings singleton before import.
for _env in ("SEARXNG_URL", "FC_URL", "OLLAMA_URL"):
    os.environ.pop(_env, None)
