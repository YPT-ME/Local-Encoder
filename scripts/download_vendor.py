"""Download vendored frontend dependencies into local_encoder/static/vendor/.

Usage:
    python scripts/download_vendor.py

Run this script whenever you want to update the vendored libraries.
No external dependencies required - uses only the standard library.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

VENDOR_DIR = Path(__file__).parent.parent / "local_encoder" / "static" / "vendor"

# Pin exact URLs and their SHA-256 so builds are reproducible and a changed CDN file fails the
# build. To upgrade: update the URL, run with --force once, and copy the printed sha256 here.
ASSETS: list[dict[str, str]] = [
    {
        "filename": "tailwind.js",
        "url": "https://cdn.tailwindcss.com/3.4.17",
        "sha256": "176e894661aa9cdc9a5cba6c720044cbbf7b8bd80d1c9a142a7c24b1b6c50d15",
    },
    {
        "filename": "react.development.js",
        "url": "https://unpkg.com/react@18.3.1/umd/react.development.js",
        "sha256": "28348fef6cb0ed8b2ceeb22deaf824428fd13875d84c73d38f77dd216fc24e7f",
    },
    {
        "filename": "react-dom.development.js",
        "url": "https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js",
        "sha256": "f9044a5e9c39db8bb1a204dff924e526ec0a621e695bb69de1035811be8709e4",
    },
    {
        "filename": "babel.min.js",
        "url": "https://unpkg.com/@babel/standalone@7.27.1/babel.min.js",
        "sha256": "17128ff779ecfd0b0b4934b6b3248d9284a5b22b5d11c46310561788c1e84963",
    },
]


def download(asset: dict[str, str], dest_dir: Path, force: bool = False) -> None:
    dest = dest_dir / asset["filename"]
    if dest.exists() and not force:
        print(f"  skip  {asset['filename']} (already exists, use --force to re-download)")
        return

    print(f"  fetch {asset['filename']}  <- {asset['url']}")
    # cdn.tailwindcss.com answers 403 to Python's default "Python-urllib" User-Agent.
    request = urllib.request.Request(asset["url"], headers={"User-Agent": "local-encoder-build"})
    with urllib.request.urlopen(request, timeout=60) as resp:  # noqa: S310
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
    print(f"  ok    {asset['filename']}  ({size_kb:.0f} KB)  sha256={digest}")


def main() -> None:
    force = "--force" in sys.argv
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Vendor dir: {VENDOR_DIR}\n")
    for asset in ASSETS:
        download(asset, VENDOR_DIR, force=force)
    print("\nDone.")


if __name__ == "__main__":
    main()
