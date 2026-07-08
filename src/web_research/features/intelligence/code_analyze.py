"""Opt-in fusion of web research with local code intelligence.

``research --code-analyze`` looks up candidate identifiers from the query in the
current working directory via the ``codeq`` CLI. Resolved hits are appended to
the scraped doc as a ``## Local code context (codeq)`` section so synthesis
sees real file locations and call-site counts alongside the web prose.

This is the honest scope for the integration: ``codeq`` operates on the local
repo (CWD), not on arbitrary scraped text. The value is fusing web findings
about an API/library with how that symbol is actually used in the caller's own
code. When ``codeq`` is absent or a symbol does not resolve locally — the common
case when researching a third-party library from an unrelated directory — the
enrichment degrades to an empty string (no error, no spurious section).
"""

from __future__ import annotations

import re
import shutil
import subprocess

# Identifier-like tokens: letter/underscore start, >=3 chars, alnum/underscore body.
_QUERY_SYM_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
# A token counts as a candidate if it contains an underscore OR an uppercase
# letter — pure-lowercase words are almost always prose ("get", "use", "data").
_IDENTIFIERISH_RE = re.compile(r"[_A-Z]")
# Common English words that happen to match the identifier shape.
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "use",
        "using",
        "how",
        "what",
        "when",
        "why",
        "who",
        "can",
        "you",
        "your",
        "are",
        "not",
        "but",
        "all",
        "any",
        "has",
        "have",
        "was",
        "will",
        "its",
    }
)

_CODEQ_TIMEOUT = 5.0  # seconds per subprocess call; codeq find/refs is fast (no LLM)


def codeq_available() -> str | None:
    """Return the codeq executable path if on PATH, else None."""
    return shutil.which("codeq")


def _is_identifier_candidate(tok: str) -> bool:
    """True if a token looks like an identifier (not prose/stopword/digit)."""
    low = tok.lower()
    if low in _STOPWORDS or low.isdigit():
        return False
    return bool(_IDENTIFIERISH_RE.search(tok))


def extract_query_symbols(query: str, limit: int = 5) -> list[str]:
    """Pick identifier-like tokens out of a natural-language query.

    Keeps order of first appearance, dedups, drops stopwords and pure-prose
    lowercase words. ``limit`` bounds the number of codeq lookups.
    """
    candidates = [t for t in _QUERY_SYM_RE.findall(query) if _is_identifier_candidate(t)]
    unique = list(dict.fromkeys(candidates))  # order-preserving dedup, no loop
    return unique[:limit]


def _run_codeq(args: list[str], timeout: float = _CODEQ_TIMEOUT) -> str | None:
    """Run a codeq subcommand; return stripped stdout or None on any failure."""
    try:
        proc = subprocess.run(
            ["codeq", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip()


def _parse_location(find_output: str) -> str:
    """Extract the first ``file:line`` from a ``codeq find`` block."""
    first_line = find_output.splitlines()[0]
    return first_line.split()[0] if first_line.split() else ""


def _count_refs(refs_output: str | None) -> int:
    """Count non-empty reference lines (grep-style output; lexical, includes comments)."""
    if not refs_output:
        return 0
    return sum(1 for line in refs_output.splitlines() if line.strip())


def _lookup_one_symbol(sym: str, project: str) -> dict | None:
    """Resolve a single symbol locally; return a hit record or None."""
    found = _run_codeq(["find", sym, "-p", project])
    if not found:
        return None
    refs = _run_codeq(["refs", sym, "-p", project])
    return {
        "symbol": sym,
        "location": _parse_location(found),
        "refs": _count_refs(refs),
    }


def lookup_local_symbols(symbols: list[str], project: str = ".") -> list[dict]:
    """Resolve each symbol in the local repo; return hit records.

    A hit record is ``{"symbol", "location", "refs"}`` where ``location`` is the
    first ``file:line`` from ``codeq find`` and ``refs`` is the call-site line
    count from ``codeq refs``. Symbols that do not resolve are skipped silently.
    """
    return list(filter(None, (_lookup_one_symbol(s, project) for s in symbols)))


def enrich_with_local_code(query: str, project: str = ".") -> str:
    """Return a markdown section fusing local codeq facts, or ``""`` if none.

    No-op (returns empty) when codeq is absent, when the query yields no
    identifier-like candidates, or when none of them resolve locally.
    """
    if not codeq_available():
        return ""
    symbols = extract_query_symbols(query)
    if not symbols:
        return ""
    hits = lookup_local_symbols(symbols, project)
    if not hits:
        return ""
    lines = ["", "## Local code context (codeq)", ""]
    for h in hits:
        loc = f"`{h['location']}`" if h["location"] else "(location unknown)"
        lines.append(f"- **{h['symbol']}** — {loc} · {h['refs']} refs")
    return "\n".join(lines) + "\n"
