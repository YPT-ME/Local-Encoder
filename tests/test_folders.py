"""Tests for browsing folders and listing the videos in one."""

from __future__ import annotations

from pathlib import Path

import pytest

from local_encoder import folders
from local_encoder.errors import LocalEncoderError


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    root = tmp_path / "Videos"
    (root / "Trips" / "2025").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "b.MP4").write_bytes(b"x" * 10)
    (root / "a.mkv").write_bytes(b"x")
    (root / "notes.txt").write_text("not a video")
    (root / "Trips" / "beach.mov").write_bytes(b"x")
    (root / "Trips" / "2025" / "deep.webm").write_bytes(b"x")
    (root / ".hidden" / "secret.mp4").write_bytes(b"x")
    return root


def test_browse_lists_visible_subfolders_and_counts_videos(library: Path) -> None:
    result = folders.browse(str(library))
    assert result["path"] == str(library.resolve())
    assert [f["name"] for f in result["folders"]] == ["Trips"]  # type: ignore[index]
    assert result["video_count"] == 2
    assert result["parent"] == str(library.resolve().parent)
    assert result["places"][0]["key"] == "home"  # type: ignore[index]


def test_browse_empty_path_is_home() -> None:
    assert folders.browse("")["path"] == str(Path.home().resolve())


def test_browse_missing_folder_has_a_code(tmp_path: Path) -> None:
    with pytest.raises(LocalEncoderError) as excinfo:
        folders.browse(str(tmp_path / "nope"))
    assert excinfo.value.code == "folder_not_found"


def test_scan_lists_videos_only_sorted(library: Path) -> None:
    result = folders.scan(str(library))
    assert [v.rel for v in result.videos] == ["a.mkv", "b.MP4"]
    assert result.videos[1].size == 10
    assert result.truncated is False


def test_scan_recursive_skips_hidden_folders(library: Path) -> None:
    result = folders.scan(str(library), recursive=True)
    assert [v.rel for v in result.videos] == [
        "a.mkv",
        "b.MP4",
        "Trips/beach.mov",
        "Trips/2025/deep.webm",
    ]


def test_scan_never_lists_the_work_folder(library: Path) -> None:
    work = library / "Trips"
    result = folders.scan(str(library), recursive=True, skip=work)
    assert all(not v.rel.startswith("Trips") for v in result.videos)


def test_scan_stops_at_the_limit(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(folders, "MAX_VIDEOS", 1)
    result = folders.scan(str(library))
    assert len(result.videos) == 1
    assert result.truncated is True


def test_video_file_accepts_an_existing_video(library: Path) -> None:
    assert folders.video_file(str(library / "a.mkv")) == (library / "a.mkv").resolve()


@pytest.mark.parametrize(
    ("name", "code"),
    [("notes.txt", "file_not_video"), ("gone.mp4", "source_missing")],
)
def test_video_file_rejects(library: Path, name: str, code: str) -> None:
    with pytest.raises(LocalEncoderError) as excinfo:
        folders.video_file(str(library / name))
    assert excinfo.value.code == code


def test_video_file_rejects_relative_paths() -> None:
    with pytest.raises(LocalEncoderError) as excinfo:
        folders.video_file("a.mkv")
    assert excinfo.value.code == "file_not_video"
