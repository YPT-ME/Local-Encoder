"""Unit tests for encoder helpers."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from local_encoder import encoder
from local_encoder.encoder import (
    ALLOWED_RESOLUTIONS,
    ENCODING_SETTINGS,
    SOFTWARE_CODEC,
    EncodeCancelled,
    MediaInfo,
    VideoCodec,
    detect_video_codec,
    encode_hls,
    encode_mp4_multi,
    nearest_resolution,
    probe_media,
)


def test_all_resolutions_have_settings():
    for res in ALLOWED_RESOLUTIONS:
        s = ENCODING_SETTINGS[res]
        assert s["minrate"] > 0
        assert s["maxrate"] >= s["minrate"]
        assert s["bufsize"] >= s["maxrate"]
        assert s["audioBitrate"] > 0


def test_nearest_resolution_exact():
    for res in ALLOWED_RESOLUTIONS:
        assert nearest_resolution(res) == res


def test_nearest_resolution_rounds_down():
    # 900 is between 720 and 1080; 900 - 720 = 180, 1080 - 900 = 180 → tie goes to 720
    result = nearest_resolution(900)
    assert result in (720, 1080)


def test_nearest_resolution_low():
    assert nearest_resolution(0) == ALLOWED_RESOLUTIONS[0]


def test_nearest_resolution_high():
    assert nearest_resolution(9999) == ALLOWED_RESOLUTIONS[-1]


def test_output_resolution_reads_only_encoder_suffix() -> None:
    from local_encoder.encoder import output_resolution

    assert output_resolution(Path("My video_720p.mp4")) == 720
    assert output_resolution(Path("Episode_2024_360p.mp4")) == 360
    assert output_resolution(Path("Episode_2024.zip")) is None
    assert output_resolution(Path("clip_123p.mp4")) is None  # not an AVideo resolution
    assert output_resolution(Path("audio.mp3")) is None


# ---------------------------------------------------------------------------
# Fakes for FFmpeg / FFprobe (no real binaries in unit tests)
# ---------------------------------------------------------------------------

NVENC = VideoCodec(key="nvenc", label="NVIDIA graphics card", hardware=True, max_outputs=8)
QSV = VideoCodec(key="qsv", label="Intel graphics (Quick Sync)", hardware=True, max_outputs=8)
HD = MediaInfo(width=1280, height=720, has_video=True, has_audio=True)

DURATION_LINE = "  Duration: 00:00:10.00, start: 0.000000, bitrate: 100 kb/s"


def _time_line(seconds: int) -> str:
    return f"frame=  10 fps=0.0 q=0.0 size=  0kB time=00:00:{seconds:02d}.00 bitrate=1kbits/s"


class _Stderr:
    """stderr pipe of a fake FFmpeg; optionally blocks until the process is stopped."""

    def __init__(self, lines: list[str], stop: threading.Event | None) -> None:
        self._lines = lines
        self._stop = stop

    def __iter__(self) -> Iterator[str]:
        for line in self._lines:
            yield line + "\n"
        if self._stop is not None:
            self._stop.wait(5)

    def close(self) -> None:
        pass


class FakeProc:
    def __init__(
        self,
        cmd: list[str],
        returncode: int = 0,
        lines: list[str] | None = None,
        block: bool = False,
    ) -> None:
        self.cmd = cmd
        self._rc = returncode
        self.returncode: int | None = None
        self.terminated = False
        self._stop = threading.Event()
        self.stderr = _Stderr(lines or [], self._stop if block else None)

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = self._rc
        return self._rc

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self._rc = 255
        self._stop.set()

    def kill(self) -> None:
        self.terminate()


Behaviour = Callable[[list[str]], dict[str, Any]]


def _install_popen(monkeypatch: pytest.MonkeyPatch, behaviour: Behaviour) -> list[FakeProc]:
    procs: list[FakeProc] = []

    def fake_popen(cmd: list[str], **_: Any) -> FakeProc:
        proc = FakeProc(list(cmd), **behaviour(list(cmd)))
        procs.append(proc)
        return proc

    monkeypatch.setattr(encoder.subprocess, "Popen", fake_popen)
    return procs


def _ok(cmd: list[str]) -> dict[str, Any]:
    return {"lines": [DURATION_LINE, _time_line(5), _time_line(10)]}


def _fake_media(
    monkeypatch: pytest.MonkeyPatch,
    info: MediaInfo,
    audio_tracks: list[dict[str, Any]] | None = None,
) -> None:
    monkeypatch.setattr(encoder, "probe_media", lambda path, ffprobe_bin="ffprobe": info)
    monkeypatch.setattr(
        encoder, "_probe_audio_tracks", lambda path, ffprobe_bin="ffprobe": audio_tracks or []
    )


def _outputs(cmd: list[str]) -> list[str]:
    """MP4 output files (each follows ``-y``)."""
    return [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-y"]


def _hls_outputs(cmd: list[str]) -> list[str]:
    return [arg for arg in cmd if arg.endswith("index.m3u8")]


def _hls_video_cmds(procs: list[FakeProc]) -> list[list[str]]:
    return [p.cmd for p in procs if "-vn" not in p.cmd]


@pytest.fixture(autouse=True)
def _empty_codec_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encoder, "_codec_cache", {})


# ---------------------------------------------------------------------------
# detect_video_codec
# ---------------------------------------------------------------------------

ENCODERS_OUTPUT = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D h264_amf             AMD AMF H.264 Encoder (codec h264)
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V..... h264_qsv             H.264 / AVC (Intel Quick Sync Video acceleration) (codec h264)
 V....D h264_videotoolbox    VideoToolbox H.264 Encoder (codec h264)
 A....D aac                  AAC (Advanced Audio Coding)
"""


