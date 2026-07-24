"""Ranking: semantic rerank, source-quality scoring, deduplication."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from functools import lru_cache
from importlib.resources import files  # nosemgrep: python37-compatibility-importlib2
from urllib.parse import urlparse

from web_research.shared.ollama_api import cosine, embed, is_alive

from . import tei_rerank

# ---------------------------------------------------------------------------
# Publication-date parsing (source recency — NOT event deadlines in prose)
# ---------------------------------------------------------------------------
# DDG and many meta-search hits leave ``publishedDate`` empty. News sites
# still encode the *publish* day in the URL path (``/2026/07/13/``) or an
# ISO stamp in the title. Prefer those over free-text "through July 19"
# phrases, which are often *deadlines inside the story*, not publish dates.
_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_URL_DATE_RE = re.compile(r"/(20\d{2})/(\d{1,2})/(\d{1,2})(?:/|$)")
_MONTH_MAP: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "ene": 1,
    "enero": 1,
    "feb": 2,
    "february": 2,
    "febrero": 2,
    "mar": 3,
    "march": 3,
    "marzo": 3,
    "apr": 4,
    "april": 4,
    "abr": 4,
    "abril": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "june": 6,
    "junio": 6,
    "jul": 7,
    "july": 7,
    "julio": 7,
    "aug": 8,
    "august": 8,
    "ago": 8,
    "agosto": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "septiembre": 9,
    "oct": 10,
    "october": 10,
    "octubre": 10,
    "nov": 11,
    "november": 11,
    "noviembre": 11,
    "dec": 12,
    "december": 12,
    "dic": 12,
    "diciembre": 12,
}
_MONTH_DAY_RE = re.compile(
    r"\b("
    + "|".join(sorted(_MONTH_MAP, key=len, reverse=True))
    + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(20\d{2}))?\b",
    re.IGNORECASE,
)
# Half-life of recency boost in days: score halves every ~14 days.
_RECENCY_HALFLIFE_DAYS = 14.0

# A small English stopword set — enough to stop "the/for/how" from dominating
# the title↔content overlap signal. Kept inline (not a data file) because it is
# a fixed linguistic constant, not a user-editable list like authority domains.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "as",
        "at",
        "from",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "how",
        "what",
        "when",
        "where",
        "why",
        "which",
        "who",
        "do",
        "does",
        "did",
        "can",
        "your",
        "you",
        "vs",
        "versus",
    }
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, drop stopwords + single chars.

    Replaces the old ``set(text.lower().split())`` which kept punctuation
    tokens and stopwords, diluting the overlap signal (``"rust?"`` and
    ``"rust"`` counted as different tokens).
    """
    return {
        tok for tok in _WORD_RE.findall(text.lower()) if len(tok) >= 2 and tok not in _STOPWORDS
    }


