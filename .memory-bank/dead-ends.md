# Dead-End Log
> Format: `[YYYY-MM-DD] Approach → Why failed → What worked instead`

## Failed Approaches
- **[2026-07-05]** Module `__setattr__` proxy for legacy `config.X = Y`
  writes. Tried overriding `__setattr__` on `web_research.shared.config`
  to capture legacy writes (`config.TIMEOUT = 90`) and route to
  `_settings.replace(...)`. → Failed: Python does NOT invoke module
  `__setattr__` for plain `module.x = y` assignments; the writes go
  straight to module `__dict__` even when `__setattr__` is defined.
  → **Worked instead:** keep the read-only `__getattr__` proxy for
  legacy imports, AND have `reload_settings()` clear stale `__dict__`
  cached entries (necessary so cross-test pollution doesn't leave a
  `__dict__["TIMEOUT"]=30` that shadows the singleton's new value).