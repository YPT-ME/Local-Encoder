"""FFmpeg-based video encoding and thumbnail generation.

Encoding settings are taken directly from AVideo's Format.php
``ENCODING_SETTINGS`` array so the output matches what the server expects.

Thumbnail commands mirror AVideo's getImage.php / Encoder.php methods:
  ``getImage``      → extract_thumbnail_jpg
  ``getGifImage``   → extract_thumbnail_gif
  ``getWebpImage``  → extract_thumbnail_webp
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

EncodeProgressCallback = Callable[[int, int], None]
"""Called as ``callback(current_seconds, total_seconds)``."""

# Mirrors AVideo Format.php ENCODING_SETTINGS
ENCODING_SETTINGS: dict[int, dict[str, int]] = {
    240:  {"minrate": 300,   "maxrate": 500,   "bufsize": 1000,  "audioBitrate": 48},
    360:  {"minrate": 500,   "maxrate": 800,   "bufsize": 1600,  "audioBitrate": 64},
    480:  {"minrate": 800,   "maxrate": 1000,  "bufsize": 2000,  "audioBitrate": 96},
    540:  {"minrate": 1000,  "maxrate": 1500,  "bufsize": 3000,  "audioBitrate": 96},
    720:  {"minrate": 1500,  "maxrate": 2000,  "bufsize": 4000,  "audioBitrate": 128},
    1080: {"minrate": 3000,  "maxrate": 4000,  "bufsize": 8000,  "audioBitrate": 128},
    1440: {"minrate": 6000,  "maxrate": 8000,  "bufsize": 16000, "audioBitrate": 160},
    2160: {"minrate": 8000,  "maxrate": 12000, "bufsize": 24000, "audioBitrate": 160},
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
    progress_callback: Optional[EncodeProgressCallback] = None,
) -> Path:
    """Re-encode *input_path* to H.264 MP4 at *resolution* pixels tall.

    Uses AVideo's exact bitrate ladder (ENCODING_SETTINGS) and the
    ``-preset veryfast -movflags +faststart`` flags that the PHP encoder uses.
    Mirrors AVideo's MP4Processor.php ``process()`` method.
    """
    if resolution not in ENCODING_SETTINGS:
        raise ValueError(
            f"Unsupported resolution {resolution}p. "
            f"Choose from: {ALLOWED_RESOLUTIONS}"
        )
    s = ENCODING_SETTINGS[resolution]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_bin,
        "-i", str(input_path),
        "-preset", "veryfast",
        "-vf", f"scale=-2:{resolution}",
        "-b:v",      f"{s['maxrate']}k",
        "-minrate",  f"{s['minrate']}k",
        "-maxrate",  f"{s['maxrate']}k",
        "-bufsize",  f"{s['bufsize']}k",
        "-c:v",      "h264",
        "-pix_fmt",  "yuv420p",
        "-c:a",      "aac",
        "-b:a",      f"{s['audioBitrate']}k",
        "-movflags", "+faststart",
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
                duration_secs = (
                    int(m.group(1)) * 3600
                    + int(m.group(2)) * 60
                    + float(m.group(3))
                )
        # Report encode progress
        if progress_callback and "time=" in line:
            m = re.search(r"time=(\d+):(\d+):([\d.]+)", line)
            if m and duration_secs > 0:
                current = (
                    int(m.group(1)) * 3600
                    + int(m.group(2)) * 60
                    + float(m.group(3))
                )
                progress_callback(int(current), int(duration_secs))

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg encode failed with exit code {proc.returncode} "
            f"(command: {' '.join(cmd)})"
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
        "-ss", str(int(seek_seconds)),
        "-i", str(input_path),
        "-vframes", "1",
        "-y",
        str(output_path),
    ]
    logger.info("Extracting JPG thumbnail: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode != 0 and not output_path.exists():
        raise RuntimeError(
            f"Thumbnail extraction failed: {result.stderr.decode(errors='replace')}"
        )
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
            "-ss", str(int(seek_seconds)),
            "-t", str(duration),
            "-i", str(input_path),
            "-vf", "fps=10,scale=320:-1:flags=lanczos,palettegen",
            str(palette_path),
        ]
        result = subprocess.run(cmd_palette, capture_output=True, timeout=60)
        if result.returncode != 0 or not palette_path.exists():
            raise RuntimeError(
                f"GIF palette generation failed: "
                f"{result.stderr.decode(errors='replace')}"
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
            "-ss", str(int(seek_seconds)),
            "-t", str(duration),
            "-i", str(input_path),
            "-i", str(palette_path),
            "-filter_complex", scale_filter,
            "-y",
            str(output_path),
        ]
        result = subprocess.run(cmd_gif, capture_output=True, timeout=120)
        if result.returncode == 0 and output_path.exists():
            return output_path

        # Fallback – simpler scale without letter-boxing
        cmd_fallback = [
            ffmpeg_bin,
            "-ss", str(int(seek_seconds)),
            "-t", str(duration),
            "-i", str(input_path),
            "-i", str(palette_path),
            "-filter_complex",
            "fps=10,scale=320:-1:flags=lanczos[x];[x][1:v]paletteuse",
            "-y",
            str(output_path),
        ]
        result = subprocess.run(cmd_fallback, capture_output=True, timeout=120)
        if result.returncode != 0 and not output_path.exists():
            raise RuntimeError(
                f"GIF generation failed: {result.stderr.decode(errors='replace')}"
            )
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
        "-ss", str(int(seek_seconds)),
        "-t", str(duration),
        "-i", str(input_path),
        "-vcodec", "libwebp",
        "-lossless", "1",
        "-vf", scale_filter,
        "-q", "60",
        "-preset", "default",
        "-loop", "0",
        "-an",
        "-vsync", "0",
        str(output_path),
    ]
    logger.info("Extracting WebP thumbnail: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode != 0 and not output_path.exists():
        raise RuntimeError(
            f"WebP extraction failed: {result.stderr.decode(errors='replace')}"
        )
    return output_path