@lru_cache(maxsize=1)
def _load_authority_domains() -> frozenset[str]:
    """Load authority domains from the packaged data file (memoized).

    ``lru_cache(maxsize=1)`` replaces a manual function-attribute cache: the
    data file is read at most once per process and the result (including the
    empty-set fallback) is reused. Falls back to an empty set if the resource
    is missing (e.g. an exotic install layout) so the score degrades gracefully
    instead of crashing.
    """
    try:
        raw = (
            files("web_research.features.ranking.data")
            .joinpath("authority_domains.txt")
            .read_text(encoding="utf-8")
        )
        return frozenset(
            line.strip().lower()
            for line in raw.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    except Exception:  # noqa: BLE001 — resource missing; degrade, don't crash
        return frozenset()


def source_quality_score(url: str, title: str, content: str) -> float:
    """Score a source by domain authority and content specificity.

    Returns a value between 0 and 1.
    """
    if not url:
        return 0.0
    domain = urlparse(url).netloc.lower()
    authority_domains = _load_authority_domains()
    score = 0.0
    if any(domain == d or domain.endswith("." + d) for d in authority_domains):
        score += 0.4
    if "blog" in domain or "medium.com" in domain:
        score += 0.1
    if len(content) >= 80:
        score += 0.2
    if title and query_word_overlap(title, content) > 0.3:
        score += 0.2
    if "/docs/" in url or "reference" in url.lower():
        score += 0.2
    return min(score, 1.0)


def query_word_overlap(title: str, content: str) -> float:
    """Token-overlap relevance heuristic (punctuation- and stopword-aware)."""
    title_words = _tokenize(title)
    content_words = _tokenize(content)
    if not title_words:
        return 0.0
    overlap = title_words & content_words
    return len(overlap) / len(title_words)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_date_string(raw: str) -> date | None:
    """Parse a free-form date string (ISO first, then Month Day Year)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    # ISO prefix (optionally with time)
    m = _ISO_DATE_RE.search(raw)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if re.match(r"^\d{4}/\d{2}/\d{2}", raw):
        parts = raw[:10].split("/")
        return _safe_date(int(parts[0]), int(parts[1]), int(parts[2]))
    m = _MONTH_DAY_RE.search(raw)
    if m:
        month = _MONTH_MAP[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else date.today().year
        return _safe_date(year, month, day)
    return None


def parse_result_date(result: dict) -> date | None:
    """Best-effort *publication* date for a search hit.

    Preference order:
      1. Explicit ``publishedDate`` / ``published_date`` field from the engine
      2. URL path ``/YYYY/MM/DD/`` (common on news CMS)
      3. ISO date in title
      4. Month+day in title (year defaults to current)

    Snippet body is intentionally ignored: it often contains *event* dates
    (``through July 12``) that would invert recency for update articles.
    """
    for key in ("publishedDate", "published_date", "date"):
        parsed = _parse_date_string(str(result.get(key) or ""))
        if parsed:
            return parsed
    url = str(result.get("url") or "")
    m = _URL_DATE_RE.search(url)
    if m:
        parsed = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if parsed:
            return parsed
    title = str(result.get("title") or "")
    # ISO in title is usually a real publish stamp ("2026-07-13 update").
    m = _ISO_DATE_RE.search(title)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # Month+day in title is often an *event* deadline ("Extends To July 19"),
    # not the publish day. Only trust it when a 4-digit year is also present
    # ("July 13, 2026") so we do not promote the deadline over a real CMS date.
    m = _MONTH_DAY_RE.search(title)
    if m and m.group(3):
        month = _MONTH_MAP[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3))
        return _safe_date(year, month, day)
    return None


def recency_score(when: date | None, *, today: date | None = None) -> float:
    """Map a publish date to a 0..1 freshness score (1 = today, ~0 after months).

    Uses exponential decay with a ~14-day half-life so a 6-day-older article
    (Jul 7 vs Jul 13) loses a clear but not catastrophic amount of score —
    enough to break near-ties without burying evergreen docs when the weight
    is modest.
    """
    if when is None:
        return 0.0
    today = today or datetime.now(UTC).date()
    age = (today - when).days
    if age < 0:
        # Future-dated CMS stamps: treat as "today" (do not reward)
        age = 0
    # score = 0.5 ** (age / half_life)
    return float(0.5 ** (age / _RECENCY_HALFLIFE_DAYS))


def _is_newer(a: dict, b: dict) -> bool:
    """True when ``a`` has a strictly newer known publish date than ``b``."""
    da, db = parse_result_date(a), parse_result_date(b)
    if da is None or db is None:
        return False
    return da > db


def select_with_recency_diversity(
    results: list[dict],
    k: int,
) -> list[dict]:
    """Pick top-``k`` hits but force-include the freshest in the top 2k pool.

    When near-duplicate news updates exist (same story, later publish day),
    pure top-k by score can keep only the older one. This guarantees the
    newest dated candidate in the local pool is among the scraped set.
    """
    if k <= 0 or not results:
        return []
    if len(results) <= k:
        return list(results)
    pool = results[: min(len(results), max(k * 2, k))]
    selected = list(results[:k])
    dated = [(parse_result_date(r), r) for r in pool]
    known_dated = [(d, r) for d, r in dated if d is not None]
    if not known_dated:
        return selected
    _, newest = max(known_dated, key=lambda item: item[0])
    if any(r is newest or r.get("url") == newest.get("url") for r in selected):
        return selected
    # Replace the lowest-ranked selected item with the newest candidate.
    selected[-1] = newest
    return selected


def rerank_results(
    query: str,
    results: list[dict],
    sim_cutoff: float = 0.93,
    quality_weight: float = 0.3,
    recency_weight: float = 0.0,
) -> list[dict]:
    """Order by composite score (sim + quality [+ recency]); drop near-duplicates.

    Embeds are parallelized (ThreadPoolExecutor) instead of sequential N+1 calls.
    ``_quality`` is reused if already present (set by ``annotate_quality``).

    ``recency_weight`` (0..~0.4) mixes in :func:`recency_score` derived from
    publish dates. Use ~0.25 for news/recency-sensitive queries; a mild 0.1
    is safe as a default boost for general search. Near-duplicate collapse
    **prefers the newer article** when both have parseable dates — this is
    what fixes "July 7 extension story survives, July 13 update is dropped".
    """
    if not results:
        return results
    # Normalize weights so sim+quality+recency sum to 1 when recency is on.
    recency_weight = max(0.0, min(float(recency_weight), 0.5))
    quality_weight = max(0.0, min(float(quality_weight), 1.0 - recency_weight))
    sim_weight = max(0.0, 1.0 - quality_weight - recency_weight)

    qv = embed(query) if is_alive() else None
    texts = [r["title"] + ". " + r["content"][:300] for r in results]
    if qv:
        with ThreadPoolExecutor(max_workers=min(len(results), 4) or 1) as ex:
            vecs = list(ex.map(embed, texts))
    else:
        vecs = [None] * len(results)
    for r, v in zip(results, vecs, strict=True):
        sim = cosine(qv, v) if qv and v else 0.0
        quality = r.get("_quality")
        if quality is None:
            quality = source_quality_score(r.get("url", ""), r["title"], r["content"])
        pub = parse_result_date(r)
        fresh = recency_score(pub)
        r["_score"] = sim_weight * sim + quality_weight * quality + recency_weight * fresh
        r["_v"] = v
        r["_pub_date"] = pub.isoformat() if pub else ""

    results.sort(key=lambda r: r["_score"], reverse=True)

    kept: list[dict] = []
    for r in results:
        dup_idx = None
        for i, k in enumerate(kept):
            if r["_v"] and k.get("_v") and cosine(r["_v"], k["_v"]) >= sim_cutoff:
                dup_idx = i
                break
        if dup_idx is None:
            kept.append(r)
            continue
        # Near-duplicate: keep the newer publish date when known; otherwise
        # the earlier (higher-score) survivor stands.
        if _is_newer(r, kept[dup_idx]):
            kept[dup_idx] = r

    # Optional stage-2: a TEI cross-encoder re-orders the survivors. Disabled
    # (TEI_RERANK_URL unset) or unreachable -> no-op, bi-encoder order stands.
    kept = _maybe_tei_rerank(query, kept)

    for r in results:
        r.pop("_v", None)
        r.pop("_score", None)
        # Leave ``_pub_date`` for formatters/agents; strip only internal vectors.
    return kept


def _maybe_tei_rerank(query: str, kept: list[dict]) -> list[dict]:
    """Apply TEI cross-encoder rerank to ``kept`` when enabled; else pass-through.

    TEI scores ``(query, doc)`` pairs jointly and returns ``[{index, score}]``
    over the same list order it received. Docs it did not score are appended at
    the end in their prior bi-encoder order so none are dropped.
    """
    if len(kept) <= 1 or not tei_rerank.tei_enabled():
        return kept
    texts = [r["title"] + ". " + r["content"][:300] for r in kept]
    scored = tei_rerank.rerank(query, texts)
    if not scored:
        return kept
    returned = {idx for idx, _ in scored}
    ordered = [kept[idx] for idx, _ in scored if 0 <= idx < len(kept)]
    for idx, r in enumerate(kept):
        if idx not in returned:
            ordered.append(r)
    return ordered


def annotate_quality(results: list[dict]) -> list[dict]:
    """Attach a ``_quality`` score to each result (domain authority + specificity)."""
    for r in results:
        r["_quality"] = source_quality_score(
            r.get("url", ""), r.get("title", ""), r.get("content", "")
        )
    return results
