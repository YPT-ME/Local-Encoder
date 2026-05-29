"""Video downloader using the yt-dlp Python library.

Strategy list mirrors the PHP encoder's ``getYoutubeDlStrategies()`` in
AVideo/.compose/encoder/objects/Encoder.php.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yt_dlp
import yt_dlp.utils

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, int], None]
"""Called as ``callback(status, downloaded_bytes, total_bytes)``."""


def download_video(
    url: str,
    output_dir: Path,
    filename_stem: str,
    progress_callback: ProgressCallback | None = None,
    cookies_file: Path | None = None,
) -> Path:
    """Download *url* with yt-dlp and return the path to the local .mp4 file.

    Tries multiple format strategies in order (best-quality first) until one
    succeeds.  Raises ``yt_dlp.utils.DownloadError`` if all strategies fail.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / f"{filename_stem}.%(ext)s")
    expected_mp4 = output_dir / f"{filename_stem}.mp4"

    def _progress_hook(d: dict) -> None:
        if progress_callback is None:
            return
        status = d.get("status", "")
        if status == "downloading":
            downloaded = int(d.get("downloaded_bytes") or 0)
            total = int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
            progress_callback("downloading", downloaded, total)
        elif status == "finished":
            total = int(d.get("total_bytes") or d.get("downloaded_bytes") or 0)
            progress_callback("finished", total, total)

    base_opts: dict[str, Any] = {
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "no_playlist": True,
        "nocheckcertificate": True,
        "noprogress": True,          # we manage progress via hooks
        "progress_hooks": [_progress_hook],
        "quiet": True,
        "no_color": True,
        "extractor_retries": 3,
        "fragment_retries": 3,
        "retries": 3,
        "ignoreerrors": False,
        "sleep_interval_requests": 1,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }
    if cookies_file and cookies_file.exists():
        base_opts["cookiefile"] = str(cookies_file)

    strategies: list[dict[str, Any]] = [
        # 1. Best MP4 video + M4A audio (highest quality, most compatible)
        {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
        },
        # 2. Any best format merged into mp4
        {
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
        },
        # 3. Web player client (helps with YouTube bot-detection)
        {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
            "extractor_args": {"youtube": {"player_client": ["web"]}},
        },
        # 4. Mobile-web client
        {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
            "extractor_args": {"youtube": {"player_client": ["mweb"]}},
        },
        # 5. Simplest possible – just best available
        {
            "format": "best[ext=mp4]/best",
        },
    ]

    last_error: Exception | None = None
    for i, strategy in enumerate(strategies, 1):
        opts: dict[str, Any] = {**base_opts, **strategy}
        logger.info("yt-dlp strategy %d/%d: format=%s", i, len(strategies), opts.get("format"))
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise yt_dlp.utils.DownloadError("extract_info returned None")

            # Prefer the expected .mp4 file; fall back to any file with the stem.
            if expected_mp4.exists():
                logger.info("Downloaded → %s", expected_mp4)
                return expected_mp4
            candidates = sorted(output_dir.glob(f"{filename_stem}.*"))
            if candidates:
                logger.info("Downloaded → %s", candidates[0])
                return candidates[0]

        except yt_dlp.utils.DownloadError as exc:
            logger.warning("Strategy %d failed: %s", i, exc)
            last_error = exc

    raise last_error or RuntimeError("All yt-dlp download strategies failed")


def get_video_info(url: str) -> dict[str, Any]:
    """Fetch metadata (title, duration, etc.) without downloading the file."""
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_color": True,
        "nocheckcertificate": True,
        "skip_download": True,
        "no_playlist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(url, download=False)
    return dict(info) if info else {}
