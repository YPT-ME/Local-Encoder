"""Configuration loading for avideo-local-encoder.

Values are read from (in order of precedence):
  1. Explicit keyword arguments passed to ``load_config``.
  2. Environment variables.
  3. A ``.env`` file in the current working directory (or a path you supply).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Config:
    server_url: str = ""
    username: str = ""
    password: str = ""
    categories_id: int = 0
    output_dir: Path = field(default_factory=lambda: Path("output"))
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    yt_dlp_bin: str = "yt-dlp"
    streamers_id: int = 0
    keep_files: bool = False
    ssl_verify: bool = True

    def normalize_server_url(self) -> None:
        """Ensure server_url ends with /."""
        if self.server_url and not self.server_url.endswith("/"):
            self.server_url += "/"

    def validate(self) -> None:
        """Raise ValueError if required fields are missing."""
        if not self.server_url:
            raise ValueError("AVIDEO_SERVER_URL is required (set via env var or --server flag)")
        if not self.username:
            raise ValueError("AVIDEO_USERNAME is required (set via env var or --user flag)")
        if not self.password:
            raise ValueError("AVIDEO_PASSWORD is required (set via env var or --password flag)")


def load_config(env_file: Optional[Path] = None) -> Config:
    """Load configuration from a .env file and environment variables."""
    if env_file and env_file.exists():
        load_dotenv(env_file)
    else:
        load_dotenv()  # searches cwd and parent directories

    cfg = Config(
        server_url=os.getenv("AVIDEO_SERVER_URL", ""),
        username=os.getenv("AVIDEO_USERNAME", ""),
        password=os.getenv("AVIDEO_PASSWORD", ""),
        categories_id=int(os.getenv("AVIDEO_CATEGORIES_ID", "0")),
        output_dir=Path(os.getenv("AVIDEO_OUTPUT_DIR", "output")),
        ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
        ffprobe_bin=os.getenv("FFPROBE_BIN", "ffprobe"),
        yt_dlp_bin=os.getenv("YTDLP_BIN", "yt-dlp"),
        streamers_id=int(os.getenv("AVIDEO_STREAMERS_ID", "0")),
        keep_files=os.getenv("AVIDEO_KEEP_FILES", "false").lower() == "true",
        ssl_verify=os.getenv("AVIDEO_SSL_VERIFY", "true").lower() == "true",
    )
    cfg.normalize_server_url()
    return cfg
