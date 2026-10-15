"""Tests for the downloader module."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp.utils  # type: ignore[import-untyped]

from local_encoder.downloader import (
    download_video,
    get_video_info,
    is_web_url,
    reject_unsupported,
)
from local_encoder.errors import LocalEncoderError

# ---------------------------------------------------------------------------
# _progress_hook behaviour (tested indirectly through download_video)
# ---------------------------------------------------------------------------


def _make_ydl_mock(
    info: dict[str, Any] | None = None, side_effect: Exception | None = None
) -> MagicMock:
    """Return a mock YoutubeDL context manager."""
    ydl = MagicMock()
    ydl.__enter__ = MagicMock(return_value=ydl)
    ydl.__exit__ = MagicMock(return_value=False)
    if side_effect:
        ydl.extract_info.side_effect = side_effect
    else:
        ydl.extract_info.return_value = info or {"title": "Test Video", "duration": 60}
    return ydl


# ---------------------------------------------------------------------------
# progress hook: byte-based progress
# ---------------------------------------------------------------------------


def test_progress_hook_byte_based(tmp_path: Path) -> None:
    """Callback is called with downloaded_bytes / total_bytes."""
    calls: list[tuple[str, int, int]] = []

    def on_progress(status: str, a: int, b: int) -> None:
        calls.append((status, a, b))

    expected = tmp_path / "video.mp4"
    expected.write_bytes(b"\x00")

    hook_ref: list[Any] = []

    def fake_ydl_class(opts: dict[str, Any]) -> MagicMock:
        hook_ref.extend(opts.get("progress_hooks", []))
        ydl = _make_ydl_mock()
        ydl.__enter__ = MagicMock(return_value=ydl)
        ydl.__exit__ = MagicMock(return_value=False)
        return ydl

    with patch("local_encoder.downloader.yt_dlp.YoutubeDL", side_effect=fake_ydl_class):
        download_video("https://example.com/v", tmp_path, "video", progress_callback=on_progress)

    assert hook_ref, "progress_hook should have been registered"
    hook = hook_ref[0]

    hook({"status": "downloading", "downloaded_bytes": 500, "total_bytes": 1000})
    assert ("downloading", 500, 1000) in calls

    hook({"status": "finished", "total_bytes": 1000})
    assert any(s == "finished" for s, _, _ in calls)


# ---------------------------------------------------------------------------
# progress hook: fragment-based progress (DASH/HLS)
# ---------------------------------------------------------------------------


def test_progress_hook_fragment_based(tmp_path: Path) -> None:
    """fragment_index/fragment_count takes priority over byte counters."""
    calls: list[tuple[str, int, int]] = []

    def on_progress(status: str, a: int, b: int) -> None:
        calls.append((status, a, b))

    expected = tmp_path / "video.mp4"
    expected.write_bytes(b"\x00")

    hook_ref: list[Any] = []

    def fake_ydl_class(opts: dict[str, Any]) -> MagicMock:
        hook_ref.extend(opts.get("progress_hooks", []))
        ydl = _make_ydl_mock()
        ydl.__enter__ = MagicMock(return_value=ydl)
        ydl.__exit__ = MagicMock(return_value=False)
        return ydl

    with patch("local_encoder.downloader.yt_dlp.YoutubeDL", side_effect=fake_ydl_class):
        download_video("https://example.com/v", tmp_path, "video", progress_callback=on_progress)

    hook = hook_ref[0]
    hook(
        {
            "status": "downloading",
            "fragment_index": 25,
            "fragment_count": 100,
            "downloaded_bytes": 100,
            "total_bytes_estimate": 200,  # should be ignored
        }
    )
    assert ("downloading", 25, 100) in calls


# ---------------------------------------------------------------------------
# download_video: success path
# ---------------------------------------------------------------------------


def test_download_video_returns_expected_mp4(tmp_path: Path) -> None:
    expected = tmp_path / "my-video.mp4"
    expected.write_bytes(b"\x00" * 10)

    with patch("local_encoder.downloader.yt_dlp.YoutubeDL", return_value=_make_ydl_mock()):
        result = download_video("https://example.com/v", tmp_path, "my-video")

    assert result == expected


def test_download_video_falls_back_to_candidate(tmp_path: Path) -> None:
    """If .mp4 not found, returns first matching file by stem."""
    webm = tmp_path / "clip.webm"
    webm.write_bytes(b"\x00")

    with patch("local_encoder.downloader.yt_dlp.YoutubeDL", return_value=_make_ydl_mock()):
        result = download_video("https://example.com/v", tmp_path, "clip")

    assert result == webm


# ---------------------------------------------------------------------------
# download_video: all strategies fail
# ---------------------------------------------------------------------------


def test_download_video_raises_when_all_strategies_fail(tmp_path: Path) -> None:
    import yt_dlp.utils

    failing_ydl = _make_ydl_mock(side_effect=yt_dlp.utils.DownloadError("unavailable"))

    with patch("local_encoder.downloader.yt_dlp.YoutubeDL", return_value=failing_ydl):
        with pytest.raises(yt_dlp.utils.DownloadError):
            download_video("https://example.com/bad", tmp_path, "bad")


def test_download_video_raises_when_extract_info_returns_none(tmp_path: Path) -> None:
    import yt_dlp.utils

    ydl = _make_ydl_mock(info=None)
    ydl.extract_info.return_value = None

    with patch("local_encoder.downloader.yt_dlp.YoutubeDL", return_value=ydl):
        with pytest.raises(yt_dlp.utils.DownloadError):
            download_video("https://example.com/v", tmp_path, "vid")


# ---------------------------------------------------------------------------
# get_video_info
# ---------------------------------------------------------------------------


def test_get_video_info_returns_dict() -> None:
    fake_info = {"title": "My Video", "duration": 120, "thumbnail": "https://img.example.com/t"}
    ydl = _make_ydl_mock(info=fake_info)

    with patch("local_encoder.downloader.yt_dlp.YoutubeDL", return_value=ydl):
        result = get_video_info("https://example.com/v")

    assert result["title"] == "My Video"
    assert result["duration"] == 120


def test_get_video_info_returns_empty_on_none() -> None:
    ydl = _make_ydl_mock()
    ydl.extract_info.return_value = None

    with patch("local_encoder.downloader.yt_dlp.YoutubeDL", return_value=ydl):
        result = get_video_info("https://example.com/v")

    assert result == {}


# ---------------------------------------------------------------------------
# Single videos only, web links only, cancel
# ---------------------------------------------------------------------------


def test_download_and_info_ask_yt_dlp_for_the_single_video(tmp_path: Path) -> None:
    (tmp_path / "v.mp4").write_bytes(b"x")
    with patch(
        "local_encoder.downloader.yt_dlp.YoutubeDL", return_value=_make_ydl_mock()
    ) as mock_cls:
        download_video("https://www.youtube.com/watch?v=a&list=b", tmp_path, "v")
        get_video_info("https://www.youtube.com/watch?v=a&list=b")

    for call in mock_cls.call_args_list:
        opts = call.args[0]
        # yt-dlp's option is "noplaylist"; an unknown key would be ignored silently.
        assert opts["noplaylist"] is True
        assert "no_playlist" not in opts
    assert mock_cls.call_args_list[-1].args[0]["extract_flat"] == "in_playlist"


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://www.youtube.com/watch?v=x", True),
        ("http://example.com/v.mp4", True),
        ("file:///etc/passwd", False),
        ("ftp://example.com/v", False),
        ("https://", False),
        ("-o /tmp/x", False),
    ],
)
def test_is_web_url(url: str, ok: bool) -> None:
    assert is_web_url(url) is ok


@pytest.mark.parametrize(
    ("info", "code"),
    [
        ({"_type": "playlist"}, "playlist_link"),
        ({"is_live": True}, "live_link"),
        ({"live_status": "is_upcoming"}, "live_link"),
    ],
)
def test_reject_unsupported(info: dict[str, Any], code: str) -> None:
    with pytest.raises(LocalEncoderError) as excinfo:
        reject_unsupported(info)
    assert excinfo.value.code == code


def test_reject_unsupported_accepts_a_video() -> None:
    reject_unsupported({"title": "x", "live_status": "was_live"})


def test_download_stops_when_cancelled(tmp_path: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    with (
        patch("local_encoder.downloader.yt_dlp.YoutubeDL") as mock_cls,
        pytest.raises(yt_dlp.utils.DownloadCancelled),
    ):
        download_video("https://example.com/v", tmp_path, "v", cancel_event=cancel)
    mock_cls.assert_not_called()


def test_progress_hook_raises_when_cancelled(tmp_path: Path) -> None:
    cancel = threading.Event()
    ydl = _make_ydl_mock()
    hooks: list[Any] = []

    def capture(opts: dict[str, Any]) -> MagicMock:
        hooks.extend(opts["progress_hooks"])
        return ydl

    with patch("local_encoder.downloader.yt_dlp.YoutubeDL", side_effect=capture):
        (tmp_path / "v.mp4").write_bytes(b"x")
        download_video("https://example.com/v", tmp_path, "v", cancel_event=cancel)
    cancel.set()
    with pytest.raises(yt_dlp.utils.DownloadCancelled):
        hooks[0]({"status": "downloading"})
