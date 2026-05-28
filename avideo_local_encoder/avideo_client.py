"""HTTP client for the AVideo encoder API.

Implements the same protocol as the PHP encoder found at:
  AVideo/.compose/encoder/objects/Encoder.php  (send / sendToStreamer)
  AVideo/.compose/encoder/objects/Login.php     (login)

Endpoint mapping (via AVideo .htaccess RewriteRules):
  {server}/login                                 → objects/login.json.php
  {server}/aVideoEncoder.json                    → objects/aVideoEncoder.json.php
  {server}/aVideoEncoderChunk.json               → objects/aVideoEncoderChunk.json.php
  {server}/objects/aVideoEncoderReceiveImage.json.php   (direct)
  {server}/objects/aVideoEncoderNotifyIsDone.json.php   (direct)
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin

import httpx

from avideo_local_encoder.utils import generate_file_id

logger = logging.getLogger(__name__)

# 500 MB per PUT chunk – matches the PHP encoder's chunk size
CHUNK_SIZE = 500 * 1024 * 1024

UploadProgressCallback = Callable[[str, int, int], None]


@dataclass
class LoginResult:
    is_logged: bool
    can_upload: bool
    encrypted_pass: str
    username: str
    user_id: int
    name: str = ""
    is_admin: bool = False


@dataclass
class RegisterVideoResult:
    videos_id: int
    video_id_hash: str
    error: bool = False
    msg: str = ""


class AVideoAPIError(RuntimeError):
    """Raised when the AVideo API returns an error response."""


class AVideoClient:
    """HTTP client mirroring the PHP encoder's AVideo API calls."""

    def __init__(self, server_url: str, ssl_verify: bool = True) -> None:
        # Guarantee a trailing slash so urljoin relative paths work correctly.
        self._base = server_url if server_url.endswith("/") else server_url + "/"
        self._http = httpx.Client(
            verify=ssl_verify,
            timeout=httpx.Timeout(connect=30.0, read=3600.0, write=3600.0, pool=30.0),
            follow_redirects=True,
            headers={"User-Agent": "avideo-local-encoder/0.1"},
        )
        self._username: str = ""
        self._encrypted_pass: str = ""
        self._streamers_id: int = 0

    # ------------------------------------------------------------------
    # Context manager helpers
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AVideoClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return urljoin(self._base, path)

    def _now_tz(self) -> str:
        """Return the current UTC offset string, e.g. '+0200'."""
        return datetime.datetime.now().astimezone().strftime("%z")

    def _auth_fields(self) -> dict[str, str]:
        """Return the authentication fields that every encoder POST must include."""
        return {
            "user": self._username,
            "pass": self._encrypted_pass,
            "encodedPass": "1",
            "streamers_id": str(self._streamers_id),
            "timezone": self._now_tz(),
        }

    def _return_vars(self) -> str:
        """Minimal return_vars JSON payload (mirrors PHP encoder behaviour)."""
        return json.dumps({"encoder_queue_id": 0})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def login(self, username: str, password: str) -> LoginResult:
        """Authenticate with AVideo.

        Sends the plain-text password; the server hashes it server-side.
        On success, stores the encrypted password returned by the server for
        use in all subsequent API calls (``encodedPass=1``).
        """
        data = {
            "user": username,
            "pass": password,
            "encodedPass": "false",   # tell server to hash the plain password
            "redirectUri": self._base,
        }
        logger.debug("POST %slogin", self._base)
        resp = self._http.post(self._url("login"), data=data)
        resp.raise_for_status()

        body: dict[str, Any] = resp.json()

        if body.get("error"):
            raise AVideoAPIError(f"AVideo login error: {body['error']}")

        if not body.get("isLogged"):
            raise AVideoAPIError("Login rejected – check username and password")

        if not body.get("canUpload"):
            raise AVideoAPIError("This AVideo user does not have upload permission")

        result = LoginResult(
            is_logged=bool(body.get("isLogged")),
            can_upload=bool(body.get("canUpload")),
            encrypted_pass=str(body.get("pass", "")),
            username=str(body.get("user", username)),
            user_id=int(body.get("id", 0)),
            name=str(body.get("name", "")),
            is_admin=bool(body.get("isAdmin")),
        )
        self._username = result.username
        self._encrypted_pass = result.encrypted_pass
        logger.info("Logged in as %s (id=%d)", result.username, result.user_id)
        return result

    def register_video(
        self,
        title: str,
        format_ext: str,
        resolution: int,
        duration: float,
        categories_id: int = 0,
        description: str = "",
        download_url: str = "",
        videos_id: Optional[int] = None,
    ) -> RegisterVideoResult:
        """Create or update a video record on AVideo.

        Called before uploading the encoded file so we receive a ``videos_id``
        and ``video_id_hash`` that authorize all subsequent requests.
        """
        data: dict[str, Any] = {
            **self._auth_fields(),
            "first_request": "1",
            "title": title,
            "format": format_ext,
            "resolution": str(resolution),
            "duration": str(int(duration)),
            "categories_id": str(categories_id),
            "description": description,
            "downloadURL": download_url,
            "videoDownloadedLink": download_url,
            "encoderURL": "",
            "keepEncoding": "0",
            "return_vars": self._return_vars(),
        }
        if videos_id:
            data["videos_id"] = str(videos_id)

        logger.debug("POST %saVideoEncoder.json (register)", self._base)
        resp = self._http.post(self._url("aVideoEncoder.json"), data=data)
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        logger.debug("register_video response: %s", body)

        vid = int(body.get("videos_id") or body.get("video_id") or 0)
        if not vid:
            raise AVideoAPIError(
                f"Video registration failed – no videos_id returned: {body.get('msg', body)}"
            )

        return RegisterVideoResult(
            videos_id=vid,
            video_id_hash=str(body.get("video_id_hash", "")),
            error=bool(body.get("error")),
            msg=str(body.get("msg", "")),
        )

    def upload_file(
        self,
        file_path: Path,
        videos_id: int,
        video_id_hash: str,
        title: str,
        format_ext: str,
        resolution: int,
        duration: float,
        categories_id: int = 0,
        description: str = "",
        download_url: str = "",
        chunk_size: int = CHUNK_SIZE,
        progress_callback: Optional[UploadProgressCallback] = None,
    ) -> dict[str, Any]:
        """Upload an encoded video file to AVideo via chunked PUT + final POST.

        Flow (mirrors Encoder.php ``sendFileChunk`` / ``sendFile``):
          1. Split file into ``chunk_size`` chunks.
          2. PUT each chunk to ``aVideoEncoderChunk.json?file_id=…&chunk=…&total=…``.
          3. POST the assembled server-side temp-file path via ``aVideoEncoder.json``
             using the ``chunkFile`` field.
        """
        file_size = file_path.stat().st_size
        total_chunks = max(1, -(-file_size // chunk_size))  # ceiling division
        file_id = generate_file_id()
        assembled_file = ""

        with open(file_path, "rb") as fh:
            for chunk_index in range(total_chunks):
                chunk_data = fh.read(chunk_size)
                if not chunk_data:
                    break

                url = self._url(
                    f"aVideoEncoderChunk.json"
                    f"?file_id={file_id}&chunk={chunk_index}&total={total_chunks}"
                )
                logger.debug(
                    "PUT chunk %d/%d (%d bytes)",
                    chunk_index + 1,
                    total_chunks,
                    len(chunk_data),
                )
                resp = self._http.put(url, content=chunk_data)
                resp.raise_for_status()
                chunk_resp = resp.json()
                assembled_file = str(chunk_resp.get("file", ""))

                if progress_callback:
                    uploaded = min((chunk_index + 1) * chunk_size, file_size)
                    progress_callback("uploading", uploaded, file_size)

        if not assembled_file:
            raise AVideoAPIError("Server did not return assembled chunk file path")

        # Register the assembled file with AVideo
        data: dict[str, Any] = {
            **self._auth_fields(),
            "videos_id": str(videos_id),
            "video_id_hash": video_id_hash,
            "title": title,
            "format": format_ext,
            "resolution": str(resolution),
            "duration": str(int(duration)),
            "categories_id": str(categories_id),
            "description": description,
            "downloadURL": download_url,
            "videoDownloadedLink": download_url,
            "chunkFile": assembled_file,
            "encoderURL": "",
            "keepEncoding": "0",
            "return_vars": self._return_vars(),
        }

        logger.debug("POST %saVideoEncoder.json (finalize)", self._base)
        resp = self._http.post(self._url("aVideoEncoder.json"), data=data)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        logger.debug("upload_file finalize response: %s", result)
        return result

    def upload_images(
        self,
        videos_id: int,
        video_id_hash: str,
        duration: float,
        jpg_path: Optional[Path] = None,
        gif_path: Optional[Path] = None,
        webp_path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Upload JPG / GIF / WebP thumbnails to AVideo.

        Mirrors Encoder.php ``sendImages`` / getImage upload to
        ``objects/aVideoEncoderReceiveImage.json.php``.
        """
        fields: dict[str, Any] = {
            **self._auth_fields(),
            "videos_id": str(videos_id),
            "video_id_hash": video_id_hash,
            "duration": str(int(duration)),
            "return_vars": self._return_vars(),
        }

        files: dict[str, Any] = {}
        handles: list[Any] = []
        try:
            for field_name, path, mime in [
                ("image", jpg_path, "image/jpeg"),
                ("gifimage", gif_path, "image/gif"),
                ("webpimage", webp_path, "image/webp"),
            ]:
                if path and path.exists():
                    fh = open(path, "rb")
                    handles.append(fh)
                    files[field_name] = (path.name, fh, mime)

            if not files:
                logger.warning("No thumbnail files found; skipping image upload")
                return {"error": True, "msg": "No thumbnails provided"}

            logger.debug("POST images for videos_id=%d", videos_id)
            resp = self._http.post(
                self._url("objects/aVideoEncoderReceiveImage.json.php"),
                data=fields,
                files=files,
            )
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            logger.debug("upload_images response: %s", result)
            return result
        finally:
            for fh in handles:
                fh.close()

    def notify_done(
        self,
        videos_id: int,
        video_id_hash: str,
        failed: bool = False,
    ) -> dict[str, Any]:
        """Notify AVideo that encoding has finished.

        Mirrors Encoder.php ``notifyIsDone`` call to
        ``objects/aVideoEncoderNotifyIsDone.json.php``.
        """
        data: dict[str, Any] = {
            **self._auth_fields(),
            "videos_id": str(videos_id),
            "video_id_hash": video_id_hash,
            "fail": "1" if failed else "0",
            "return_vars": self._return_vars(),
        }
        logger.debug("POST notify_done videos_id=%d fail=%s", videos_id, failed)
        resp = self._http.post(
            self._url("objects/aVideoEncoderNotifyIsDone.json.php"),
            data=data,
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        logger.debug("notify_done response: %s", result)
        return result
