"""FFmpeg-based video encoding and thumbnail generation.

Encoding settings are taken directly from AVideo's Format.php
``ENCODING_SETTINGS`` array so the output matches what the server expects.

Thumbnail commands mirror AVideo's getImage.php / Encoder.php methods:
  ``getImage``      → extract_thumbnail_jpg
  ``getGifImage``   → extract_thumbnail_gif
  ``getWebpImage``  → extract_thumbnail_webp

HLS support mirrors AVideo's HLSProcessor.php:
  ``encode_hls``    → multi-resolution HLS + AES-128 encryption → zipped

Video can be encoded on a graphics card (``detect_video_codec``); a failed hardware encode is
redone automatically with the software encoder the PHP Encoder uses.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import subprocess
import sys
import threading
import zipfile
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EncodeProgressCallback = Callable[[int, int], None]
"""Called as ``callback(current_seconds, total_seconds)``."""

# Mirrors AVideo Format.php ENCODING_SETTINGS
ENCODING_SETTINGS: dict[int, dict[str, int]] = {
    240: {"minrate": 300, "maxrate": 500, "bufsize": 1000, "audioBitrate": 48},
    360: {"minrate": 500, "maxrate": 800, "bufsize": 1600, "audioBitrate": 64},
    480: {"minrate": 800, "maxrate": 1000, "bufsize": 2000, "audioBitrate": 96},
    540: {"minrate": 1000, "maxrate": 1500, "bufsize": 3000, "audioBitrate": 96},
    720: {"minrate": 1500, "maxrate": 2000, "bufsize": 4000, "audioBitrate": 128},
    1080: {"minrate": 3000, "maxrate": 4000, "bufsize": 8000, "audioBitrate": 128},
    1440: {"minrate": 6000, "maxrate": 8000, "bufsize": 16000, "audioBitrate": 160},
    2160: {"minrate": 8000, "maxrate": 12000, "bufsize": 24000, "audioBitrate": 160},
}

ALLOWED_RESOLUTIONS: list[int] = sorted(ENCODING_SETTINGS.keys())


def nearest_resolution(height: int) -> int:
    """Return the ENCODING_SETTINGS resolution closest to *height*."""
    return min(ALLOWED_RESOLUTIONS, key=lambda r: abs(r - height))


def output_resolution(path: Path) -> int | None:
    """Return the resolution of an ``encode_mp4_multi`` output (``<stem>_<res>p.mp4``).

    Only the ``_<res>p`` suffix this module appends is read, and only an allowed value is
    accepted, so a title ending in digits can never produce an invalid ``resolution``.
    Returns ``None`` for files stored without a resolution (HLS zip, mp3).
    """
    match = re.search(r"_(\d+)p$", path.stem)
    if path.suffix.lower() != ".mp4" or not match:
        return None
    value = int(match.group(1))
    return value if value in ALLOWED_RESOLUTIONS else None


# ---------------------------------------------------------------------------
# Video codec selection (software or graphics card)
# ---------------------------------------------------------------------------


class EncodeCancelled(Exception):
    """Raised when an encode stops because its ``cancel_event`` was set."""


@dataclass(frozen=True)
class VideoCodec:
    """H.264 encoder used for the video outputs.

    ``max_outputs`` is how many outputs one FFmpeg process may encode at once (consumer NVIDIA
    cards limit concurrent NVENC sessions); a longer ladder is split into sequential runs.
    """

    key: str
    label: str
    hardware: bool
    max_outputs: int


SOFTWARE_CODEC = VideoCodec(
    key="software", label="Processor (software)", hardware=False, max_outputs=99
)

# (key, FFmpeg encoder, plain-language label, macOS only), in order of preference.
_HARDWARE_CANDIDATES: tuple[tuple[str, str, str, bool], ...] = (
    ("videotoolbox", "h264_videotoolbox", "Apple hardware encoder", True),
    ("nvenc", "h264_nvenc", "NVIDIA graphics card", False),
    ("qsv", "h264_qsv", "Intel graphics (Quick Sync)", False),
    ("amf", "h264_amf", "AMD graphics card", False),
)
_DETECT_TIMEOUT_SECONDS = 15
_MAX_OUTPUTS_STEPS = (8, 3)
_STDERR_TAIL_LINES = 20
_STOP_GRACE_SECONDS = 5
# Format.php getResolution() assumes 1080 when ffprobe gives no height.
_UNKNOWN_HEIGHT = 1080

_codec_cache: dict[str, VideoCodec] = {}
_codec_lock = threading.Lock()


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _video_codec_args(codec: VideoCodec, *, hls: bool) -> list[str]:
    """Return the ``-c:v …`` arguments for *codec*; software mirrors the PHP Encoder."""
    profile = ["-profile:v", "main"] if hls else []
    if codec.key == "nvenc":
        # Forced key frames must be IDR frames so every HLS segment starts independently.
        idr = ["-forced-idr", "1"] if hls else []
        return ["-c:v", "h264_nvenc", "-preset:v", "p4", *profile, *idr, "-pix_fmt", "yuv420p"]
    if codec.key == "qsv":
        idr = ["-forced_idr", "1"] if hls else []
        return ["-c:v", "h264_qsv", "-preset:v", "veryfast", *profile, *idr, "-pix_fmt", "nv12"]
    if codec.key == "amf":
        return ["-c:v", "h264_amf", "-quality:v", "speed", *profile, "-pix_fmt", "yuv420p"]
    if codec.key == "videotoolbox":
        return ["-c:v", "h264_videotoolbox", *profile, "-pix_fmt", "yuv420p"]
    return ["-c:v", "h264", *profile, "-pix_fmt", "yuv420p"]


def _detection_cmd(ffmpeg_bin: str, codec: VideoCodec, outputs: int) -> list[str]:
    """Tiny lavfi encode using every video option the real MP4 and HLS encodes use."""
    s = ENCODING_SETTINGS[240]
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=size=640x360:rate=30:duration=1",
    ]
    for _ in range(outputs):
        cmd += [
            "-force_key_frames",
            "expr:gte(t,n_forced*6)",
            "-vf",
            "scale=-2:240",
            "-b:v",
            f"{s['maxrate']}k",
            "-minrate",
            f"{s['minrate']}k",
            "-maxrate",
            f"{s['maxrate']}k",
            "-bufsize",
            f"{s['bufsize']}k",
            "-r",
            "20",
            *_video_codec_args(codec, hls=True),
            "-an",
            "-f",
            "null",
            "-",
        ]
    return cmd


def _ffmpeg_succeeds(cmd: list[str]) -> bool:
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_DETECT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Encoder test did not run: %s", exc)
        return False
    if result.returncode != 0:
        logger.debug(
            "Encoder test failed (exit code %d): %s",
            result.returncode,
            " | ".join((result.stderr or "").strip().splitlines()[-3:]),
        )
    return result.returncode == 0


def _list_video_encoders(ffmpeg_bin: str) -> set[str]:
    result = subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-encoders"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_DETECT_TIMEOUT_SECONDS,
    )
    names: set[str] = set()
    for line in (result.stdout or "").splitlines():
        match = re.match(r"^\s*V[A-Z.]{5}\s+(\S+)", line)
        if match:
            names.add(match.group(1))
    return names


def _detect_video_codec(ffmpeg_bin: str) -> VideoCodec:
    try:
        available = _list_video_encoders(ffmpeg_bin)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("Could not list the FFmpeg encoders (%s); using the processor", exc)
        return SOFTWARE_CODEC

    for key, encoder_name, label, macos_only in _HARDWARE_CANDIDATES:
        if encoder_name not in available or (macos_only and not _is_macos()):
            continue
        candidate = VideoCodec(key=key, label=label, hardware=True, max_outputs=1)
        if not _ffmpeg_succeeds(_detection_cmd(ffmpeg_bin, candidate, 1)):
            logger.info("%s (%s) is in FFmpeg but does not work here", label, encoder_name)
            continue
        max_outputs = 1
        for outputs in _MAX_OUTPUTS_STEPS:
            if _ffmpeg_succeeds(_detection_cmd(ffmpeg_bin, candidate, outputs)):
                max_outputs = outputs
                break
        codec = VideoCodec(key=key, label=label, hardware=True, max_outputs=max_outputs)
        logger.info(
            "Video encoder: %s (%s, up to %d outputs per FFmpeg run)",
            label,
            encoder_name,
            max_outputs,
        )
        return codec

    logger.info("Video encoder: %s (no working hardware encoder found)", SOFTWARE_CODEC.label)
    return SOFTWARE_CODEC


def detect_video_codec(ffmpeg_bin: str, prefer_hardware: bool = True) -> VideoCodec:
    """Return the fastest H.264 encoder that really works with *ffmpeg_bin*.

    A hardware encoder listed by ``ffmpeg -encoders`` is only chosen after a tiny test encode
    succeeds (the driver or graphics card may be missing). The result is cached per binary.
    Never raises: any problem means the software encoder.
    """
    if not prefer_hardware:
        return SOFTWARE_CODEC
    with _codec_lock:
        cached = _codec_cache.get(ffmpeg_bin)
        if cached is None:
            try:
                cached = _detect_video_codec(ffmpeg_bin)
            except Exception:
                logger.exception("Hardware encoder detection failed; using the processor")
                cached = SOFTWARE_CODEC
            _codec_cache[ffmpeg_bin] = cached
        return cached


# ---------------------------------------------------------------------------
# Media probing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MediaInfo:
    """What ``probe_media`` found in a media file (zeros/False when unknown)."""

    width: int
    height: int
    has_video: bool
    has_audio: bool


def _positive_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def probe_media(input_path: Path, ffprobe_bin: str = "ffprobe") -> MediaInfo:
    """Return the size of the first real video stream and whether video/audio exist.

    Cover art (``disposition.attached_pic``, e.g. in MP3/M4A files) does not count as video.
    Unreadable output gives an empty ``MediaInfo``; a missing ffprobe raises
    ``FileNotFoundError`` so the caller can say that FFmpeg is missing.
    """
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,width,height:stream_disposition=attached_pic",
        "-of",
        "json",
        str(input_path.absolute()),
    ]
    empty = MediaInfo(width=0, height=0, has_video=False, has_audio=False)
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe took too long to read %s", input_path.name)
        return empty
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        logger.warning("ffprobe returned unreadable output for %s", input_path.name)
        return empty
    streams = data.get("streams") if isinstance(data, dict) else None
    if not isinstance(streams, list):
        return empty

    width = height = 0
    has_video = has_audio = False
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        kind = stream.get("codec_type")
        if kind == "audio":
            has_audio = True
        elif kind == "video" and not has_video:
            disposition = stream.get("disposition")
            if isinstance(disposition, dict) and _positive_int(disposition.get("attached_pic")):
                continue
            has_video = True
            width = _positive_int(stream.get("width"))
            height = _positive_int(stream.get("height"))
    return MediaInfo(width=width, height=height, has_video=has_video, has_audio=has_audio)


def _eligible_resolutions(resolutions: list[int] | None, info: MediaInfo) -> list[int]:
    """Ladder steps not taller than the source (never upscale); at least the smallest one."""
    wanted = sorted(resolutions) if resolutions else list(ALLOWED_RESOLUTIONS)
    source_height = info.height
    if source_height <= 0:
        logger.info("Video height unknown; assuming %dp like the AVideo Encoder", _UNKNOWN_HEIGHT)
        source_height = _UNKNOWN_HEIGHT
    return [r for r in wanted if r <= source_height] or [wanted[0]]


# ---------------------------------------------------------------------------
# Running FFmpeg (progress, cancel, hardware fallback)
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")
_TIME_RE = re.compile(r"time=(\d+):(\d+):([\d.]+)")


class _FFmpegFailed(Exception):
    def __init__(self, returncode: int, tail: list[str]) -> None:
        super().__init__(f"FFmpeg exited with code {returncode}")
        self.returncode = returncode
        self.tail = tail


def _seconds(match: re.Match[str]) -> float:
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


class _Progress:
    """Merge the ``time=`` of sequential FFmpeg runs into one monotonic, capped progress.

    ``total = duration × runs``; ``current = finished runs × duration + time in this run``.
    """

    def __init__(self, callback: EncodeProgressCallback | None, runs: int) -> None:
        self._callback = callback
        self._runs = max(runs, 1)
        self._finished = 0
        self._last = -1
        self.duration = 0.0

    def update(self, seconds: float) -> None:
        if self._callback is None or self.duration <= 0:
            return
        total = int(self.duration * self._runs)
        if total <= 0:
            return
        elapsed = self._finished * self.duration + min(max(seconds, 0.0), self.duration)
        current = min(int(elapsed), total)
        if current > self._last:
            self._last = current
            self._callback(current, total)

    def finish_run(self) -> None:
        self._finished = min(self._finished + 1, self._runs)
        self.update(0.0)


def _stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _stop_on_cancel(
    proc: subprocess.Popen[str], cancel_event: threading.Event, finished: threading.Event
) -> None:
    while not finished.is_set():
        if cancel_event.wait(0.2):
            if not finished.is_set():
                _stop_process(proc)
            return


def _run_ffmpeg(
    cmd: list[str],
    *,
    cancel_event: threading.Event | None,
    progress: _Progress | None,
) -> None:
    """Run one FFmpeg command; raise ``EncodeCancelled`` or ``_FFmpegFailed`` on failure."""
    if cancel_event is not None and cancel_event.is_set():
        raise EncodeCancelled("The encode was cancelled")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    finished = threading.Event()
    watcher: threading.Thread | None = None
    if cancel_event is not None:
        watcher = threading.Thread(
            target=_stop_on_cancel,
            args=(proc, cancel_event, finished),
            name="ffmpeg-cancel-watcher",
            daemon=True,
        )
        watcher.start()
    tail: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
    try:
        for raw_line in proc.stderr or []:
            line = raw_line.rstrip()
            if line and not line.startswith(("frame=", "size=")):
                tail.append(line)
            if progress is None:
                continue
            if progress.duration == 0.0 and "Duration:" in line:
                match = _DURATION_RE.search(line)
                if match:
                    progress.duration = _seconds(match)
            if "time=" in line:
                match = _TIME_RE.search(line)
                if match:
                    progress.update(_seconds(match))
        returncode = proc.wait()
    finally:
        finished.set()
        if proc.poll() is None:
            _stop_process(proc)
        if proc.stderr is not None:
            proc.stderr.close()
        if watcher is not None:
            watcher.join(timeout=_STOP_GRACE_SECONDS + 1)
    if cancel_event is not None and cancel_event.is_set():
        raise EncodeCancelled("The encode was cancelled")
    if returncode != 0:
        raise _FFmpegFailed(returncode, list(tail))


def _batches(resolutions: list[int], size: int) -> list[list[int]]:
    size = max(size, 1)
    return [resolutions[i : i + size] for i in range(0, len(resolutions), size)]


def _encode_with_fallback(
    run: Callable[[VideoCodec], None],
    codec: VideoCodec,
    cleanup: Callable[[], None],
    notice_callback: Callable[[str], None] | None,
) -> None:
    """Run *run* with *codec*; redo it with the software encoder if the hardware one fails."""
    try:
        if codec.hardware:
            try:
                run(codec)
                return
            except _FFmpegFailed as exc:
                logger.warning(
                    "%s could not convert the video (FFmpeg exit code %d); converting again "
                    "with the processor. Last FFmpeg output:\n%s",
                    codec.label,
                    exc.returncode,
                    "\n".join(exc.tail),
                )
                cleanup()
                if notice_callback is not None:
                    notice_callback("hw_fallback")
        try:
            run(SOFTWARE_CODEC)
        except _FFmpegFailed as exc:
            logger.error(
                "FFmpeg could not convert the video (exit code %d). Last FFmpeg output:\n%s",
                exc.returncode,
                "\n".join(exc.tail),
            )
            cleanup()
            raise RuntimeError(
                f"FFmpeg could not convert the video (exit code {exc.returncode})"
            ) from exc
    except EncodeCancelled:
        cleanup()
        raise


def encode_mp4(
    input_path: Path,
    output_path: Path,
    resolution: int,
    ffmpeg_bin: str = "ffmpeg",
    progress_callback: EncodeProgressCallback | None = None,
) -> Path:
    """Re-encode *input_path* to H.264 MP4 at *resolution* pixels tall.

    Uses AVideo's exact bitrate ladder (ENCODING_SETTINGS) and the
    ``-preset veryfast -movflags +faststart`` flags that the PHP encoder uses.
    Mirrors AVideo's MP4Processor.php ``process()`` method.
    """
    if resolution not in ENCODING_SETTINGS:
        raise ValueError(
            f"Unsupported resolution {resolution}p. Choose from: {ALLOWED_RESOLUTIONS}"
        )
    s = ENCODING_SETTINGS[resolution]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_bin,
        "-i",
        str(input_path),
        "-preset",
        "veryfast",
        "-vf",
        f"scale=-2:{resolution}",
        "-b:v",
        f"{s['maxrate']}k",
        "-minrate",
        f"{s['minrate']}k",
        "-maxrate",
        f"{s['maxrate']}k",
        "-bufsize",
        f"{s['bufsize']}k",
        "-c:v",
        "h264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        f"{s['audioBitrate']}k",
        "-movflags",
        "+faststart",
        "-y",
        str(output_path),
    ]
    logger.info("Encoding %dp MP4: %s", resolution, " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    duration_secs: float = 0.0
    for line in proc.stderr or []:
        # Parse total duration from the first FFmpeg diagnostic line
        if duration_secs == 0.0 and "Duration:" in line:
            m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", line)
            if m:
                duration_secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        # Report encode progress
        if progress_callback and "time=" in line:
            m = re.search(r"time=(\d+):(\d+):([\d.]+)", line)
            if m and duration_secs > 0:
                current = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                progress_callback(int(current), int(duration_secs))

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg encode failed with exit code {proc.returncode} (command: {' '.join(cmd)})"
        )
    return output_path


def encode_mp4_multi(
    input_path: Path,
    output_dir: Path,
    resolutions: list[int] | None = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    progress_callback: EncodeProgressCallback | None = None,
    codec: VideoCodec | None = None,
    cancel_event: threading.Event | None = None,
    notice_callback: Callable[[str], None] | None = None,
) -> list[Path]:
    """Re-encode *input_path* to multiple H.264 MP4 files.

    Mirrors AVideo's ``getDynamicCommandFromFormat()`` in Format.php: all resolutions ≤ source
    height are produced by one ``ffmpeg -i … out1 out2 …`` run, or by several sequential runs
    when *codec* limits the outputs per run. *codec* ``None`` means the software encoder; a
    failed hardware encode is redone in software after ``notice_callback("hw_fallback")``.
    Returns the output paths in ascending resolution order.
    """
    input_path = input_path.absolute()
    output_dir = output_dir.absolute()
    eligible = _eligible_resolutions(resolutions, probe_media(input_path, ffprobe_bin))

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {res: output_dir / f"{input_path.stem}_{res}p.mp4" for res in eligible}

    def build_cmd(group: list[int], video_codec: VideoCodec) -> list[str]:
        cmd: list[str] = [ffmpeg_bin, "-i", str(input_path)]
        for res in group:
            s = ENCODING_SETTINGS[res]
            if not video_codec.hardware:
                cmd += ["-preset", "veryfast"]
            cmd += [
                "-vf",
                f"scale=-2:{res}",
                "-b:v",
                f"{s['maxrate']}k",
                "-minrate",
                f"{s['minrate']}k",
                "-maxrate",
                f"{s['maxrate']}k",
                "-bufsize",
                f"{s['bufsize']}k",
                *_video_codec_args(video_codec, hls=False),
                "-c:a",
                "aac",
                "-b:a",
                f"{s['audioBitrate']}k",
                "-movflags",
                "+faststart",
                "-y",
                str(outputs[res]),
            ]
        return cmd

    def run(video_codec: VideoCodec) -> None:
        groups = _batches(eligible, video_codec.max_outputs)
        progress = _Progress(progress_callback, len(groups))
        for group in groups:
            cmd = build_cmd(group, video_codec)
            logger.info("MP4 %s with %s: %s", group, video_codec.label, " ".join(cmd))
            _run_ffmpeg(cmd, cancel_event=cancel_event, progress=progress)
            progress.finish_run()

    def cleanup() -> None:
        for path in outputs.values():
            path.unlink(missing_ok=True)

    _encode_with_fallback(run, codec or SOFTWARE_CODEC, cleanup, notice_callback)
    return [outputs[res] for res in eligible if outputs[res].exists()]


def extract_mp3(
    input_path: Path,
    output_path: Path,
    ffmpeg_bin: str = "ffmpeg",
    bitrate: int = 128,
) -> Path:
    """Extract audio to MP3.

    Mirrors AVideo's ``MP3Processor::createMP3()`` / ``generateFFmpegCommand()``:
      ffmpeg -i input -preset veryfast -vn -c:a libmp3lame -b:a 128k -movflags +faststart output.mp3
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-i",
        str(input_path),
        "-preset",
        "veryfast",
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        f"{bitrate}k",
        "-movflags",
        "+faststart",
        "-y",
        str(output_path),
    ]
    logger.info("Extracting MP3: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, timeout=3600)
    if result.returncode != 0:
        raise RuntimeError(
            f"MP3 extraction failed: {result.stderr.decode(errors='replace')[-400:]}"
        )
    return output_path


def extract_thumbnail_jpg(
    input_path: Path,
    output_path: Path,
    seek_seconds: float,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    """Extract a single frame at *seek_seconds* as a JPEG thumbnail.

    Mirrors Encoder.php ``getImage()`` / getImage.php thumbnail command.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-ss",
        str(int(seek_seconds)),
        "-i",
        str(input_path),
        "-vframes",
        "1",
        "-y",
        str(output_path),
    ]
    logger.info("Extracting JPG thumbnail: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode != 0 and not output_path.exists():
        raise RuntimeError(f"Thumbnail extraction failed: {result.stderr.decode(errors='replace')}")
    return output_path


def extract_thumbnail_gif(
    input_path: Path,
    output_path: Path,
    seek_seconds: float,
    duration: float = 3.0,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    """Generate an animated GIF thumbnail.

    Uses a two-pass palette approach (320 × 180 px, 10 fps, *duration* seconds).
    Mirrors Encoder.php ``getGifImage()``.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    palette_path = output_path.with_suffix(".palette.png")

    try:
        # Pass 1 – generate colour palette
        cmd_palette = [
            ffmpeg_bin,
            "-y",
            "-ss",
            str(int(seek_seconds)),
            "-t",
            str(duration),
            "-i",
            str(input_path),
            "-vf",
            "fps=10,scale=320:-1:flags=lanczos,palettegen",
            str(palette_path),
        ]
        result = subprocess.run(cmd_palette, capture_output=True, timeout=60)
        if result.returncode != 0 or not palette_path.exists():
            raise RuntimeError(
                f"GIF palette generation failed: {result.stderr.decode(errors='replace')}"
            )

        # Pass 2 – render GIF with letter-boxing to 320 × 180
        scale_filter = (
            "fps=10,"
            "scale=(iw*sar)*min(320/(iw*sar)\\,180/ih)"
            ":ih*min(320/(iw*sar)\\,180/ih)"
            ":flags=lanczos"
            "[x];[x][1:v]paletteuse,"
            "pad=320:180"
            ":(320-iw*min(320/iw\\,180/ih))/2"
            ":(180-ih*min(320/iw\\,180/ih))/2"
        )
        cmd_gif = [
            ffmpeg_bin,
            "-ss",
            str(int(seek_seconds)),
            "-t",
            str(duration),
            "-i",
            str(input_path),
            "-i",
            str(palette_path),
            "-filter_complex",
            scale_filter,
            "-y",
            str(output_path),
        ]
        result = subprocess.run(cmd_gif, capture_output=True, timeout=120)
        if result.returncode == 0 and output_path.exists():
            return output_path

        # Fallback – simpler scale without letter-boxing
        cmd_fallback = [
            ffmpeg_bin,
            "-ss",
            str(int(seek_seconds)),
            "-t",
            str(duration),
            "-i",
            str(input_path),
            "-i",
            str(palette_path),
            "-filter_complex",
            "fps=10,scale=320:-1:flags=lanczos[x];[x][1:v]paletteuse",
            "-y",
            str(output_path),
        ]
        result = subprocess.run(cmd_fallback, capture_output=True, timeout=120)
        if result.returncode != 0 and not output_path.exists():
            raise RuntimeError(f"GIF generation failed: {result.stderr.decode(errors='replace')}")
        return output_path

    finally:
        palette_path.unlink(missing_ok=True)


def extract_thumbnail_webp(
    input_path: Path,
    output_path: Path,
    seek_seconds: float,
    duration: float = 3.0,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    """Generate an animated WebP thumbnail.

    640 × 360 px, 10 fps, *duration* seconds, lossless.
    Mirrors Encoder.php ``getWebpImage()``.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scale_filter = (
        "fps=10,"
        "scale=(iw*sar)*min(640/(iw*sar)\\,360/ih)"
        ":ih*min(640/(iw*sar)\\,360/ih)"
        ":flags=lanczos,"
        "pad=640:360"
        ":(640-iw*min(640/iw\\,360/ih))/2"
        ":(360-ih*min(640/iw\\,360/ih))/2"
    )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss",
        str(int(seek_seconds)),
        "-t",
        str(duration),
        "-i",
        str(input_path),
        "-vcodec",
        "libwebp",
        "-lossless",
        "1",
        "-vf",
        scale_filter,
        "-q",
        "60",
        "-preset",
        "default",
        "-loop",
        "0",
        "-an",
        # No "-vsync 0" (Encoder.php still has it): FFmpeg 9 removed the option and its
        # replacement "-fps_mode" does not exist before FFmpeg 5.1. The fps=10 filter already
        # fixes the frame rate, so neither is needed.
        str(output_path),
    ]
    logger.info("Extracting WebP thumbnail: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode != 0 and not output_path.exists():
        raise RuntimeError(f"WebP extraction failed: {result.stderr.decode(errors='replace')}")
    return output_path


# ---------------------------------------------------------------------------
# HLS helpers
# ---------------------------------------------------------------------------


def _probe_audio_tracks(input_path: Path, ffprobe_bin: str = "ffprobe") -> list[dict[str, Any]]:
    """Return a list of audio-track dicts with keys index, language, title.

    Mirrors HLSProcessor::getAudioTracks().
    """
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index:stream_tags=language,title",
        "-of",
        "json",
        str(input_path.absolute()),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout or "{}")
        tracks = []
        for i, stream in enumerate(data.get("streams", [])):
            tags = stream.get("tags", {})
            lang = tags.get("language") or "Default"
            title = tags.get("title") or lang
            if lang == "und":
                lang = "Default"
            if title == "und":
                title = "Default"
            tracks.append({"index": i, "language": lang, "title": title})
        return tracks or [{"index": 0, "language": "Default", "title": "Default"}]
    except Exception as exc:
        logger.warning("Could not probe audio tracks (%s); using single default track", exc)
        return [{"index": 0, "language": "Default", "title": "Default"}]


def _hls_framerate(resolution: int) -> int:
    """Format.php ``videoFramerate``: 20 fps at 240p, otherwise HLSProcessor's 30 fps."""
    return 20 if resolution == 240 else 30


def _hls_master_width(resolution: int, info: MediaInfo) -> int:
    """Even width for the master playlist, from the source aspect ratio (16:9 if unknown).

    Mirrors HLSProcessor::getScaledWidth() / getDefaultWidth().
    """
    if info.width > 0 and info.height > 0:
        width = resolution * info.width // info.height
    else:
        width = resolution * 16 // 9
    return width - width % 2


def encode_hls(
    input_path: Path,
    output_dir: Path,
    resolutions: list[int] | None = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    hls_time: int = 6,
    encrypt: bool = True,
    progress_callback: EncodeProgressCallback | None = None,
    codec: VideoCodec | None = None,
    cancel_event: threading.Event | None = None,
    notice_callback: Callable[[str], None] | None = None,
) -> Path:
    """Encode *input_path* to multi-resolution AES-128 HLS and return the ZIP path.

    Mirrors AVideo's HLSProcessor::createHLSWithAudioTracks() + zipDirectory().
    *codec*, *cancel_event* and *notice_callback* work as in ``encode_mp4_multi``.

    Structure inside the ZIP (also on disk before zipping):
      index.m3u8           – master playlist
      enc_XXXX.key         – AES-128 key (16 raw bytes)
      keyinfo              – FFmpeg key-info file
      audio_tracks/<lang>/audio.m3u8 + *.ts
      res<N>/index.m3u8 + *.ts

    Returns the path to the produced ``.zip`` file.
    """
    input_path = input_path.absolute()
    output_dir = output_dir.absolute()
    info = probe_media(input_path, ffprobe_bin)
    audio_tracks = _probe_audio_tracks(input_path, ffprobe_bin)
    eligible = _eligible_resolutions(resolutions, info)

    work_dir = output_dir / input_path.stem
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        return _encode_hls_in(
            input_path,
            work_dir,
            eligible,
            info,
            audio_tracks,
            ffmpeg_bin=ffmpeg_bin,
            hls_time=hls_time,
            encrypt=encrypt,
            progress_callback=progress_callback,
            codec=codec or SOFTWARE_CODEC,
            cancel_event=cancel_event,
            notice_callback=notice_callback,
        )
    except BaseException:
        # A partial HLS folder is useless and holds the secret key: remove it.
        shutil.rmtree(work_dir, ignore_errors=True)
        (work_dir.parent / f"{work_dir.name}.zip").unlink(missing_ok=True)
        raise


def _encode_hls_in(
    input_path: Path,
    work_dir: Path,
    eligible: list[int],
    info: MediaInfo,
    audio_tracks: list[dict[str, Any]],
    *,
    ffmpeg_bin: str,
    hls_time: int,
    encrypt: bool,
    progress_callback: EncodeProgressCallback | None,
    codec: VideoCodec,
    cancel_event: threading.Event | None,
    notice_callback: Callable[[str], None] | None,
) -> Path:
    """Body of ``encode_hls``; the caller removes *work_dir* if this raises."""
    # ------------------------------------------------------------------
    # AES-128 encryption artefacts
    # ------------------------------------------------------------------
    key_bytes = secrets.token_bytes(16)
    key_filename = f"enc_{secrets.token_hex(8)}.key"
    key_file = work_dir / key_filename
    key_file.write_bytes(key_bytes)

    # keyinfo format (one path per line):
    #   <URI used in playlist>
    #   <absolute path to key file>
    keyinfo_path = work_dir / "keyinfo"
    keyinfo_path.write_text(f"../{key_filename}\n{key_file}\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Audio-only HLS streams
    # ------------------------------------------------------------------
    audio_tracks_dir = work_dir / "audio_tracks"
    audio_tracks_dir.mkdir(exist_ok=True)
    valid_audio_tracks: list[dict[str, Any]] = []

    for track in audio_tracks:
        lang_safe = re.sub(r"[^a-z0-9_\-]", "", track["language"], flags=re.IGNORECASE)
        lang_dir = audio_tracks_dir / lang_safe
        lang_dir.mkdir(exist_ok=True)

        audio_m3u8 = lang_dir / "audio.m3u8"
        audio_ts_pattern = str(lang_dir / "audio_%03d.ts")

        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-map",
            f"0:a:{track['index']}",
            "-c:a",
            "aac",
            "-profile:a",
            "aac_low",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-b:a",
            "128k",
            "-f",
            "hls",
            "-hls_time",
            str(hls_time),
            "-hls_flags",
            "independent_segments+split_by_time",
            "-hls_playlist_type",
            "vod",
            "-hls_segment_type",
            "mpegts",
            "-hls_segment_filename",
            audio_ts_pattern,
            str(audio_m3u8),
        ]
        logger.info("HLS audio track %d: %s", track["index"], " ".join(cmd))
        try:
            _run_ffmpeg(cmd, cancel_event=cancel_event, progress=None)
        except _FFmpegFailed as exc:
            logger.warning(
                "Audio track %d (%s) failed (exit code %d) – skipping: %s",
                track["index"],
                track["language"],
                exc.returncode,
                "\n".join(exc.tail[-5:]),
            )
            shutil.rmtree(lang_dir, ignore_errors=True)
            continue
        if not audio_m3u8.exists():
            logger.warning(
                "Audio track %d (%s) produced no playlist – skipping",
                track["index"],
                track["language"],
            )
            shutil.rmtree(lang_dir, ignore_errors=True)
        else:
            valid_audio_tracks.append({**track, "lang_safe": lang_safe})

    # ------------------------------------------------------------------
    # FFmpeg command(s) for the video resolutions (single -i, several output
    # branches – mirrors HLSProcessor.php; split when the codec limits outputs)
    # ------------------------------------------------------------------
    res_dirs = {res: work_dir / f"res{res}" for res in eligible}

    def build_cmd(group: list[int], video_codec: VideoCodec) -> list[str]:
        cmd_video: list[str] = [ffmpeg_bin, "-i", str(input_path)]
        for res in group:
            rate = ENCODING_SETTINGS[res]["maxrate"]
            res_dir = res_dirs[res]
            cmd_video += [
                "-force_key_frames",
                f"expr:gte(t,n_forced*{hls_time})",
                "-vf",
                f"scale=-2:{res}",
                "-b:v",
                f"{rate}k",
                "-r",
                str(_hls_framerate(res)),
                "-movflags",
                "+faststart",
                "-hls_time",
                str(hls_time),
                "-hls_flags",
                "independent_segments+split_by_time",
                "-hls_playlist_type",
                "vod",
                # Only the first video stream: cover art must not become extra HLS video.
                "-map",
                "0:v:0",
                *_video_codec_args(video_codec, hls=True),
                "-f",
                "hls",
            ]
            if encrypt:
                cmd_video += ["-hls_key_info_file", str(keyinfo_path)]
            cmd_video += [
                "-hls_segment_filename",
                str(res_dir / "seg_%03d.ts"),
                str(res_dir / "index.m3u8"),
            ]
        return cmd_video

    def run(video_codec: VideoCodec) -> None:
        for res_dir in res_dirs.values():
            res_dir.mkdir(exist_ok=True)
        groups = _batches(eligible, video_codec.max_outputs)
        progress = _Progress(progress_callback, len(groups))
        for group in groups:
            cmd_video = build_cmd(group, video_codec)
            logger.info("HLS %s with %s: %s", group, video_codec.label, " ".join(cmd_video))
            _run_ffmpeg(cmd_video, cancel_event=cancel_event, progress=progress)
            progress.finish_run()

    def cleanup() -> None:
        for res_dir in res_dirs.values():
            shutil.rmtree(res_dir, ignore_errors=True)

    _encode_with_fallback(run, codec, cleanup, notice_callback)

    # ------------------------------------------------------------------
    # Master playlist
    # ------------------------------------------------------------------
    master_lines = ["#EXTM3U", "#EXT-X-VERSION:3"]

    for track in valid_audio_tracks:
        default = "YES" if track["index"] == 0 else "NO"
        master_lines.append(
            f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio_group",'
            f'NAME="{track["title"]}",LANGUAGE="{track["language"]}",'
            f"DEFAULT={default},AUTOSELECT=YES,"
            f'URI="audio_tracks/{track["lang_safe"]}/audio.m3u8"'
        )

    for res in eligible:
        s = ENCODING_SETTINGS[res]
        w = _hls_master_width(res, info)
        bandwidth = s["maxrate"] * 1000
        audio_part = ',AUDIO="audio_group"' if valid_audio_tracks else ""
        master_lines.append(
            f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={w}x{res}{audio_part}"
        )
        master_lines.append(f"res{res}/index.m3u8")

    (work_dir / "index.m3u8").write_text("\n".join(master_lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Zip the whole directory (mirrors zipDirectory() in functions.php)
    # ------------------------------------------------------------------
    zip_path = work_dir.parent / f"{work_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in work_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(work_dir))

    logger.info("HLS ZIP created: %s (%d bytes)", zip_path, zip_path.stat().st_size)
    return zip_path
