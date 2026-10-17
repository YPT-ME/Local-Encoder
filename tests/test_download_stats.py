"""Download history must preserve observations without inventing download timestamps."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from scripts.collect_download_stats import build_snapshot, render_report, save_snapshot


def _release(release_id: int = 1, *, draft: bool = False) -> dict[str, Any]:
    return {
        "id": release_id,
        "tag_name": f"v1.0.{release_id}",
        "published_at": "2026-10-16T12:00:00Z",
        "draft": draft,
        "prerelease": False,
        "assets": [
            {"id": release_id * 10, "name": "LocalEncoder-windows-x64.zip", "download_count": 3},
            {"id": release_id * 10 + 1, "name": "SHA256SUMS.txt", "download_count": 2},
        ],
    }


def test_all_pages_are_counted_without_drafts_or_duplicate_releases() -> None:
    first = _release()
    prerelease = _release(2)
    prerelease["prerelease"] = True
    result = build_snapshot(
        [[first], [first, prerelease, _release(3, draft=True)]],
        "YPT-ME/Local-Encoder",
        datetime(2026, 10, 16, 15, 23, tzinfo=timezone(timedelta(hours=-3))),
    )
    assert result["collected_at"] == "2026-10-16T18:23:00Z"
    assert result["total_downloads"] == 10
    assert result["program_downloads"] == 6
    assert [release["id"] for release in result["releases"]] == [1, 2]
    assert result["releases"][1]["prerelease"] is True
    assert result["releases"][0]["assets"][0]["id"] == 10


def test_empty_repository_has_zero_downloads() -> None:
    snapshot = build_snapshot([[]], "YPT-ME/Local-Encoder", datetime.now(timezone.utc))
    assert snapshot["total_downloads"] == snapshot["program_downloads"] == 0
    assert snapshot["releases"] == []


@pytest.mark.parametrize("count", [-1, True, "3"])
def test_invalid_counter_is_rejected(count: Any) -> None:
    release = _release()
    release["assets"][0]["download_count"] = count
    with pytest.raises(ValueError, match="non-negative integers"):
        build_snapshot([[release]], "YPT-ME/Local-Encoder", datetime.now(timezone.utc))


def test_history_is_preserved_and_latest_advances_across_days(tmp_path: Path) -> None:
    release = _release()
    moment = datetime(2026, 10, 16, 23, 23, tzinfo=timezone.utc)
    baseline = build_snapshot([[release]], "YPT-ME/Local-Encoder", moment)
    save_snapshot(baseline, tmp_path)
    release["assets"][0]["download_count"] += 2
    second = build_snapshot([[release]], "YPT-ME/Local-Encoder", moment + timedelta(minutes=20))
    save_snapshot(second, tmp_path)
    third = build_snapshot([[release]], "YPT-ME/Local-Encoder", moment + timedelta(hours=1))
    save_snapshot(third, tmp_path)

    first_day = (tmp_path / "snapshots" / "2026-10-16.jsonl").read_text(encoding="utf-8")
    assert [json.loads(line) for line in first_day.splitlines()] == [baseline, second]
    next_day = (tmp_path / "snapshots" / "2026-10-17.jsonl").read_text(encoding="utf-8")
    assert json.loads(next_day) == third
    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8")) == third
    assert third["program_downloads"] - baseline["program_downloads"] == 2


def _observation(moment: datetime, releases: list[dict[str, Any]]) -> dict[str, Any]:
    return build_snapshot([releases], "YPT-ME/Local-Encoder", moment)


def test_report_breaks_downloads_down_by_version_platform_day_and_interval() -> None:
    old = _release()
    old["assets"].append(
        {"id": 12, "name": "LocalEncoder-macos-arm64.zip", "download_count": 1},
    )
    start = datetime(2026, 10, 16, 22, 23, tzinfo=timezone.utc)
    baseline = _observation(start, [old])
    old["assets"][0]["download_count"] += 2
    after_midnight = _observation(start + timedelta(hours=2), [old])
    new = _release(2)
    new["published_at"] = "2026-10-17T01:00:00Z"
    with_new_release = _observation(start + timedelta(hours=3), [old, new])
    quiet = _observation(start + timedelta(hours=4), [old, new])

    report = render_report([baseline, after_midnight, with_new_release, quiet])

    assert "| Version | windows-x64 | macos-arm64 | Total |" in report
    assert "| v1.0.2 | 3 | 0 | 3 |" in report
    assert "| v1.0.1 | 5 | 1 | 6 |" in report
    assert "| **Total** | 8 | 1 | 9 |" in report
    assert (
        "| Before 2026-10-16 22:23 (time unknown) | 4 "
        "| v1.0.1 windows-x64: 3, v1.0.1 macos-arm64: 1 |" in report
    )
    assert "| 2026-10-17 | 5 | v1.0.1 windows-x64: 2, v1.0.2 windows-x64: 3 |" in report
    assert "| 2026-10-17 00:23 | 2026-10-17 01:23 | 3 | v1.0.2 windows-x64: 3 |" in report
    assert "| 2026-10-16 22:23 | 2026-10-17 00:23 | 2 | v1.0.1 windows-x64: 2 |" in report
    assert "SHA256SUMS" not in report


def test_report_does_not_invent_interval_downloads() -> None:
    start = datetime(2026, 10, 16, 12, 23, tzinfo=timezone.utc)
    shrinking = _release()
    baseline = _observation(start, [shrinking])
    shrinking["assets"][0]["download_count"] = 1
    replaced = _observation(start + timedelta(hours=1), [shrinking])
    # An asset first seen now, from a release older than the previous observation.
    late = _release(2)
    late_seen = _observation(start + timedelta(hours=2), [shrinking, late])

    report = render_report([baseline, replaced, late_seen])

    assert "| Before 2026-10-16 12:23 (time unknown) | 6 |" in report
    assert "| – | – | 0 | No new downloads since collection began |" in report
    assert "| 2026-10-16 |" not in report


def test_saved_readme_contains_the_report(tmp_path: Path) -> None:
    moment = datetime(2026, 10, 16, 12, 23, tzinfo=timezone.utc)
    save_snapshot(_observation(moment, [_release()]), tmp_path)
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "## Program downloads per version and platform" in readme
    assert "| v1.0.1 | 3 | 3 |" in readme
    assert "## About the data" in readme
