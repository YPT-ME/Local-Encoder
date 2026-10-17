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


_PROGRAM_ASSET = re.compile(r"LocalEncoder-(.+?)\.(?:zip|tar\.gz)")
_PLATFORM_ORDER = ["windows-x64", "macos-arm64", "macos-x64", "linux-x64", "linux-arm64"]
_RECENT_INTERVALS = 48

# (release tag, platform) -> downloads
Counts = dict[tuple[str, str], int]


def _program_assets(snapshot: dict[str, Any]) -> dict[int, tuple[str, str, str, int]]:
    """Map program asset ID -> (tag, platform, release published_at, cumulative count)."""
    assets = {}
    for release in snapshot["releases"]:
        for asset in release["assets"]:
            match = _PROGRAM_ASSET.fullmatch(asset["name"])
            if match:
                assets[asset["id"]] = (
                    release["tag_name"],
                    match.group(1),
                    release["published_at"] or "",
                    asset["download_count"],
                )
    return assets


def _interval_downloads(previous: dict[str, Any], current: dict[str, Any]) -> tuple[Counts, Counts]:
    """Split counter increases into (observed in this interval, time unknown).

    A new asset counts toward the interval only when its release was published after the
    previous observation; otherwise some of its downloads may be older. Lower counters
    (deleted/replaced assets) are never negative downloads.
    """
    before = _program_assets(previous)
    observed: Counts = {}
    unknown: Counts = {}
    for asset_id, (tag, platform, published_at, count) in _program_assets(current).items():
        if asset_id in before:
            target, increase = observed, count - before[asset_id][3]
        else:
            target = observed if published_at > previous["collected_at"] else unknown
            increase = count
        if increase > 0:
            target[(tag, platform)] = target.get((tag, platform), 0) + increase
    return observed, unknown


def _add(total: Counts, counts: Counts) -> None:
    for key, value in counts.items():
        total[key] = total.get(key, 0) + value


def _breakdown(counts: Counts) -> str:
    return ", ".join(f"{tag} {platform}: {value}" for (tag, platform), value in counts.items())


def _minute(observation: dict[str, Any]) -> str:
    return str(observation["collected_at"][:16]).replace("T", " ")


def _load_history(output: Path) -> list[dict[str, Any]]:
    observations = []
    for path in sorted((output / "snapshots").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                observations.append(json.loads(line))
    return sorted(observations, key=lambda observation: observation["collected_at"])


def render_report(history: list[dict[str, Any]]) -> str:
    """Markdown tables per version/platform, per UTC day and per collection interval."""
    latest = history[-1]
    tags = [release["tag_name"] for release in latest["releases"]]
    per_version: Counts = {}
    for tag, platform, _published, count in _program_assets(latest).values():
        per_version[(tag, platform)] = per_version.get((tag, platform), 0) + count
    platforms = sorted(
        {platform for _tag, platform in per_version},
        key=lambda name: (_PLATFORM_ORDER.index(name) if name in _PLATFORM_ORDER else 99, name),
    )

    baseline: Counts = {
        (tag, platform): count
        for tag, platform, _published, count in _program_assets(history[0]).values()
        if count
    }
    days: dict[str, Counts] = {}
    intervals = []
    for previous, current in zip(history, history[1:], strict=False):
        observed, unknown = _interval_downloads(previous, current)
        _add(baseline, unknown)
        if observed:
            _add(days.setdefault(current["collected_at"][:10], {}), observed)
            intervals.append((_minute(previous), _minute(current), observed))

    lines = [
        "# Download statistics",
        "",
        "Automatic observations of GitHub release asset counters, collected about hourly.",
        "",
        "| Latest observation (UTC) | All release assets | Program packages only |",
        "| --- | --- | --- |",
        f"| {latest['collected_at']} | {latest['total_downloads']} "
        f"| {latest['program_downloads']} |",
        "",
        "## Program downloads per version and platform",
        "",
        "Cumulative totals, including downloads before collection began.",
        "",
        "| Version | " + " | ".join(platforms) + " | Total |",
        "| --- |" + " ---: |" * (len(platforms) + 1),
    ]
    for tag in reversed(tags):
        row = [per_version.get((tag, platform), 0) for platform in platforms]
        if any(row):
            lines.append(f"| {tag} | " + " | ".join(map(str, row)) + f" | {sum(row)} |")
    column_totals = [
        sum(value for (_tag, name), value in per_version.items() if name == platform)
        for platform in platforms
    ]
    lines += [
        "| **Total** | " + " | ".join(map(str, column_totals)) + f" | {sum(column_totals)} |",
        "",
        "## Program downloads per UTC day",
        "",
        "Increases between collections, assigned to the day of the later collection.",
        "",
        "| Day (UTC) | Downloads | Version and platform |",
        "| --- | ---: | --- |",
        f"| Before {_minute(history[0])} (time unknown) "
        f"| {sum(baseline.values())} | {_breakdown(baseline)} |",
    ]
    for day, counts in sorted(days.items(), reverse=True):
        lines.append(f"| {day} | {sum(counts.values())} | {_breakdown(counts)} |")
    lines += [
        "",
        f"## Recent collection intervals with downloads (last {_RECENT_INTERVALS})",
        "",
        "Downloads happened at some moment between the two collection times.",
        "",
        "| From (UTC) | To (UTC) | Downloads | Version and platform |",
        "| --- | --- | ---: | --- |",
    ]
    for start, end, counts in reversed(intervals[-_RECENT_INTERVALS:]):
        lines.append(f"| {start} | {end} | {sum(counts.values())} | {_breakdown(counts)} |")
    if not intervals:
        lines.append("| – | – | 0 | No new downloads since collection began |")
    return "\n".join(lines) + "\n\n"


def save_snapshot(snapshot: dict[str, Any], output: Path) -> None:
    """Append an observation to its UTC day and refresh the latest snapshot and report."""
    history = output / "snapshots" / f"{snapshot['collected_at'][:10]}.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(snapshot, separators=(",", ":")) + "\n")
    (output / "latest.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    (output / "README.md").write_text(
        render_report(_load_history(output)) + "## About the data\n\n"
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
