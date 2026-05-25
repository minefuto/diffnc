"""Allow ``python -m diffnc`` to dispatch to the CLI."""

from __future__ import annotations

from diffnc.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
