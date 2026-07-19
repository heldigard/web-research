"""Query intelligence: profiling, expansion, and focused extraction."""

from __future__ import annotations

import re
from datetime import UTC

from web_research.shared.json_utils import extract_json_object
from web_research.shared.ollama_api import generate, is_alive

# ---------------------------------------------------------------
# Tuning constants for :func:`focused_extract`
# ---------------------------------------------------------------
_FOCUSED_MIN_TEXT_LEN = 800  # below this, return text as-is (no extraction needed)
_FOCUSED_LLM_CHARS = 6000  # max chars sent to the LLM extractor
_HEURISTIC_TOP_PARAGRAPHS = 4  # top-N paragraphs in deterministic fallback
_HEURISTIC_FALLBACK_CHARS = 1200  # first N chars when heuristic finds nothing
_VALID_INTENTS = frozenset({"general", "troubleshooting", "docs", "comparison", "news"})
_VALID_FORMATS = frozenset({"snippet", "paragraph", "table", "step_list"})


def _has_any(text: str, words: tuple[str, ...] | list[str]) -> bool:
    """True if any whole word/phrase appears in ``text`` (not bare substrings).

    Prevents ``"api" in "fastapi"`` false positives that mis-classify
    comparison queries as docs.
    """
    for word in words:
        word = word.strip().lower()
        if not word:
            continue
        if " " in word:
            if word in text:
                return True
            continue
        if re.search(rf"(?<![a-z0-9_]){re.escape(word)}(?![a-z0-9_])", text):
            return True
    return False


def _string_list(value: object, fallback: object, *, allow_empty: bool = False) -> list[str]:
    """Return stripped string items from ``value`` or a safe fallback list."""
    items = value if isinstance(value, list) else []
    cleaned = [item.strip() for item in items if isinstance(item, str) and item.strip()]
    if cleaned or (allow_empty and isinstance(value, list)):
        return cleaned
    fallback_items = fallback if isinstance(fallback, list) else []
    return [item for item in fallback_items if isinstance(item, str)]


def _enum_value(value: object, fallback: object, allowed: frozenset[str]) -> str:
    """Return a known string enum value, otherwise the deterministic fallback."""
    if isinstance(value, str) and value in allowed:
        return value
    return fallback if isinstance(fallback, str) else ""


def _normalize_profile(raw: object, fallback: dict[str, object]) -> dict[str, object]:
    """Normalize untrusted model output without mutating it or ``fallback``."""
    source = raw if isinstance(raw, dict) else {}
    recency = source.get("needs_recency")
    return {
        "intent": _enum_value(source.get("intent"), fallback["intent"], _VALID_INTENTS),
        "needs_recency": (recency if type(recency) is bool else bool(fallback["needs_recency"])),
        "preferred_sites": _string_list(
            source.get("preferred_sites"), fallback["preferred_sites"], allow_empty=True
        ),
        "expected_format": _enum_value(
            source.get("expected_format"), fallback["expected_format"], _VALID_FORMATS
        ),
        "expand_queries": _string_list(source.get("expand_queries"), fallback["expand_queries"]),
    }


def _today() -> str:
    """Return current ISO date (runtime)."""
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y-%m-%d")


def _docs_preferred_sites(query_lower: str) -> list[str]:
    """Pick docs-oriented site filters from cheap language hints in the query."""
    sites = ["site:stackoverflow.com", "site:github.com"]
    if _has_any(query_lower, ("python", "django", "flask", "fastapi", "pytest")):
        sites.insert(0, "site:docs.python.org")
    if _has_any(query_lower, ("javascript", "typescript", "node", "react", "css", "html")):
        sites.insert(0, "site:developer.mozilla.org")
    if _has_any(query_lower, ("rust", "cargo", "crate")):
        sites.insert(0, "site:doc.rust-lang.org")
    if _has_any(query_lower, ("golang", "go")):
        sites.insert(0, "site:pkg.go.dev")
    if _has_any(query_lower, ("java", "spring", "jvm", "kotlin")):
        sites.insert(0, "site:docs.oracle.com")
    # De-dupe while preserving order; cap so search fan-out stays small.
    out: list[str] = []
    seen: set[str] = set()
    for s in sites:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:4]


def _looks_like_product_news(query_lower: str) -> bool:
    """Heuristic: AI model / vendor product windows need fresh sources.

    Controllers often ask ``"Fable 5 Anthropic"`` without the word "news". That
    query is *about a live product window*, not evergreen API docs — without
    this, ranking treats July 7 and July 19 extension stories as evergreen
    and the older headline can win.

    Kept narrow on purpose: bare ``google 3`` / ``meta 2`` must not flip to
    news (too many false positives). Prefer explicit model/vendor tokens.
    """
    # Direct model families (version optional)
    if _has_any(
        query_lower,
        (
            "claude",
            "gpt",
            "gemini",
            "llama",
            "grok",
            "fable",
            "mythos",
            "sonnet",
            "opus",
            "haiku",
            "chatgpt",
            "o1",
            "o3",
            "o4",
        ),
    ):
        return True
    # Vendor + version/codename (avoid "google chrome 3" style FPs: require
    # an AI-ish companion token, not just any digit).
    if _has_any(query_lower, ("anthropic", "openai", "mistral", "xai", "deepseek")):
        if _has_any(
            query_lower,
            ("model", "release", "preview", "beta", "api", "checkpoint", "weights"),
        ) or re.search(r"\b(v?\d+(?:\.\d+)*)\b", query_lower):
            return True
    return False