def _install_run(
    monkeypatch: pytest.MonkeyPatch,
    works: Callable[[str, int], bool],
    listing: str = ENCODERS_OUTPUT,
) -> list[list[str]]:
    """Fake ``subprocess.run``; ``works(encoder_name, outputs)`` decides each test encode."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        assert kwargs.get("timeout"), "every detection call needs a timeout"
        if "-encoders" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=listing, stderr="")
        ok = works(cmd[cmd.index("-c:v") + 1], cmd.count("null"))
        return subprocess.CompletedProcess(cmd, 0 if ok else 1, stdout="", stderr="no device")

    monkeypatch.setattr(encoder.subprocess, "run", fake_run)
    return calls


def _tested(calls: list[list[str]]) -> list[tuple[str, int]]:
    return [(c[c.index("-c:v") + 1], c.count("null")) for c in calls if "-c:v" in c]


def test_detect_prefers_working_hardware_and_probes_max_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(encoder, "_is_macos", lambda: False)
    # nvenc is listed but has no driver; qsv works with up to 3 outputs per run.
    calls = _install_run(monkeypatch, lambda name, n: name == "h264_qsv" and n <= 3)

    codec = detect_video_codec("my-ffmpeg")

    assert codec == VideoCodec("qsv", "Intel graphics (Quick Sync)", True, 3)
    assert calls[0] == ["my-ffmpeg", "-hide_banner", "-encoders"]
    assert _tested(calls) == [("h264_nvenc", 1), ("h264_qsv", 1), ("h264_qsv", 8), ("h264_qsv", 3)]
    assert all(c[0] == "my-ffmpeg" for c in calls)


def test_detect_test_encode_uses_real_encode_options(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encoder, "_is_macos", lambda: False)
    calls = _install_run(monkeypatch, lambda name, n: name == "h264_nvenc")

    codec = detect_video_codec("ffmpeg")

    assert codec.key == "nvenc" and codec.max_outputs == 8
    test_cmd = calls[1]
    i = test_cmd.index("-i")
    assert test_cmd[i - 2 : i + 2] == ["-f", "lavfi", "-i", "color=size=640x360:rate=30:duration=1"]
    for option in ("-force_key_frames", "-minrate", "-maxrate", "-bufsize", "-r"):
        assert option in test_cmd
    c = test_cmd.index("-c:v")
    assert test_cmd[c : c + 10] == [
        "-c:v", "h264_nvenc", "-preset:v", "p4", "-profile:v", "main",
        "-forced-idr", "1", "-pix_fmt", "yuv420p",
    ]  # fmt: skip
    assert test_cmd[-3:] == ["-f", "null", "-"]


def test_detect_single_output_when_multi_output_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encoder, "_is_macos", lambda: False)
    _install_run(monkeypatch, lambda name, n: name == "h264_amf" and n == 1)
    assert detect_video_codec("ffmpeg") == VideoCodec("amf", "AMD graphics card", True, 1)


def test_detect_falls_back_to_software(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encoder, "_is_macos", lambda: False)
    calls = _install_run(monkeypatch, lambda name, n: False)
    assert detect_video_codec("ffmpeg") is SOFTWARE_CODEC
    # videotoolbox is never tried outside macOS
    assert [name for name, _ in _tested(calls)] == ["h264_nvenc", "h264_qsv", "h264_amf"]


def test_detect_only_tries_listed_encoders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encoder, "_is_macos", lambda: False)
    listing = " V....D libx264              libx264 H.264\n V..... h264_qsv             QSV\n"
    calls = _install_run(monkeypatch, lambda name, n: True, listing=listing)
    assert detect_video_codec("ffmpeg").key == "qsv"
    assert _tested(calls)[0] == ("h264_qsv", 1)


def test_detect_videotoolbox_only_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encoder, "_is_macos", lambda: True)
    _install_run(monkeypatch, lambda name, n: name == "h264_videotoolbox")
    codec = detect_video_codec("ffmpeg")
    assert codec.key == "videotoolbox" and codec.label == "Apple hardware encoder"


def test_detect_is_cached_per_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encoder, "_is_macos", lambda: False)
    calls = _install_run(monkeypatch, lambda name, n: name == "h264_nvenc")
    first = detect_video_codec("ffmpeg")
    count = len(calls)
    assert detect_video_codec("ffmpeg") is first
    assert len(calls) == count
    detect_video_codec("other-ffmpeg")
    assert len(calls) > count


def test_detect_without_hardware_preference_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_run(monkeypatch, lambda name, n: True)
    assert detect_video_codec("ffmpeg", prefer_hardware=False) is SOFTWARE_CODEC
    assert calls == []


@pytest.mark.parametrize(
    "error", [FileNotFoundError("ffmpeg"), subprocess.TimeoutExpired(["ffmpeg"], 15)]
)
def test_detect_never_raises(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def broken_run(cmd: list[str], **_: Any) -> None:
        raise error

    monkeypatch.setattr(encoder.subprocess, "run", broken_run)
    assert detect_video_codec("ffmpeg") is SOFTWARE_CODEC


def test_detect_timeout_on_test_encode_tries_next(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encoder, "_is_macos", lambda: False)

    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        if "-encoders" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=ENCODERS_OUTPUT, stderr="")
        if "h264_nvenc" in cmd:
            raise subprocess.TimeoutExpired(cmd, 15)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(encoder.subprocess, "run", fake_run)
    assert detect_video_codec("ffmpeg").key == "qsv"


# ---------------------------------------------------------------------------
# probe_media
# ---------------------------------------------------------------------------


def _fake_ffprobe(monkeypatch: pytest.MonkeyPatch, stdout: str) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        assert kwargs.get("timeout")
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(encoder.subprocess, "run", fake_run)
    return calls


def test_probe_media_ignores_cover_art(monkeypatch: pytest.MonkeyPatch) -> None:
    streams = {
        "streams": [
            {"codec_type": "audio", "disposition": {"attached_pic": 0}},
            {
                "codec_type": "video",
                "width": 600,
                "height": 600,
                "disposition": {"attached_pic": 1},
            },
        ]
    }
    calls = _fake_ffprobe(monkeypatch, json.dumps(streams))
    info = probe_media(Path("-song.mp3"), "my-ffprobe")
    assert info == MediaInfo(width=0, height=0, has_video=False, has_audio=True)
    assert calls[0][0] == "my-ffprobe"
    # a file name starting with "-" is passed as an absolute path, never as an option
    assert Path(calls[0][-1]).is_absolute()


def test_probe_media_reads_first_real_video_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    streams = {
        "streams": [
            {
                "codec_type": "video",
                "width": 300,
                "height": 300,
                "disposition": {"attached_pic": 1},
            },
            {"codec_type": "video", "width": 1920, "height": 1080, "disposition": {}},
            {"codec_type": "audio"},
        ]
    }
    _fake_ffprobe(monkeypatch, json.dumps(streams))
    assert probe_media(Path("a.mkv")) == MediaInfo(1920, 1080, True, True)


@pytest.mark.parametrize("stdout", ["", "not json", "[]", '{"streams": "x"}', '{"streams": [1]}'])
def test_probe_media_bad_output(monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    _fake_ffprobe(monkeypatch, stdout)
    assert probe_media(Path("a.mp4")) == MediaInfo(0, 0, False, False)


def test_probe_media_timeout_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(cmd: list[str], **_: Any) -> None:
        raise subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr(encoder.subprocess, "run", slow)
    assert probe_media(Path("a.mp4")) == MediaInfo(0, 0, False, False)


def test_probe_media_missing_ffprobe_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(cmd: list[str], **_: Any) -> None:
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(encoder.subprocess, "run", missing)
    with pytest.raises(FileNotFoundError):
        probe_media(Path("a.mp4"))


# ---------------------------------------------------------------------------
# encode_mp4_multi
# ---------------------------------------------------------------------------


def test_mp4_software_command_matches_php_encoder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_media(monkeypatch, MediaInfo(640, 360, True, True))
    procs = _install_popen(monkeypatch, _ok)
    src = tmp_path / "in.mp4"

    encode_mp4_multi(src, tmp_path / "out", None, "my-ffmpeg", "ffprobe")

    assert len(procs) == 1
    expected = ["my-ffmpeg", "-i", str(src)]
    for res, (mn, mx, buf, ab) in {240: (300, 500, 1000, 48), 360: (500, 800, 1600, 64)}.items():
        expected += [
            "-preset", "veryfast", "-vf", f"scale=-2:{res}",
            "-b:v", f"{mx}k", "-minrate", f"{mn}k", "-maxrate", f"{mx}k", "-bufsize", f"{buf}k",
            "-c:v", "h264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", f"{ab}k",
            "-movflags", "+faststart", "-y", str(tmp_path / "out" / f"in_{res}p.mp4"),
        ]  # fmt: skip
    assert procs[0].cmd == expected


@pytest.mark.parametrize(
    ("codec", "codec_args"),
    [
        (NVENC, ["-c:v", "h264_nvenc", "-preset:v", "p4", "-pix_fmt", "yuv420p"]),
        (QSV, ["-c:v", "h264_qsv", "-preset:v", "veryfast", "-pix_fmt", "nv12"]),
        (
            VideoCodec("amf", "AMD graphics card", True, 8),
            ["-c:v", "h264_amf", "-quality:v", "speed", "-pix_fmt", "yuv420p"],
        ),
        (
            VideoCodec("videotoolbox", "Apple hardware encoder", True, 8),
            ["-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p"],
        ),
    ],
)
def test_mp4_hardware_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, codec: VideoCodec, codec_args: list[str]
) -> None:
    _fake_media(monkeypatch, HD)
    procs = _install_popen(monkeypatch, _ok)

    encode_mp4_multi(tmp_path / "in.mp4", tmp_path, [720], codec=codec)

    assert procs[0].cmd[3:] == [
        "-vf", "scale=-2:720",
        "-b:v", "2000k", "-minrate", "1500k", "-maxrate", "2000k", "-bufsize", "4000k",
        *codec_args,
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        "-y", str(tmp_path / "in_720p.mp4"),
    ]  # fmt: skip


def test_mp4_unknown_height_assumes_1080(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _fake_media(monkeypatch, MediaInfo(0, 0, True, True))
    procs = _install_popen(monkeypatch, _ok)

    encode_mp4_multi(tmp_path / "in.mp4", tmp_path)

    names = [Path(o).name for o in _outputs(procs[0].cmd)]
    assert names == [f"in_{r}p.mp4" for r in (240, 360, 480, 540, 720, 1080)]


def test_mp4_small_source_keeps_smallest_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_media(monkeypatch, MediaInfo(176, 144, True, True))
    procs = _install_popen(monkeypatch, _ok)
    encode_mp4_multi(tmp_path / "in.mp4", tmp_path, [360, 720])
    assert [Path(o).name for o in _outputs(procs[0].cmd)] == ["in_360p.mp4"]


def test_mp4_hardware_failure_falls_back_to_software(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _fake_media(monkeypatch, HD)

    def behaviour(cmd: list[str]) -> dict[str, Any]:
        for out in _outputs(cmd):
            Path(out).write_bytes(b"x")  # FFmpeg creates the files before failing
        if "h264_nvenc" in cmd:
            return {"returncode": 1, "lines": ["No NVENC capable devices found"]}
        return _ok(cmd)

    procs = _install_popen(monkeypatch, behaviour)
    partial_removed: list[bool] = []
    notices: list[str] = []

    def notice(kind: str) -> None:
        partial_removed.append(not (tmp_path / "in_240p.mp4").exists())
        notices.append(kind)

    with caplog.at_level(logging.WARNING, logger="local_encoder.encoder"):
        files = encode_mp4_multi(
            tmp_path / "in.mp4", tmp_path, [240, 480], codec=NVENC, notice_callback=notice
        )

    assert notices == ["hw_fallback"]
    assert partial_removed == [True]  # hardware outputs deleted before the software retry
    assert "h264_nvenc" in procs[0].cmd
    software = procs[1].cmd
    assert software[3:5] == ["-preset", "veryfast"]
    assert software[software.index("-c:v") + 1] == "h264"
    assert [f.name for f in files] == ["in_240p.mp4", "in_480p.mp4"]
    assert "No NVENC capable devices found" in caplog.text


def test_mp4_software_failure_raises_short_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _fake_media(monkeypatch, HD)
    noise = [f"noise line {i}" for i in range(100)]

    def behaviour(cmd: list[str]) -> dict[str, Any]:
        for out in _outputs(cmd):
            Path(out).write_bytes(b"partial")
        return {"returncode": 1, "lines": [*noise, "Invalid data found when processing input"]}

    _install_popen(monkeypatch, behaviour)
    notices: list[str] = []
    with (
        caplog.at_level(logging.ERROR, logger="local_encoder.encoder"),
        pytest.raises(RuntimeError) as err,
    ):
        encode_mp4_multi(tmp_path / "in.mp4", tmp_path, [240], notice_callback=notices.append)

    assert str(err.value) == "FFmpeg could not convert the video (exit code 1)"
    assert notices == []
    assert "Invalid data found when processing input" in caplog.text
    assert "noise line 50" not in caplog.text  # only the last stderr lines are kept
    assert not (tmp_path / "in_240p.mp4").exists()


def test_mp4_batches_respect_max_outputs_and_progress_is_monotonic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_media(monkeypatch, MediaInfo(1920, 1080, True, True))

    def behaviour(cmd: list[str]) -> dict[str, Any]:
        times = [_time_line(4), _time_line(2), _time_line(10), _time_line(12)]
        return {"lines": [DURATION_LINE, *times]}

    procs = _install_popen(monkeypatch, behaviour)
    seen: list[tuple[int, int]] = []

    encode_mp4_multi(
        tmp_path / "in.mp4",
        tmp_path,
        [240, 360, 480, 720, 1080],
        codec=replace(NVENC, max_outputs=2),
        progress_callback=lambda cur, total: seen.append((cur, total)),
    )

    assert [len(_outputs(p.cmd)) for p in procs] == [2, 2, 1]
    assert all("h264_nvenc" in p.cmd for p in procs)
    assert {total for _, total in seen} == {30}  # 10 s × 3 runs
    currents = [cur for cur, _ in seen]
    assert currents == sorted(currents)
    assert currents[-1] == 30


def test_mp4_cancel_stops_ffmpeg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _fake_media(monkeypatch, HD)

    def behaviour(cmd: list[str]) -> dict[str, Any]:
        for out in _outputs(cmd):
            Path(out).write_bytes(b"partial")
        return {"lines": [DURATION_LINE, _time_line(1)], "block": True}

    procs = _install_popen(monkeypatch, behaviour)
    cancel = threading.Event()
    timer = threading.Timer(0.2, cancel.set)
    timer.start()
    notices: list[str] = []

    with pytest.raises(EncodeCancelled):
        encode_mp4_multi(
            tmp_path / "in.mp4",
            tmp_path,
            [240, 360],
            codec=replace(NVENC, max_outputs=1),
            cancel_event=cancel,
            notice_callback=notices.append,
        )

    timer.join()
    assert len(procs) == 1  # no software retry and no next batch after a cancel
    assert procs[0].terminated
    assert notices == []
    assert list(tmp_path.glob("*.mp4")) == []


def test_mp4_cancel_before_start_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_media(monkeypatch, HD)
    procs = _install_popen(monkeypatch, _ok)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(EncodeCancelled):
        encode_mp4_multi(tmp_path / "in.mp4", tmp_path, cancel_event=cancel)
    assert procs == []


# ---------------------------------------------------------------------------
# encode_hls
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("languages", [("por", "por"), ("und", "und"), ("a!", "a?")])
def test_hls_keeps_each_audio_track_in_a_separate_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, languages: tuple[str, str]
) -> None:
    tracks = [
        {"index": i, "language": lang, "title": f"Track {i}"} for i, lang in enumerate(languages)
    ]
    _fake_media(monkeypatch, HD, tracks)

    def behaviour(cmd: list[str]) -> dict[str, Any]:
        if "-vn" in cmd:
            mapping = cmd[cmd.index("-map") + 1]
            Path(cmd[-1]).write_text(mapping, encoding="utf-8")
        return _ok(cmd)

    procs = _install_popen(monkeypatch, behaviour)
    encode_hls(tmp_path / "in.mp4", tmp_path, [240])

    audio_outputs = [Path(proc.cmd[-1]) for proc in procs if "-vn" in proc.cmd]
    assert len(set(audio_outputs)) == 2
    master = (tmp_path / "in" / "index.m3u8").read_text(encoding="utf-8")
    for i, output in enumerate(audio_outputs):
        assert output.read_text(encoding="utf-8") == f"0:a:{i}"
        assert f'URI="{output.relative_to(tmp_path / "in").as_posix()}"' in master


@pytest.mark.parametrize("titles", [("por", "por", "por (2)"), ('Main "audio"', "Main 'audio'")])
def test_hls_audio_options_have_unique_valid_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, titles: tuple[str, ...]
) -> None:
    tracks = [{"index": i, "language": "por", "title": title} for i, title in enumerate(titles)]
    _fake_media(monkeypatch, HD, tracks)

    def behaviour(cmd: list[str]) -> dict[str, Any]:
        if "-vn" in cmd:
            Path(cmd[-1]).write_text("#EXTM3U\n", encoding="utf-8")
        return _ok(cmd)

    _install_popen(monkeypatch, behaviour)
    encode_hls(tmp_path / "in.mp4", tmp_path, [240])
    master = (tmp_path / "in" / "index.m3u8").read_text(encoding="utf-8")
    names = re.findall(r'NAME="([^"]+)",LANGUAGE=', master)
    assert len(names) == len(titles)
    assert len(set(names)) == len(titles)


def test_hls_software_command_matches_php_encoder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_media(monkeypatch, MediaInfo(640, 360, True, True))
    procs = _install_popen(monkeypatch, _ok)
    src = tmp_path / "in.mp4"

    encode_hls(src, tmp_path / "out", [240, 360], "my-ffmpeg")

    (cmd,) = _hls_video_cmds(procs)
    work = tmp_path / "out" / "in"
    expected = ["my-ffmpeg", "-i", str(src)]
    # 20 fps at 240p like the PHP Encoder (Format.php videoFramerate), 30 fps otherwise
    for res, rate, fps in ((240, 500, 20), (360, 800, 30)):
        expected += [
            "-force_key_frames", "expr:gte(t,n_forced*6)", "-vf", f"scale=-2:{res}",
            "-b:v", f"{rate}k", "-r", str(fps), "-movflags", "+faststart",
            "-hls_time", "6", "-hls_flags", "independent_segments+split_by_time",
            "-hls_playlist_type", "vod", "-map", "0:v:0",
            "-c:v", "h264", "-profile:v", "main", "-pix_fmt", "yuv420p", "-f", "hls",
            "-hls_key_info_file", str(work / "keyinfo"),
            "-hls_segment_filename", str(work / f"res{res}" / "seg_%03d.ts"),
            str(work / f"res{res}" / "index.m3u8"),
        ]  # fmt: skip
    assert cmd == expected


def test_hls_hardware_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _fake_media(monkeypatch, HD)
    procs = _install_popen(monkeypatch, _ok)

    encode_hls(tmp_path / "in.mp4", tmp_path, [720], codec=QSV)

    (cmd,) = _hls_video_cmds(procs)
    c = cmd.index("-c:v")
    assert cmd[c : c + 10] == [
        "-c:v", "h264_qsv", "-preset:v", "veryfast", "-profile:v", "main",
        "-forced_idr", "1", "-pix_fmt", "nv12",
    ]  # fmt: skip
    assert cmd[cmd.index("-b:v") + 1] == "2000k"
    assert cmd[cmd.index("-map") + 1] == "0:v:0"


def test_hls_master_playlist_width_follows_aspect_ratio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_media(monkeypatch, MediaInfo(1440, 1080, True, True))  # 4:3
    _install_popen(monkeypatch, _ok)
    encode_hls(tmp_path / "in.mp4", tmp_path, [240, 360, 720])
    master = (tmp_path / "in" / "index.m3u8").read_text(encoding="utf-8")
    assert "RESOLUTION=320x240" in master
    assert "RESOLUTION=480x360" in master
    assert "RESOLUTION=960x720" in master


def test_hls_master_width_rounds_down_to_even_and_defaults_to_16_9() -> None:
    assert encoder._hls_master_width(720, MediaInfo(1080, 1920, True, True)) == 404  # 405
    assert encoder._hls_master_width(240, MediaInfo(0, 0, True, True)) == 426
    assert encoder._hls_master_width(1080, MediaInfo(0, 0, True, True)) == 1920


def test_hls_unknown_height_assumes_1080(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _fake_media(monkeypatch, MediaInfo(0, 0, True, True))
    procs = _install_popen(monkeypatch, _ok)
    encode_hls(tmp_path / "in.mp4", tmp_path)
    (cmd,) = _hls_video_cmds(procs)
    assert [Path(o).parent.name for o in _hls_outputs(cmd)] == [
        f"res{r}" for r in (240, 360, 480, 540, 720, 1080)
    ]


def test_hls_progress_never_exceeds_total(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Regression: playlists written during the encode used to push progress past 100 %."""
    _fake_media(monkeypatch, MediaInfo(1920, 1080, True, True))

    def behaviour(cmd: list[str]) -> dict[str, Any]:
        for out in _hls_outputs(cmd):
            Path(out).write_text("#EXTM3U\n", encoding="utf-8")
        return {"lines": [DURATION_LINE, _time_line(3), _time_line(9), _time_line(10)]}

    procs = _install_popen(monkeypatch, behaviour)
    seen: list[tuple[int, int]] = []
    encode_hls(
        tmp_path / "in.mp4",
        tmp_path,
        [240, 360, 720],
        codec=replace(NVENC, max_outputs=2),
        progress_callback=lambda cur, total: seen.append((cur, total)),
    )
    assert [len(_hls_outputs(c)) for c in _hls_video_cmds(procs)] == [2, 1]
    assert all(cur <= total == 20 for cur, total in seen)  # 10 s × 2 runs
    currents = [cur for cur, _ in seen]
    assert currents == sorted(currents) and currents[-1] == 20


