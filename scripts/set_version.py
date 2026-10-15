"""Stamp a release version into local_encoder/__init__.py (the single version source).

Usage:
    python scripts/set_version.py 1.2.3

Used by .github/workflows/release.yml before building; the repository keeps the
development version.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

INIT = Path(__file__).resolve().parent.parent / "local_encoder" / "__init__.py"


def main() -> None:
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        raise SystemExit(__doc__)
    text = INIT.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'^__version__ = "[^"]*"$', f'__version__ = "{sys.argv[1]}"', text, flags=re.M
    )
    if count != 1:
        raise SystemExit(f"__version__ not found in {INIT}")
    INIT.write_text(new_text, encoding="utf-8")
    print(f"Version set to {sys.argv[1]}")


if __name__ == "__main__":
    main()
