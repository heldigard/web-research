"""Search backend registry + factory.

Adding a new search source: write a ``backends/<name>.py`` class that
implements :class:`~.base.SearchBackend`, then register it in
:func:`build_backend` + :data:`BUILTIN_BACKENDS`.
"""

from __future__ import annotations

from typing import cast

from .base import SearchBackend, SearchResult, normalize_url, tracking_params
from .minimax import MinimaxBackend
from .searxng import SearXNGBackend
from .zai import ZaiBackend, zai_recency

# All known backends, keyed by ``--engine`` name. The dispatcher looks up
# ``BUILTIN_BACKENDS[engine]``; an unknown name yields ``None`` and the
# CLI fails fast before hitting the network.
BUILTIN_BACKENDS: dict[str, type[SearchBackend]] = {
    "searxng": cast(type[SearchBackend], SearXNGBackend),
    "minimax": cast(type[SearchBackend], MinimaxBackend),
    "zai": cast(type[SearchBackend], ZaiBackend),
}


def build_backend(name: str, **kwargs: object) -> SearchBackend | None:
    """Return an instance for the named backend, or ``None`` if unknown."""
    cls = BUILTIN_BACKENDS.get(name)
    if cls is None:
        return None
    return cls(**kwargs)  # type: ignore[abstract]


__all__ = [
    "BUILTIN_BACKENDS",
    "MinimaxBackend",
    "SearchBackend",
    "SearchResult",
    "SearXNGBackend",
    "ZaiBackend",
    "build_backend",
    "normalize_url",
    "tracking_params",
    "zai_recency",
]
