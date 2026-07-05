"""Query intelligence: profiling, expansion, and focused extraction."""

from __future__ import annotations

import json
import re
from datetime import UTC

from web_research.shared.ollama_api import generate, is_alive

# ---------------------------------------------------------------
# Tuning constants for :func:`focused_extract`
# ---------------------------------------------------------------
_FOCUSED_MIN_TEXT_LEN = 800  # below this, return text as-is (no extraction needed)
_FOCUSED_LLM_CHARS = 6000  # max chars sent to the LLM extractor
_HEURISTIC_TOP_PARAGRAPHS = 4  # top-N paragraphs in deterministic fallback
_HEURISTIC_FALLBACK_CHARS = 1200  # first N chars when heuristic finds nothing


def _today() -> str:
    """Return current ISO date (runtime)."""
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y-%m-%d")


def query_profile(query: str) -> dict:
    """Classify a query so the engine can pick the best backend and format.

    Runs a tiny local prompt when Ollama is available; otherwise returns a
    conservative rule-based profile.
    """
    q = query.lower()
    default = {
        "intent": "general",
        "needs_recency": False,
        "preferred_sites": [],
        "expected_format": "snippet",
        "expand_queries": [query],
    }

    # Fast rule-based override first (cheap, deterministic).
    if any(w in q for w in ("error", "exception", "traceback", "failed", "bug")):
        default["intent"] = "troubleshooting"
        default["needs_recency"] = True
        default["preferred_sites"] = ["site:stackoverflow.com", "site:github.com"]
        default["expected_format"] = "step_list"
    elif any(w in q for w in ("docs", "api", "reference", "function", "method")):
        default["intent"] = "docs"
        default["preferred_sites"] = [
            "site:docs.python.org",
            "site:developer.mozilla.org",
        ]
        default["expected_format"] = "paragraph"
    elif {"vs", "versus", "compare", "difference", "mejor", "better"} & set(q.split()):
        default["intent"] = "comparison"
        default["expected_format"] = "table"
    elif any(w in q for w in ("latest", "news", "release", "announced", "2025", "2026")):
        default["intent"] = "news"
        default["needs_recency"] = True
        default["expected_format"] = "paragraph"

    if not is_alive():
        return default

    system = (
        "You are a query classifier. Reply ONLY with compact JSON. "
        "Fields: intent, needs_recency (bool), preferred_sites (list of site:...), "
        "expected_format (one of snippet/paragraph/table/step_list), expand_queries (list)."
    )
    prompt = f"Query: {query}\nToday: {_today()}\nReturn a JSON object with the fields above."
    raw = generate(prompt, system=system, temperature=0.0)
    if not raw:
        return default
    try:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
        profile = json.loads(cleaned)
        for key in default:
            profile.setdefault(key, default[key])
        if not isinstance(profile["expand_queries"], list) or not profile["expand_queries"]:
            profile["expand_queries"] = [query]
        return profile
    except (json.JSONDecodeError, TypeError):
        return default


def expand_queries(query: str, profile: dict | None = None) -> list[str]:
    """Return original query plus targeted variants (max 5 total)."""
    profile = profile or query_profile(query)
    out = [query]
    seen: set[str] = {query}
    eqs = profile.get("expand_queries") or []
    for v in eqs:
        v = v.strip()
        if v and v not in seen and len(out) < 5:
            seen.add(v)
            out.append(v)
    return out


def search_queries(query: str, profile: dict | None = None, max_queries: int = 4) -> list[str]:
    """Build the bounded query set used by smart search/research.

    LLM-generated expansions and preferred ``site:`` filters are useful, but
    unbounded fan-out makes agent tools slow and noisy. Keep the original query
    first, then add at most a few high-signal variants.
    """
    if max_queries <= 1:
        return [query]

    profile = profile or query_profile(query)
    out = expand_queries(query, profile)[:max_queries]
    seen = {q.lower() for q in out}

    for site in profile.get("preferred_sites") or []:
        site = str(site).strip()
        if not site.startswith("site:") or len(out) >= max_queries:
            continue
        variant = f"{query} {site}"
        key = variant.lower()
        if key not in seen:
            seen.add(key)
            out.append(variant)

    return out


def focused_extract(text: str, query: str, intent: str = "general") -> str:
    """Extract only the portion of a page relevant to the query.

    Falls back to a heuristic paragraph extraction if Ollama is unavailable.
    """
    if not text or len(text) <= _FOCUSED_MIN_TEXT_LEN:
        return text

    if not is_alive():
        return _heuristic_extract(text, query)

    system = (
        "You extract only information relevant to the user's query. "
        "Discard menus, ads, intros, and unrelated sections. "
        "Return: a concise answer (if any), one exact quote between quotes, "
        "and a note about date/version if present. If nothing is relevant, "
        "reply exactly: NO_RELEVANT_CONTENT."
    )
    prompt = (
        f"Query: {query}\nIntent: {intent}\nPage text:\n{text[:_FOCUSED_LLM_CHARS]}\n\nExtraction:"
    )
    raw = generate(prompt, system=system, temperature=0.1)
    if raw and "NO_RELEVANT_CONTENT" not in raw:
        return raw.strip()
    return _heuristic_extract(text, query)


def _heuristic_extract(text: str, query: str) -> str:
    """Fallback: keep paragraphs with highest keyword overlap."""
    query_words = set(query.lower().split())
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    scored = []
    for p in paragraphs:
        words = set(p.lower().split())
        overlap = len(words & query_words) / max(len(query_words), 1)
        scored.append((overlap, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    kept = [p for s, p in scored[:_HEURISTIC_TOP_PARAGRAPHS] if s > 0]
    return "\n\n".join(kept) if kept else text[:_HEURISTIC_FALLBACK_CHARS]
