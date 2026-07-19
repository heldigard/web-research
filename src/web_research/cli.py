"""CLI entrypoint: build the parser and dispatch to the feature command."""

from __future__ import annotations

import sys
import urllib.error

from web_research.capabilities import mode_capabilities
from web_research.cli_parser import build_parser
from web_research.features.read.command import mode_read
from web_research.features.research.command import mode_research
from web_research.features.search.command import mode_search
from web_research.features.status.command import mode_status


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    p = build_parser(
        {
            "search": mode_search,
            "research": mode_research,
            "read": mode_read,
            "status": mode_status,
            "capabilities": mode_capabilities,
        }
    )
    args = p.parse_args(argv)
    try:
        return args.func(args)
    except urllib.error.URLError as e:
        print(
            f"[error] network: {e}\n(check service is up: web-research status)",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
