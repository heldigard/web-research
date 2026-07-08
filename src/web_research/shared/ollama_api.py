"""Ollama wrapper: embed, generate, availability. CLI-agnostic."""

from __future__ import annotations

import math
import time as _time

from web_research.shared.compat import oc

from .config import OLLAMA_EMBED, OLLAMA_MODEL, OLLAMA_URL

# Short-TTL cache for is_alive() — avoids repeated HTTP pings in a single
# operation (research mode can call is_alive 2-3 times on one path).
_alive_at: float = 0.0
_alive_value: bool = False
_ALIVE_TTL: float = 30.0


def is_alive() -> bool:
    """Check if Ollama is reachable (30 s cache)."""
    global _alive_at, _alive_value
    now = _time.time()
    if now - _alive_at < _ALIVE_TTL:
        return _alive_value
    v = oc is not None and oc.is_alive(base_url=OLLAMA_URL)
    _alive_at = now
    _alive_value = v
    return v


def _bust_alive_cache() -> None:
    """Reset the ``is_alive`` cache (idempotent, called from test setUp)."""
    global _alive_at, _alive_value
    _alive_at = 0.0
    _alive_value = False


def embed(text: str) -> list[float] | None:
    """Embed text via local Ollama."""
    if oc is None:
        return None
    try:
        return oc.embed(text, model=OLLAMA_EMBED, base_url=OLLAMA_URL)
    except oc.OllamaUnavailable:  # type: ignore[union-attr]
        return None


def generate(
    prompt: str,
    system: str = "",
    temperature: float = 0.2,
    model: str | None = None,
) -> str | None:
    """Generate text via local Ollama.

    ``model`` defaults to OLLAMA_MODEL (cryptidbleh/gemma4-claude-opus-4.6:latest). Callers that need a stronger
    judgment model for the FINAL output (e.g. synthesis) pass OLLAMA_SYNTH_MODEL.
    """
    if oc is None or not is_alive():
        return None
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    try:
        return oc.generate(
            full_prompt,
            model=model or OLLAMA_MODEL,
            temperature=temperature,
            base_url=OLLAMA_URL,
            num_ctx=16384,
        )
    except oc.OllamaUnavailable:  # type: ignore[union-attr]
        return None


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