def query_profile(query: str) -> dict:
    """Classify a query so the engine can pick the best backend and format.

    Runs a tiny local prompt when Ollama is available; otherwise returns a
    conservative rule-based profile.
    """
    q = query.lower()
    default: dict[str, object] = {
        "intent": "general",
        "needs_recency": False,
        "preferred_sites": [],
        "expected_format": "snippet",
        "expand_queries": [query],
    }

    # Fast rule-based override first (cheap, deterministic).
    # EN + ES triggers: controllers in this ecosystem often query in Spanish.
    # Comparison is checked before docs so "fastapi vs django" is not stolen
    # by the substring "api" inside "fastapi".
    tokens = set(q.split())
    if _has_any(
        q,
        (
            "error",
            "exception",
            "traceback",
            "failed",
            "bug",
            "fallo",
            "falló",
            "falla",
            "traza",
            "excepción",
            "excepcion",
            "rompe",
            "crash",
        ),
    ):
        default["intent"] = "troubleshooting"
        default["needs_recency"] = True
        default["preferred_sites"] = ["site:stackoverflow.com", "site:github.com"]
        default["expected_format"] = "step_list"
    elif tokens & {
        "vs",
        "versus",
        "compare",
        "comparison",
        "difference",
        "differences",
        "mejor",
        "better",
        "comparar",
        "comparación",
        "comparacion",
        "diferencia",
        "diferencias",
        "contra",
    }:
        default["intent"] = "comparison"
        default["expected_format"] = "table"
    elif _has_any(
        q,
        (
            "docs",
            "api",
            "reference",
            "function",
            "method",
            "documentación",
            "documentacion",
            "referencia",
            "función",
            "funcion",
            "método",
            "metodo",
        ),
    ):
        default["intent"] = "docs"
        default["preferred_sites"] = _docs_preferred_sites(q)
        default["expected_format"] = "paragraph"
    elif _has_any(
        q,
        (
            "latest",
            "news",
            "release",
            "announced",
            "2025",
            "2026",
            "últimas",
            "ultimas",
            "noticias",
            "reciente",
            "recientes",
            "novedades",
            "lanzamiento",
            "changelog",
            # Availability / window / extension queries — these go stale fast
            # (e.g. "Fable 5 extends to July 19" superseding a July 7 note).
            "extends",
            "extended",
            "extension",
            "deadline",
            "until",
            "cutoff",
            "redeploy",
            "redeploying",
            "available until",
            "free window",
            "prórroga",
            "prorroga",
            "hasta cuándo",
            "hasta cuando",
            "disponible",
            "disponibilidad",
        ),
    ):
        default["intent"] = "news"
        default["needs_recency"] = True
        default["expected_format"] = "paragraph"
    elif _looks_like_product_news(q):
        # "claude fable 5", "gpt-5 release status" without explicit "news"
        # still need fresh sources — product windows move under our feet.
        default["intent"] = "news"
        default["needs_recency"] = True
        default["expected_format"] = "paragraph"
    elif _has_any(
        q,
        (
            "how to",
            "howto",
            "how do i",
            "cómo",
            "como",
            "paso a paso",
            "tutorial",
        ),
    ):
        default["intent"] = "troubleshooting"  # procedural → step_list
        default["expected_format"] = "step_list"

    if not is_alive():
        return default

    system = (
        "You are a query classifier. Reply ONLY with compact JSON. "
        "Fields: intent, needs_recency (bool), preferred_sites (list of site:...), "
        "expected_format (one of snippet/paragraph/table/step_list), expand_queries (list). "
        "Set needs_recency=true for product availability windows, model launches, "
        "deadlines, extensions, and anything that goes stale within days."
    )
    prompt = f"Query: {query}\nToday: {_today()}\nReturn a JSON object with the fields above."
    raw = generate(prompt, system=system, temperature=0.0)
    if not raw:
        return default
    profile = _normalize_profile(extract_json_object(raw), default)
    # Heuristic floor: rule-based recency/news must not be downgraded by a
    # casual LLM classification (the Fable-5 evergreen mis-tag). The model may
    # still *raise* recency or refine expand_queries / preferred_sites.
    if default.get("needs_recency"):
        profile["needs_recency"] = True
    if default.get("intent") == "news" and profile.get("intent") == "general":
        profile["intent"] = "news"
    return profile


def expand_queries(query: str, profile: dict | None = None) -> list[str]:
    """Return original query plus targeted variants (max 5 total)."""
    profile = profile or query_profile(query)
    out = [query]
    seen: set[str] = {query}
    raw_eqs = profile.get("expand_queries") or []
    eqs = raw_eqs if isinstance(raw_eqs, list) else []
    for v in eqs:
        if not isinstance(v, str):
            continue
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

    raw_sites = profile.get("preferred_sites") or []
    sites = raw_sites if isinstance(raw_sites, list) else []
    for site in sites:
        if not isinstance(site, str):
            continue
        site = site.strip()
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
