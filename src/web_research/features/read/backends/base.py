"""Base protocol + Page dataclass for read (URL → markdown) backends.

Each reader backend (``firecrawl`` / ``zai_reader``) lives in its own
file under this package and implements the duck-typed reader contract.
Adding a new reader is one new file + one registry entry.
"""

# vs-soft-allow  — reader backend contract is duck-typed by design; explicit
# Protocols here drift because each reader takes different kwargs (Firecrawl
# takes ``wait``, Z.AI takes ``timeout``). Python's duck typing wins.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Page:
    """Markdown-rendered page from a single URL."""

    url: str
    markdown: str

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "markdown": self.markdown}


def tracking_params() -> set[str]:
    """Tracking-param set used during URL canonicalization before cache lookup."""
    return {"utm_source", "utm_medium", "utm_campaign"}


# Type alias for dispatcher/registry purposes.
PageReader = Any