def test_hls_hardware_failure_falls_back_to_software(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_media(monkeypatch, HD)

    def behaviour(cmd: list[str]) -> dict[str, Any]:
        if "h264_nvenc" in cmd:
            for out in _hls_outputs(cmd):
                (Path(out).parent / "seg_000.ts").write_bytes(b"partial")
            return {"returncode": 1, "lines": ["OpenEncodeSessionEx failed"]}
        return _ok(cmd)

    procs = _install_popen(monkeypatch, behaviour)
    notices: list[str] = []
    zip_path = encode_hls(
        tmp_path / "in.mp4", tmp_path, [240], codec=NVENC, notice_callback=notices.append
    )
    assert notices == ["hw_fallback"]
    hardware, software = _hls_video_cmds(procs)
    assert "h264_nvenc" in hardware
    assert software[software.index("-c:v") + 1] == "h264"
    assert not (tmp_path / "in" / "res240" / "seg_000.ts").exists()
    assert zip_path.exists()


def test_hls_cancel_between_audio_tracks_removes_work_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tracks = [
        {"index": 0, "language": "eng", "title": "English"},
        {"index": 1, "language": "por", "title": "Portuguese"},
    ]
    _fake_media(monkeypatch, HD, tracks)
    cancel = threading.Event()

    def behaviour(cmd: list[str]) -> dict[str, Any]:
        cancel.set()  # the user cancels while the first audio track encodes
        return _ok(cmd)

    procs = _install_popen(monkeypatch, behaviour)
    with pytest.raises(EncodeCancelled):
        encode_hls(tmp_path / "in.mp4", tmp_path, [240], cancel_event=cancel)
    assert len(procs) == 1
    assert not (tmp_path / "in").exists()
    assert not (tmp_path / "in.zip").exists()


def test_hls_video_cancel_terminates_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_media(monkeypatch, HD)
    procs = _install_popen(monkeypatch, lambda cmd: {"lines": [DURATION_LINE], "block": True})
    cancel = threading.Event()
    timer = threading.Timer(0.2, cancel.set)
    timer.start()
    with pytest.raises(EncodeCancelled):
        encode_hls(tmp_path / "in.mp4", tmp_path, [240, 360], cancel_event=cancel)
    timer.join()
    assert len(procs) == 1 and procs[0].terminated
    assert not (tmp_path / "in").exists()
