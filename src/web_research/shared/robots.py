"""robots.txt compliance for the reader (stdlib only, fail-open).

The reader consults this before fetching a page so the engine respects
crawl directives. Parsing results are cached per host (5 min) to avoid a
robots round-trip on every scrape. Any failure to fetch or parse robots.txt
is treated as *allow* (fail-open): an unreachable or malformed robots file
must not silently block research, and public pages commonly return 404 for
``/robots.txt`` which ``RobotFileParser`` already maps to "allow all".
"""

from __future__ import annotations

import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

_CACHE: dict[str, tuple[float, RobotFileParser | None]] = {}
_TTL_SECONDS = 300.0


def _host_root(url: str) -> str | None:
    """Return ``scheme://netloc`` for ``url``, or ``None`` if not absolute."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _load_parser(host_root: str) -> RobotFileParser | None:
    """Fetch+parse ``{host_root}/robots.txt``; cache by host for ``_TTL_SECONDS``."""
    now = time.time()
    cached = _CACHE.get(host_root)
    if cached and now - cached[0] < _TTL_SECONDS:
        return cached[1]
    parser = RobotFileParser()
    parser.set_url(f"{host_root}/robots.txt")
    try:
        parser.read()
        result: RobotFileParser | None = parser
    except Exception:  # noqa: BLE001 — unreachable/malformed → fail open
        result = None
    _CACHE[host_root] = (now, result)
    return result


def is_allowed(url: str, user_agent: str = "*") -> bool:
    """True if robots.txt permits fetching ``url``; fails open on any error."""
    root = _host_root(url)
    if root is None:
        return False
    parser = _load_parser(root)
    if parser is None:
        return True
    try:
        return parser.can_fetch(user_agent, url)
    except Exception:  # noqa: BLE001 — malformed entry → allow rather than block
        return True


def bust_cache() -> None:
    """Clear the in-memory robots cache (test hook)."""
    _CACHE.clear()
