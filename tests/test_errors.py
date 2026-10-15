"""Tests for the plain-language error classification."""

from __future__ import annotations

import errno
from pathlib import Path

import httpx
import pytest
import yt_dlp.utils  # type: ignore[import-untyped]

from local_encoder.avideo_client import AVideoAPIError
from local_encoder.encoder import EncodeCancelled
from local_encoder.errors import MESSAGES, JobCancelled, LocalEncoderError, classify


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (JobCancelled(), "cancelled"),
        (EncodeCancelled(), "cancelled"),
        (yt_dlp.utils.DownloadCancelled("x"), "cancelled"),
        (AVideoAPIError("x", code="wrong_password"), "wrong_password"),
        (AVideoAPIError("weird"), "site_error"),
        (yt_dlp.utils.DownloadError("ERROR: [youtube] x: Private video"), "download_private"),
        (
            yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot"),
            "download_login_required",
        ),
        (yt_dlp.utils.DownloadError("ERROR: Unsupported URL: x"), "download_unsupported"),
        (yt_dlp.utils.DownloadError("ERROR: something odd"), "download_failed"),
        (httpx.ConnectTimeout("t"), "site_timeout"),
        (httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]"), "tls_error"),
        (httpx.ConnectError("getaddrinfo failed"), "site_unreachable"),
        (FileNotFoundError(2, "No such file", "C:/bin/ffmpeg.exe"), "ffmpeg_missing"),
        (OSError(errno.ENOSPC, "No space left on device"), "no_disk_space"),
        (RuntimeError("FFmpeg could not convert the video (exit code 1)"), "encode_failed"),
        (ValueError("boom"), "unknown"),
    ],
)
def test_classify(exc: BaseException, code: str) -> None:
    problem = classify(exc)
    assert problem.code == code
    assert problem.message
    assert "{" not in problem.message  # every placeholder was filled


def test_download_failed_keeps_a_clean_detail() -> None:
    problem = classify(yt_dlp.utils.DownloadError("\x1b[0;31mERROR:\x1b[0m HTTP Error 500"))
    assert problem.params["detail"] == "HTTP Error 500"


def test_local_error_message_uses_params() -> None:
    exc = LocalEncoderError("no_disk_space", {"needed_gb": "3.0", "free_gb": "1.2"})
    assert "3.0 GB" in str(exc)
    assert classify(exc).to_dict()["params"] == {"needed_gb": "3.0", "free_gb": "1.2"}


def test_every_code_has_a_ui_translation() -> None:
    """The web UI translates the same codes (static/i18n.js, keys err.<code>)."""
    i18n = (Path(__file__).parent.parent / "local_encoder" / "static" / "i18n.js").read_text(
        encoding="utf-8"
    )
    for code in MESSAGES:
        assert i18n.count(f"'err.{code}'") == 3, code  # en, pt, es
