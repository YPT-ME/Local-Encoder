"""Download vendored frontend dependencies into avideo_local_encoder/static/vendor/.

Usage:
    python scripts/download_vendor.py

Run this script whenever you want to update the vendored libraries.
No external dependencies required — uses only the standard library.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

VENDOR_DIR = Path(__file__).parent.parent / "avideo_local_encoder" / "static" / "vendor"

# Pin exact URLs so builds are reproducible.
# To upgrade: update the URL and the expected SHA-256.
ASSETS: list[dict[str, str]] = [
    {
        "filename": "tailwind.js",
        "url": "https://cdn.tailwindcss.com/3.4.17",
        "sha256": "",  # fill in after first download with: python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" vendor/tailwind.js
    },
    {
        "filename": "react.development.js",
        "url": "https://unpkg.com/react@18.3.1/umd/react.development.js",
        "sha256": "",
    },
    {
        "filename": "react-dom.development.js",
        "url": "https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js",
        "sha256": "",
    },
    {
        "filename": "babel.min.js",
        "url": "https://unpkg.com/@babel/standalone@7.27.1/babel.min.js",
        "sha256": "",
    },
]


def download(asset: dict[str, str], dest_dir: Path, force: bool = False) -> None:
    dest = dest_dir / asset["filename"]
    if dest.exists() and not force:
        print(f"  skip  {asset['filename']} (already exists, use --force to re-download)")
        return

    print(f"  fetch {asset['filename']}  ← {asset['url']}")
    with urllib.request.urlopen(asset["url"], timeout=60) as resp:  # noqa: S310
        data = resp.read()

    if asset["sha256"]:
        digest = hashlib.sha256(data).hexdigest()
        if digest != asset["sha256"]:
            print(f"  ERROR: SHA-256 mismatch for {asset['filename']}")
            print(f"         expected: {asset['sha256']}")
            print(f"         got:      {digest}")
            sys.exit(1)

    dest.write_bytes(data)
    size_kb = len(data) / 1024
    digest = hashlib.sha256(data).hexdigest()
    print(f"  ok    {asset['filename']}  ({size_kb:.0f} KB)  sha256={digest[:16]}…")


def main() -> None:
    force = "--force" in sys.argv
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Vendor dir: {VENDOR_DIR}\n")
    for asset in ASSETS:
        download(asset, VENDOR_DIR, force=force)
    print("\nDone.")


if __name__ == "__main__":
    main()
