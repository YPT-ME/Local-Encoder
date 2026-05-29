"""FFmpeg-based video encoding and thumbnail generation.

Encoding settings are taken directly from AVideo's Format.php
``ENCODING_SETTINGS`` array so the output matches what the server expects.

Thumbnail commands mirror AVideo's getImage.php / Encoder.php methods:
  ``getImage``      → extract_thumbnail_jpg
  ``getGifImage``   → extract_thumbnail_gif
  ``getWebpImage``  → extract_thumbnail_webp

HLS support mirrors AVideo's HLSProcessor.php:
  ``encode_hls``    → multi-resolution HLS + AES-128 encryption → zipped
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import subprocess
import zipfile
from collections.abc import Callable
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
) -> list[Path]:
    """Re-encode *input_path* to multiple H.264 MP4 files in a single FFmpeg pass.

    Mirrors AVideo's ``getDynamicCommandFromFormat()`` in Format.php:
    all resolutions ≤ source height are produced in one ``ffmpeg -i … out1 out2 …``
    invocation. Returns list of output paths in ascending resolution order.
    """
    source_height = _probe_video_height(input_path, ffprobe_bin)
    if resolutions is None:
        resolutions = ALLOWED_RESOLUTIONS
    eligible = [r for r in sorted(resolutions) if source_height == 0 or r <= source_height]
    if not eligible:
        eligible = [min(resolutions)]

    output_dir.mkdir(parents=True, exist_ok=True)
    output_files: list[Path] = []
    cmd: list[str] = [ffmpeg_bin, "-i", str(input_path)]

    for res in eligible:
        s = ENCODING_SETTINGS[res]
        out = output_dir / f"{input_path.stem}_{res}p.mp4"
        output_files.append(out)
        cmd += [
            "-preset",
            "veryfast",
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
            str(out),
        ]

    logger.info("Multi-resolution MP4 (%s): %s", eligible, " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    duration_secs: float = 0.0
    for line in proc.stderr or []:
        if duration_secs == 0.0 and "Duration:" in line:
            m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", line)
            if m:
                duration_secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        if progress_callback and "time=" in line:
            m = re.search(r"time=(\d+):(\d+):([\d.]+)", line)
            if m and duration_secs > 0:
                current = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                progress_callback(int(current), int(duration_secs))
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg multi-resolution encode failed with exit code {proc.returncode}"
        )
    return [f for f in output_files if f.exists()]


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
        "-vsync",
        "0",
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
        str(input_path),
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


def _probe_video_height(input_path: Path, ffprobe_bin: str = "ffprobe") -> int:
    """Return the video height in pixels (0 on failure)."""
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=height",
        "-of",
        "csv=p=0",
        str(input_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return int(result.stdout.strip())
    except Exception:
        return 0


def encode_hls(
    input_path: Path,
    output_dir: Path,
    resolutions: list[int] | None = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    hls_time: int = 6,
    encrypt: bool = True,
    progress_callback: EncodeProgressCallback | None = None,
) -> Path:
    """Encode *input_path* to multi-resolution AES-128 HLS and return the ZIP path.

    Mirrors AVideo's HLSProcessor::createHLSWithAudioTracks() + zipDirectory().

    Structure inside the ZIP (also on disk before zipping):
      index.m3u8           – master playlist
      enc_XXXX.key         – AES-128 key (16 raw bytes)
      keyinfo              – FFmpeg key-info file
      audio_tracks/<lang>/audio.m3u8 + *.ts
      res<N>/index.m3u8 + *.ts

    Returns the path to the produced ``.zip`` file.
    """
    source_height = _probe_video_height(input_path, ffprobe_bin)
    audio_tracks = _probe_audio_tracks(input_path, ffprobe_bin)

    # Decide which resolutions to encode
    if resolutions is None:
        resolutions = ALLOWED_RESOLUTIONS
    # Keep only resolutions that are at most as tall as the source; always
    # include at least one (the smallest ≤ source, or the smallest overall).
    eligible = [r for r in sorted(resolutions) if source_height == 0 or r <= source_height]
    if not eligible:
        eligible = [min(resolutions)]

    work_dir = output_dir / input_path.stem
    work_dir.mkdir(parents=True, exist_ok=True)

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
        result = subprocess.run(cmd, capture_output=True, timeout=3600)
        if result.returncode != 0 or not audio_m3u8.exists():
            logger.warning(
                "Audio track %d (%s) failed – skipping: %s",
                track["index"],
                track["language"],
                result.stderr.decode(errors="replace")[-400:],
            )
            shutil.rmtree(lang_dir, ignore_errors=True)
        else:
            valid_audio_tracks.append({**track, "lang_safe": lang_safe})

    # ------------------------------------------------------------------
    # Build the combined FFmpeg command for all video resolutions
    # (single -i, multiple output branches – mirrors HLSProcessor.php)
    # ------------------------------------------------------------------
    cmd_video: list[str] = [ffmpeg_bin, "-i", str(input_path)]
    res_dirs: list[tuple[int, Path]] = []

    for res in eligible:
        s = ENCODING_SETTINGS[res]
        rate = s["maxrate"]
        res_dir = work_dir / f"res{res}"
        res_dir.mkdir(exist_ok=True)
        output_m3u8 = res_dir / "index.m3u8"
        res_dirs.append((res, res_dir))

        ts_pattern = str(res_dir / "seg_%03d.ts")
        cmd_video += [
            "-force_key_frames",
            f"expr:gte(t,n_forced*{hls_time})",
            "-vf",
            f"scale=-2:{res}",
            "-b:v",
            f"{rate}k",
            "-r",
            "30",
            "-movflags",
            "+faststart",
            "-hls_time",
            str(hls_time),
            "-hls_flags",
            "independent_segments+split_by_time",
            "-hls_playlist_type",
            "vod",
            "-map",
            "0:v",
            "-c:v",
            "h264",
            "-profile:v",
            "main",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "hls",
        ]
        if encrypt:
            cmd_video += ["-hls_key_info_file", str(keyinfo_path)]
        cmd_video += [
            "-hls_segment_filename",
            ts_pattern,
            str(output_m3u8),
        ]

    logger.info("HLS video encode: %s", " ".join(cmd_video))
    proc = subprocess.Popen(
        cmd_video,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    duration_secs: float = 0.0
    for line in proc.stderr or []:
        if duration_secs == 0.0 and "Duration:" in line:
            m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", line)
            if m:
                duration_secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        if progress_callback and "time=" in line:
            m = re.search(r"time=(\d+):(\d+):([\d.]+)", line)
            if m and duration_secs > 0:
                current = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                # Scale progress over all resolutions
                per_res = duration_secs * len(eligible)
                # Approximate: count completed resolutions by inspecting m3u8s
                done_res = sum(1 for _, d in res_dirs if (d / "index.m3u8").exists())
                overall = done_res * duration_secs + current
                progress_callback(int(overall), int(per_res))
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg HLS encode failed with exit code {proc.returncode}")

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

    for res, _ in res_dirs:
        s = ENCODING_SETTINGS[res]
        # Approximate 16:9 width (even number)
        w = (int(res * 16 / 9) // 2) * 2 if source_height == 0 else ((int(res * 16 / 9) // 2) * 2)
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
