"""Ollama wrapper: embed, generate, availability. CLI-agnostic."""

from __future__ import annotations

import math
import sys

# Ensure sibling scripts are importable when package is run from any cwd.
from .config import ECOSYSTEM_SCRIPTS  # sibling scripts dir (ollama_client, cheap_llm)

if ECOSYSTEM_SCRIPTS not in sys.path:
    sys.path.insert(0, ECOSYSTEM_SCRIPTS)

try:
    import ollama_client as oc
except Exception:  # pragma: no cover
    oc = None  # type: ignore[assignment]

from .config import OLLAMA_EMBED, OLLAMA_MODEL, OLLAMA_URL  # noqa: E402


def is_alive() -> bool:
    """Check if Ollama is reachable."""
    return oc is not None and oc.is_alive(base_url=OLLAMA_URL)


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

    ``model`` defaults to OLLAMA_MODEL (qwen3.5:4b). Callers that need a stronger
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
