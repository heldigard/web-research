"""Read backend registry + factory.

Adding a new reader: write a ``backends/<name>.py`` class that implements
the reader contract (see ``backends/base.py``), then register it in
:func:`build_reader` + :data:`BUILTIN_READERS`.
"""

from __future__ import annotations

from typing import cast

from .base import Page, PageReader, tracking_params
from .firecrawl import FirecrawlReader
from .zai_reader import ZaiReader

# All known readers, keyed by ``--engine`` name. The dispatcher looks up
# ``BUILTIN_READERS[engine]``; an unknown name yields ``None``.
BUILTIN_READERS: dict[str, type[PageReader]] = {
    "firecrawl": cast(type[PageReader], FirecrawlReader),
    "zai": cast(type[PageReader], ZaiReader),
}


def build_reader(name: str, **kwargs: object) -> PageReader | None:
    """Return an instance for the named reader, or ``None`` if unknown."""
    cls = BUILTIN_READERS.get(name)
    if cls is None:
        return None
    return cls(**kwargs)  # type: ignore[abstract]


__all__ = [
    "BUILTIN_READERS",
    "FirecrawlReader",
    "Page",
    "PageReader",
    "ZaiReader",
    "build_reader",
    "tracking_params",
]
