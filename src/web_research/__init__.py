"""web-research: local-first web research engine for LLM agents.

Graduated from ``~/.claude/scripts/web_research/`` (flat package) into a
vertical-slice layout. Public functions are re-exported here so callers can do
``import web_research as wr; wr.searxng_search(...)`` unchanged.

Module aliases (``wr.search``, ``wr.reader``, ``wr.synthesis``) expose the
engine modules under their historic flat names so that
``patch.object(wr.search, "MINIMAX_API_KEY", ...)`` style test patches keep
resolving to the module where the name is actually bound.
"""

from __future__ import annotations

try:
    from importlib.metadata import version as _version

    __version__ = _version("web-research")
    if __version__ == "0.0.0":
        from ._version import __version__
except Exception:  # pragma: no cover — installed vs source-tree
    from ._version import __version__

from .cli import main
from .features.intelligence.engine import (
    expand_queries,
    focused_extract,
    query_profile,
    search_queries,
)
from .features.ranking.engine import (
    parse_result_date,
    recency_score,
    rerank_results,
    select_with_recency_diversity,
    source_quality_score,
)

# Module aliases for historic patch targets (wr.search / wr.reader / wr.synthesis).
from .features.read import engine as reader  # noqa: E402,F401
from .features.read.engine import firecrawl_scrape, scrape_with_fallback, zai_reader
from .features.search import engine as search  # noqa: E402,F401
from .features.search.engine import (
    escalation_chain,
    minimax_search,
    search_backends,
    search_with_escalation,
    searxng_search,
    zai_search,
)
from .features.synthesis import engine as synthesis  # noqa: E402,F401
from .features.synthesis.engine import (
    ground_structured_facts,
    next_search_query,
    synthesize,
    synthesize_result,
)
from .shared.formatters import fmt_results, fmt_smart_results

__all__ = [
    "__version__",
    "main",
    "fmt_results",
    "fmt_smart_results",
    "expand_queries",
    "focused_extract",
    "query_profile",
    "search_queries",
    "parse_result_date",
    "recency_score",
    "rerank_results",
    "select_with_recency_diversity",
    "source_quality_score",
    "firecrawl_scrape",
    "scrape_with_fallback",
    "zai_reader",
    "escalation_chain",
    "minimax_search",
    "search_backends",
    "search_with_escalation",
    "searxng_search",
    "zai_search",
    "ground_structured_facts",
    "next_search_query",
    "synthesize",
    "synthesize_result",
    # module aliases (historic flat names)
    "search",
    "reader",
    "synthesis",
]
