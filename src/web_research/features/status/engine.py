"""Operational health probes for the local-first Ubuntu service stack.

The complement to ``capabilities``: where that command emits a static manifest
without touching the network, ``status`` actively probes the three self-hosted
services (SearXNG :8080, Firecrawl :3002, Ollama :11434), cross-checks the
configured Ollama models against the ones actually installed, and reports API
key / cache / cloud-fallback state. It answers "why did research fall back to
cloud?" or "why was rerank skipped?" without forcing the operator to curl each
service by hand.

Probes run concurrently with a short, bounded timeout. The HTTP client is
injectable so tests pass a fake instead of touching the network.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from web_research._version import __version__
from web_research.shared.cache import _cache_dir, _collect_cache_entries
from web_research.shared.compat import cheap_complete
from web_research.shared.config import SCHEMA_VERSION, get_settings
from web_research.shared.http import HttpClient, default_client

# Single-attempt probe budget. Kept short on purpose: every probe is to
# localhost, so a dead service fails fast (ECONNREFUSED) rather than hangs.
# Override per-call via the ``probe_timeout`` argument.
DEFAULT_PROBE_TIMEOUT = 3.0

# The local Firecrawl default key shipped with the engine. Status flags it so
# operators notice an unconfigured install without exposing the value.
_FC_DEFAULT_PLACEHOLDER = "fc-local-dev-key-2024"


def _timed_get_bytes(client: HttpClient, url: str, timeout: float) -> tuple[bool, int, str]:
    """GET ``url`` once, returning ``(ok, latency_ms, detail)``.

    Any exception (connection refused, timeout, HTTP error raised by the
    client's retry policy) collapses to ``ok=False`` with the error message.
    """
    start = time.perf_counter()
    try:
        client.get_bytes(url, timeout=timeout)
        latency = int((time.perf_counter() - start) * 1000)
        return True, latency, "ok"
    except Exception as e:  # noqa: BLE001 — diagnostic; never crash status
        latency = int((time.perf_counter() - start) * 1000)
        return False, latency, str(e)[:200]


def _timed_get_json(client: HttpClient, url: str, timeout: float) -> tuple[dict | None, int, str]:
    """GET JSON ``url`` once, returning ``(data_or_None, latency_ms, detail)``."""
    start = time.perf_counter()
    try:
        data = client.get_json(url, timeout=timeout)
        latency = int((time.perf_counter() - start) * 1000)
        return data, latency, "ok"
    except Exception as e:  # noqa: BLE001 — diagnostic; never crash status
        latency = int((time.perf_counter() - start) * 1000)
        return None, latency, str(e)[:200]


def probe_searxng(client: HttpClient, timeout: float) -> dict:
    settings = get_settings()
    ok, latency, detail = _timed_get_bytes(client, settings.searxng_url, timeout)
    return {"url": settings.searxng_url, "ok": ok, "latency_ms": latency, "detail": detail}


def probe_firecrawl(client: HttpClient, timeout: float) -> dict:
    settings = get_settings()
    ok, latency, detail = _timed_get_bytes(client, settings.firecrawl_url, timeout)
    return {"url": settings.firecrawl_url, "ok": ok, "latency_ms": latency, "detail": detail}


def probe_ollama(client: HttpClient, timeout: float) -> dict:
    """Probe Ollama and return installed model names alongside liveness."""
    settings = get_settings()
    tags_url = f"{settings.ollama_url}/api/tags"
    data, latency, detail = _timed_get_json(client, tags_url, timeout)
    if data is None:
        return {
            "url": settings.ollama_url,
            "ok": False,
            "latency_ms": latency,
            "models_installed": 0,
            "detail": detail,
        }
    installed = [str(m.get("name", "")) for m in (data.get("models") or []) if m.get("name")]
    return {
        "url": settings.ollama_url,
        "ok": True,
        "latency_ms": latency,
        "models_installed": len(installed),
        "models": installed,
        "detail": detail,
    }


def _installed_match(configured: str, installed_set: set[str]) -> bool:
    """True if ``configured`` resolves to an installed Ollama model.

    Ollama treats a bare name (``"embeddinggemma"``) as ``name:latest``, so both
    the exact tag and the implicit-``:latest`` form count as a hit. A configured
    name that already carries a tag (``"foo:q4"``) is matched verbatim.
    """
    if configured in installed_set:
        return True
    return ":" not in configured and f"{configured}:latest" in installed_set


def check_models(settings_fields: dict[str, str], installed: list[str]) -> dict[str, dict]:
    """Cross-check each configured model name against the installed set.

    ``settings_fields`` maps a friendly key (e.g. ``"synth"``) to the configured
    model name. Matching is tag-tolerant (see :func:`_installed_match`) because
    Ollama stores every model with a ``:tag`` suffix while config entries often
    omit the implicit ``:latest``.
    """
    installed_set = set(installed)
    return {
        key: {"configured": name, "installed": _installed_match(name, installed_set)}
        for key, name in settings_fields.items()
        if name  # skip empty configured-model placeholders
    }


def _configured_ollama_models() -> dict[str, str]:
    s = get_settings()
    return {
        "primary": s.ollama_model,
        "synth": s.ollama_synth_model,
        "synth_fallback": s.ollama_synth_fallback_model,
        "embed": s.ollama_embed,
    }


def _key_state() -> dict:
    s = get_settings()
    return {
        "minimax": bool(s.minimax_api_key),
        "zai": bool(s.zai_api_key),
        "firecrawl": bool(s.firecrawl_api_key),
        # Surface an unconfigured local Firecrawl without printing the key.
        "firecrawl_is_default_placeholder": s.firecrawl_api_key == _FC_DEFAULT_PLACEHOLDER,
    }


def _cloud_fallback_state() -> dict:
    s = get_settings()
    return {"available": cheap_complete is not None, "model": s.web_synth_cloud_model}


def _cache_state() -> dict:
    directory = _cache_dir()
    entries, total = _collect_cache_entries(directory)
    return {"dir": directory, "entries": len(entries), "bytes": total}


def status_payload(
    *, client: HttpClient | None = None, probe_timeout: float = DEFAULT_PROBE_TIMEOUT
) -> dict:
    """Assemble the full status envelope, probing services concurrently."""
    http_client = client or default_client()

    # ThreadPoolExecutor gives bounded parallelism across the three localhost
    # probes so a single slow service does not gate the others.
    probes = {
        "searxng": probe_searxng,
        "firecrawl": probe_firecrawl,
        "ollama": probe_ollama,
    }
    with ThreadPoolExecutor(max_workers=len(probes)) as ex:
        futures = {name: ex.submit(fn, http_client, probe_timeout) for name, fn in probes.items()}
        services = {name: fut.result() for name, fut in futures.items()}

    # The ollama probe returns the installed model names so the cross-check
    # below can match exact tags; the per-model installed flags carry the
    # actionable signal, so drop the verbose list from the service entry.
    installed_models = services["ollama"].pop("models", []) if services["ollama"].get("ok") else []

    return {
        "command": "status",
        "schema_version": SCHEMA_VERSION,
        "version": __version__,
        "generated_at": datetime.now(UTC).isoformat(),
        "probe_timeout_seconds": probe_timeout,
        "services": services,
        "models": check_models(_configured_ollama_models(), installed_models),
        "keys": _key_state(),
        "cloud_fallback": _cloud_fallback_state(),
        "cache": _cache_state(),
        "overall_ok": all(s["ok"] for s in services.values()),
    }
