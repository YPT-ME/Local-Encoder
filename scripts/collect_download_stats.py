"""Save hourly observations of GitHub release download counters.

Input is the paginated JSON returned by `gh api --paginate --slurp .../releases`.
Only public release metadata is saved; draft releases are excluded.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_snapshot(
    pages: list[list[dict[str, Any]]], repository: str, collected_at: datetime
) -> dict[str, Any]:
    """Keep asset identities and cumulative counters, without inferring download times."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected a repository in owner/name format")
    if collected_at.tzinfo is None:
        raise ValueError("The collection timestamp must include a timezone")

    releases = []
    seen = set()
    program_downloads = 0
    for page in pages:
        for release in page:
            if release["draft"] or release["id"] in seen:
                continue
            seen.add(release["id"])
            assets = []
            for asset in release["assets"]:
                count = asset["download_count"]
                if type(count) is not int or count < 0:
                    raise ValueError("Download counts must be non-negative integers")
                assets.append({"id": asset["id"], "name": asset["name"], "download_count": count})
                if asset["name"].startswith("LocalEncoder-"):
                    program_downloads += count
            releases.append(
                {
                    "id": release["id"],
                    "tag_name": release["tag_name"],
                    "published_at": release["published_at"],
                    "prerelease": release["prerelease"],
                    "download_count": sum(asset["download_count"] for asset in assets),
                    "assets": sorted(assets, key=lambda asset: asset["id"]),
                }
            )

    return {
        "schema_version": 1,
        "repository": repository,
        "collected_at": collected_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_downloads": sum(release["download_count"] for release in releases),
        "program_downloads": program_downloads,
        "releases": sorted(releases, key=lambda release: release["id"]),
    }


def save_snapshot(snapshot: dict[str, Any], output: Path) -> None:
    """Append an observation to its UTC day and refresh the latest snapshot and summary."""
    history = output / "snapshots" / f"{snapshot['collected_at'][:10]}.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(snapshot, separators=(",", ":")) + "\n")
    (output / "latest.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    (output / "README.md").write_text(
        "# Download statistics\n\n"
        "Automatic observations of GitHub release asset counters.\n\n"
        "| Latest observation (UTC) | All release assets | Program packages only |\n"
        "| --- | --- | --- |\n"
        f"| {snapshot['collected_at']} | {snapshot['total_downloads']} "
        f"| {snapshot['program_downloads']} |\n\n"
        "- `latest.json`: the most recent observation.\n"
        "- `snapshots/YYYY-MM-DD.jsonl`: one JSON observation per line, grouped by UTC day.\n"
        "- Each observation contains release IDs/tags and asset IDs/names with cumulative counts.\n"
        "- All published releases, including pre-releases, are included; drafts are excluded.\n"
        "- Program packages are assets whose names start with `LocalEncoder-`.\n\n"
        "The first observation is a baseline, including earlier downloads. Compare the same "
        "asset ID in successive observations to measure the increase over that interval. "
        "A newly seen asset's count may include downloads before collection began; a removed "
        "or replaced asset must not be treated as negative downloads.\n\n"
        "Collection is scheduled hourly but may be delayed or skipped by GitHub Actions. "
        "These are observation timestamps, not the exact times of individual downloads. "
        "Repeat downloads and updates count again; no downloader identities are collected.\n\n"
        f"[Collector workflow](https://github.com/{snapshot['repository']}"
        "/actions/workflows/download-stats.yml)\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--releases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    pages = json.loads(args.releases.read_text(encoding="utf-8"))
    snapshot = build_snapshot(pages, args.repository, datetime.now(timezone.utc))
    save_snapshot(snapshot, args.output)
    print(f"Recorded {snapshot['total_downloads']} release asset downloads")


if __name__ == "__main__":
    main()
