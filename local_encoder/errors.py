"""Turn any failure into a plain-language error with a stable code.

The web UI translates the ``code`` (with ``params``) into the user's language and offers the
next step; the CLI prints the English ``message``. The original exception text stays in the log.
"""

from __future__ import annotations

import errno
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import yt_dlp.utils  # type: ignore[import-untyped]

from local_encoder.avideo_client import AVideoAPIError

# English text for every code (the UI has its own translations of the same codes).
MESSAGES: dict[str, str] = {
    "cancelled": "Cancelled.",
    "invalid_url": "This is not a web link. Paste a link that starts with http:// or https://.",
    "playlist_link": "This link is a playlist or a channel. Paste the link of a single video.",
    "live_link": "This link is a live broadcast. Only recorded videos can be imported.",
    "download_private": "This video is private, so it cannot be downloaded.",
    "download_login_required": (
        "The video site asked to sign in before downloading. Try again later, or download the "
        "video yourself and choose the file instead."
    ),
    "download_geo": "This video is not available in your country.",
    "download_unavailable": "This video is not available any more. Check the link.",
    "download_unsupported": "This link is not supported. Check the link or choose a file.",
    "download_failed": "The video could not be downloaded: {detail}",
    "audio_only": (
        "This file has no picture (audio only). Audio files are not supported yet; "
        "choose a video file."
    ),
    "unreadable_file": "This file could not be read as a video. It may be damaged.",
    "source_missing": "The original file is gone. Add the video again.",
    "folder_not_found": "This folder was not found: {path}",
    "folder_denied": "Local Encoder is not allowed to open this folder: {path}",
    "file_not_video": "This is not a video file: {path}",
    "no_disk_space": (
        "There is not enough free disk space. About {needed_gb} GB is needed and "
        "{free_gb} GB is free. Free some space and try again."
    ),
    "ffmpeg_missing": (
        "FFmpeg, which converts the videos, was not found. Download Local Encoder again."
    ),
    "encode_failed": (
        "The video could not be converted. The file may be damaged or use an unsupported format."
    ),
    "site_unreachable": (
        "Could not reach the site. Check the address and your internet connection."
    ),
    "site_timeout": "The site took too long to answer. Try again in a few minutes.",
    "tls_error": (
        "The site's security certificate could not be verified. If this is your own test "
        "server, untick “Verify the security certificate” and connect again."
    ),
    "wrong_password": "The user name or password was not accepted by the site.",
    "login_error": "The site did not accept the login: {detail}",
    "cannot_upload": (
        "This account is not allowed to upload videos on this site. Ask the site "
        "administrator to enable uploads for it."
    ),
    "session_expired": "Your connection to the site expired. Type your password and connect again.",
    "rate_limited": "The site is limiting requests right now. Wait a few minutes and try again.",
    "bot_blocked": (
        "The site blocked Local Encoder as a robot. Ask the site administrator to allow "
        "AVideo encoders."
    ),
    "not_avideo": (
        "The address did not answer as an AVideo site. Check the site address and try again."
    ),
    "refused": "The site refused the request (HTTP {status}). Check that your user can upload.",
    "site_http_error": "The site answered with an error (HTTP {status}). Try again later.",
    "site_error": "The site reported a problem: {detail}",
    "register_failed": "The site did not create the video: {detail}",
    "save_failed": "The site could not save the file: {detail}",
    "completion_failed": (
        "The site received the files but did not confirm completion. Your converted files "
        "are kept. Try again; if it keeps failing, ask the site administrator to check the video."
    ),
    "completion_in_progress": (
        "The site is still finishing this video. Your converted files are kept. "
        "Wait a little, then try again."
    ),
    "file_receive_failed": (
        "Local Encoder could not receive the file. It is still selected. Try adding it again."
    ),
    "file_too_large": (
        "The file is larger than this site accepts. Ask the site administrator to raise the "
        "upload limit."
    ),
    "unknown": "Something went wrong: {detail}",
}

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class LocalEncoderError(Exception):
    """An expected failure detected by Local Encoder itself (not by AVideo or FFmpeg)."""

    def __init__(self, code: str, params: dict[str, Any] | None = None) -> None:
        self.code = code
        self.params = params or {}
        super().__init__(format_message(code, self.params))


class JobCancelled(LocalEncoderError):
    """The user cancelled the job."""

    def __init__(self) -> None:
        super().__init__("cancelled")


@dataclass
class UserError:
    code: str
    message: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "params": self.params}


def format_message(code: str, params: dict[str, Any]) -> str:
    template = MESSAGES.get(code, MESSAGES["unknown"])
    try:
        return template.format(**{"detail": "", **params})
    except (KeyError, IndexError, ValueError):
        return template


def _short(text: str, limit: int = 300) -> str:
    text = _ANSI.sub("", text).strip()
    text = re.sub(r"^ERROR:\s*", "", text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _download_code(text: str) -> str:
    lower = text.lower()
    if "private video" in lower:
        return "download_private"
    if "sign in" in lower or "login required" in lower or "cookies" in lower:
        return "download_login_required"
    if "not available in your country" in lower or "geo restrict" in lower:
        return "download_geo"
    if "unsupported url" in lower:
        return "download_unsupported"
    if "video unavailable" in lower or "has been removed" in lower or "http error 404" in lower:
        return "download_unavailable"
    return "download_failed"


def _make(code: str, params: dict[str, Any] | None = None) -> UserError:
    params = params or {}
    return UserError(code=code, message=format_message(code, params), params=params)


def classify(exc: BaseException) -> UserError:
    """Return the plain-language error for *exc*."""
    if isinstance(exc, LocalEncoderError):
        return _make(exc.code, exc.params)
    if isinstance(exc, AVideoAPIError):
        code = exc.code if exc.code in MESSAGES else "site_error"
        params = dict(exc.params)
        if code == "site_error":
            params.setdefault("detail", _short(str(exc)))
        return _make(code, params)
    if type(exc).__name__ == "EncodeCancelled" or isinstance(exc, yt_dlp.utils.DownloadCancelled):
        return _make("cancelled")
    if isinstance(exc, yt_dlp.utils.DownloadError):
        text = _short(str(exc))
        code = _download_code(text)
        return _make(code, {"detail": text} if code == "download_failed" else {})
    if isinstance(exc, httpx.TimeoutException):
        return _make("site_timeout")
    if isinstance(exc, httpx.HTTPError):
        text = str(exc)
        if "CERTIFICATE_VERIFY_FAILED" in text or "SSL" in text or "certificate" in text:
            return _make("tls_error")
        return _make("site_unreachable")
    if isinstance(exc, FileNotFoundError):
        name = str(exc.filename or "")
        if "ffmpeg" in name.lower() or "ffprobe" in name.lower():
            return _make("ffmpeg_missing")
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return _make("no_disk_space", {"needed_gb": "?", "free_gb": "0"})
    if isinstance(exc, RuntimeError) and str(exc).startswith("FFmpeg"):
        return _make("encode_failed")
    return _make("unknown", {"detail": _short(str(exc)) or type(exc).__name__})
