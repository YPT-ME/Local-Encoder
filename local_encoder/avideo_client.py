"""HTTP client for the AVideo encoder API.

Implements the same protocol as the PHP encoder found at:
  AVideo/.compose/encoder/objects/Encoder.php  (send / sendFileChunk / sendToStreamer)
  AVideo/.compose/encoder/objects/Login.php     (login)

Endpoint mapping (via AVideo .htaccess RewriteRules, with a direct-file fallback for
installations without rewrites):
  {server}/login                  → objects/login.json.php
  {server}/aVideoEncoder.json     → objects/aVideoEncoder.json.php
  {server}/aVideoEncoderChunk.json → objects/aVideoEncoderChunk.json.php
  {server}/objects/aVideoEncoderReceiveImage.json.php   (direct)
  {server}/objects/aVideoEncoderNotifyIsDone.json.php   (direct)

See docs/avideo-encoder-protocol.md for the full field reference.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from local_encoder import __version__
from local_encoder.utils import format_duration, generate_file_id

logger = logging.getLogger(__name__)

# 500 MB per PUT chunk – matches the PHP encoder's chunk size
CHUNK_SIZE = 500 * 1024 * 1024

# Bytes read from disk per write while streaming a chunk (also the progress granularity)
_STREAM_PIECE = 1024 * 1024

# Retries per chunk before falling back to a multipart upload (PHP: MAX_CHUNK_SEND_RETRIES)
MAX_CHUNK_RETRIES = 6

# AVideo recognises encoder traffic by "AVideoEncoder" in the User-Agent
# (isAVideoUserAgent()). Without it the chunk endpoint refuses the request and sites that
# require login redirect the public config endpoints to the login page.
USER_AGENT = f"AVideoEncoder local-encoder/{__version__}"

UploadProgressCallback = Callable[[str, int, int], None]

# Indirection so tests can skip the retry back-off.
_sleep = time.sleep


@dataclass
class LoginResult:
    is_logged: bool
    can_upload: bool
    encrypted_pass: str
    username: str
    user_id: int
    name: str = ""
    is_admin: bool = False
    categories: list[dict[str, Any]] = field(default_factory=list)
    # The site sends ``videoHLS: true`` only when its VideoHLS plugin is enabled; without it the
    # site cannot play an HLS upload (the PHP Encoder hides HLS then).
    video_hls: bool = False
    # Resolutions this user may receive (UserGroups); empty = no restriction.
    allowed_resolutions: list[int] = field(default_factory=list)


@dataclass
class RegisterVideoResult:
    videos_id: int
    video_id_hash: str
    error: bool = False
    msg: str = ""


@dataclass
class ServerConfig:
    """Relevant fields from AVideo's advancedCustom.json.php.

    Mirrors the keys that influence encoding decisions in Format.php.
    """

    auto_convert_to_mp3: bool = False
    single_resolution: int = 0  # 0 = disabled (encode all eligible resolutions)
    save_original_resolution: bool = False
    disable_hls: bool = False
    disable_mp4: bool = False


@dataclass
class SiteStatus:
    """Limits from AVideo's ``status`` endpoint (0 = unknown or unlimited)."""

    version: str = ""
    max_file_size: int = 0  # bytes, the PHP upload limit (matters for the multipart fallback)
    storage_limit_minutes: int = 0
    storage_used_seconds: int = 0


class AVideoAPIError(RuntimeError):
    """Raised when the AVideo API returns an error response.

    ``code`` is a stable identifier the web UI translates into a message with a next step
    (see ``local_encoder.errors``); the text stays a readable English fallback.
    """

    def __init__(
        self, message: str, code: str = "site_error", params: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.params = params or {}


def _parse_resolutions(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(set(result))


def _parse_categories(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for c in items:
        if not isinstance(c, dict) or not c.get("id") or not c.get("name"):
            continue
        try:
            cid = int(c["id"])
        except (TypeError, ValueError):
            continue
        result.append({"id": cid, "name": str(c.get("hierarchyAndName") or c["name"])})
    return result


class AVideoClient:
    """HTTP client mirroring the PHP encoder's AVideo API calls."""

    def __init__(self, server_url: str, ssl_verify: bool = True) -> None:
        # Guarantee a trailing slash so urljoin relative paths work correctly.
        self._base = server_url if server_url.endswith("/") else server_url + "/"
        self._http = httpx.Client(
            verify=ssl_verify,
            timeout=httpx.Timeout(connect=30.0, read=3600.0, write=3600.0, pool=30.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
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

    def _post(self, paths: tuple[str, ...], **kwargs: Any) -> httpx.Response:
        """POST to the first path that exists (rewritten URL first, then the direct file)."""
        resp: httpx.Response | None = None
        for path in paths:
            # A retried multipart upload must re-read its files from the start.
            for value in (kwargs.get("files") or {}).values():
                if isinstance(value, tuple) and hasattr(value[1], "seek"):
                    value[1].seek(0)
            resp = self._http.post(self._url(path), **kwargs)
            if resp.status_code != 404:
                return resp
            logger.debug("%s returned 404; trying the next endpoint path", path)
        assert resp is not None
        return resp

    def _json(self, resp: httpx.Response, action: str) -> Any:
        """Decode an AVideo JSON response, turning every failure into a clear message."""
        status = resp.status_code
        if status == 429:
            raise AVideoAPIError(
                f"The site is temporarily limiting requests ({action}). "
                "Wait a few minutes and try again.",
                code="rate_limited",
            )
        try:
            return resp.json()
        except ValueError:
            pass
        text = resp.text if isinstance(resp.text, str) else ""
        # PHP notices printed before the JSON: keep the trailing object, like Encoder.php does.
        match = re.search(r"(\{[^{]*\})\s*$", text)
        if match:
            try:
                return json.loads(match.group(1))
            except ValueError:
                pass
        logger.warning("%s: non-JSON response (HTTP %s): %.200s", action, status, text)
        if "Bot Found" in text:
            raise AVideoAPIError(
                f"The site blocked the request as a robot ({action}). "
                "Ask the site administrator to allow AVideo encoders.",
                code="bot_blocked",
            )
        if status >= 400:
            raise AVideoAPIError(
                f"The site answered with an error (HTTP {status}) while {action}.",
                code="site_http_error",
                params={"status": status},
            )
        raise AVideoAPIError(
            f"The site did not answer as an AVideo site while {action}. "
            "Check the site address and try again.",
            code="not_avideo",
        )

    def _check_status(self, resp: httpx.Response, action: str) -> None:
        if resp.status_code == 429 or resp.status_code < 400:
            return
        if resp.status_code in (401, 403):
            raise AVideoAPIError(
                f"The site refused the request while {action} (HTTP {resp.status_code}). "
                "Check that your user can upload videos.",
                code="refused",
                params={"status": resp.status_code},
            )
        raise AVideoAPIError(
            f"The site answered with an error (HTTP {resp.status_code}) while {action}.",
            code="site_http_error",
            params={"status": resp.status_code},
        )

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
            "encodedPass": "false",  # tell server to hash the plain password
            "redirectUri": self._base,
        }
        logger.debug("POST %slogin", self._base)
        resp = self._post(("login", "objects/login.json.php"), data=data)
        self._check_status(resp, "logging in")
        body = self._json(resp, "logging in")
        if not isinstance(body, dict):
            raise AVideoAPIError(
                "The site did not answer as an AVideo site while logging in.", code="not_avideo"
            )

        if body.get("error"):
            # Captcha, unverified e-mail, two-factor, too many attempts: the site's own words.
            detail = str(body["error"])[:300]
            raise AVideoAPIError(
                f"AVideo login error: {detail}", code="login_error", params={"detail": detail}
            )

        if not body.get("isLogged"):
            raise AVideoAPIError(
                "Login rejected – check username and password", code="wrong_password"
            )

        if not body.get("canUpload"):
            raise AVideoAPIError(
                "This AVideo user does not have upload permission", code="cannot_upload"
            )

        result = LoginResult(
            is_logged=bool(body.get("isLogged")),
            can_upload=bool(body.get("canUpload")),
            encrypted_pass=str(body.get("pass", "")),
            username=str(body.get("user", username)),
            user_id=int(body.get("id", 0)),
            name=str(body.get("name", "")),
            is_admin=bool(body.get("isAdmin")),
            categories=_parse_categories(body.get("categories")),
            video_hls=body.get("videoHLS") is True,
            allowed_resolutions=_parse_resolutions(body.get("allowedResolutions")),
        )
        self.use_login(result)
        logger.info("Logged in as %s (id=%d)", result.username, result.user_id)
        return result

    def use_login(self, login: LoginResult) -> None:
        """Reuse the token of an earlier login instead of logging in again."""
        self._username = login.username
        self._encrypted_pass = login.encrypted_pass

    def get_server_config(self) -> ServerConfig:
        """Fetch AVideo's advanced config from advancedCustom.json.php.

        Mirrors the ``getAdvancedCustomizedObjectData()`` call in Format.php
        that controls autoConvertVideosToMP3, singleResolution, etc.
        Returns a ``ServerConfig`` with safe defaults on failure.
        """
        url = self._url("plugin/CustomizeAdvanced/advancedCustom.json.php")
        try:
            resp = self._http.get(url, timeout=15)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except Exception as exc:
            logger.warning("Could not fetch server config (%s); using defaults", exc)
            return ServerConfig()

        single_res_raw = data.get("singleResolution") or {}
        if isinstance(single_res_raw, dict):
            try:
                single_res = int(single_res_raw.get("value", 0) or 0)
            except (ValueError, TypeError):
                single_res = 0
        else:
            try:
                single_res = int(single_res_raw or 0)
            except (ValueError, TypeError):
                single_res = 0

        return ServerConfig(
            auto_convert_to_mp3=bool(data.get("autoConvertVideosToMP3")),
            single_resolution=single_res,
            save_original_resolution=bool(data.get("saveOriginalVideoResolution")),
            disable_hls=bool(data.get("doNotShowEncoderAutomaticHLS")),
            disable_mp4=bool(data.get("doNotShowEncoderAutomaticMP4")),
        )

    def get_site_status(self) -> SiteStatus:
        """Read the upload/storage limits from ``status`` (best effort, never raises)."""
        for path in ("status", "objects/status.json.php"):
            try:
                resp = self._http.get(self._url(path), timeout=15)
                if resp.status_code == 404:
                    continue
                data = resp.json()
            except Exception as exc:
                logger.warning("Could not read the site status (%s)", exc)
                return SiteStatus()
            if not isinstance(data, dict):
                return SiteStatus()
            return SiteStatus(
                version=str(data.get("version") or ""),
                max_file_size=_as_int(data.get("file_upload_max_size")) or 0,
                storage_limit_minutes=_as_int(data.get("videoStorageLimitMinutes")) or 0,
                storage_used_seconds=_as_int(data.get("currentStorageUsage")) or 0,
            )
        return SiteStatus()

    def get_categories(self) -> list[dict[str, Any]]:
        """Return list of video categories from AVideo.

        Each item has at minimum: ``id`` (int) and ``name`` (str).
        Falls back to an empty list on failure. Prefer ``LoginResult.categories``
        when a login response is available (no extra request).
        """
        url = self._url("objects/categories.json.php")
        try:
            resp = self._http.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            # AVideo returns {"rows": [...], "total": N} from objects/categories.json.php
            # or a bare list, or {"response": [...]}
            if isinstance(data, list):
                items = data
            else:
                items = data.get("rows") or data.get("response") or data.get("categories") or []
            return [
                {"id": int(c.get("id", 0)), "name": str(c.get("name", ""))}
                for c in items
                if c.get("id") and c.get("name")
            ]
        except Exception as exc:
            logger.warning("Could not fetch categories (%s)", exc)
            return []

    def register_video(
        self,
        title: str,
        format_ext: str,
        resolution: int | None,
        duration: float,
        categories_id: int = 0,
        description: str = "",
        download_url: str = "",
        videos_id: int | None = None,
    ) -> RegisterVideoResult:
        """Create or update a video record on AVideo.

        Called before uploading the encoded file so we receive a ``videos_id``
        and ``video_id_hash`` that authorize all subsequent requests.
        ``download_url`` is the source page (stored as ``videoDownloadedLink``);
        it is never sent as ``downloadURL``, which would make the site fetch it.
        ``resolution`` is ``None`` for formats stored without one (HLS zip, mp3).
        """
        data: dict[str, Any] = {
            **self._auth_fields(),
            "first_request": "1",
            "title": title,
            "format": format_ext,
            "resolution": "" if resolution is None else str(resolution),
            "duration": format_duration(duration),
            "categories_id": str(categories_id),
            "description": description,
            "videoDownloadedLink": download_url,
            "encoderURL": "",
            "keepEncoding": "0",
            "return_vars": self._return_vars(),
        }
        if videos_id:
            data["videos_id"] = str(videos_id)

        logger.debug("POST %saVideoEncoder.json (register)", self._base)
        resp = self._post(("aVideoEncoder.json", "objects/aVideoEncoder.json.php"), data=data)
        self._check_status(resp, "registering the video")
        body = self._json(resp, "registering the video")
        if not isinstance(body, dict):
            body = {}
        logger.debug("register_video response: %s", body)

        vid = int(body.get("videos_id") or body.get("video_id") or 0)
        if not vid:
            detail = str(body.get("msg") or "")[:300]
            raise AVideoAPIError(
                f"Video registration failed – no videos_id returned: {detail}",
                code="register_failed",
                params={"detail": detail},
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
        resolution: int | None,
        duration: float,
        categories_id: int = 0,
        description: str = "",
        download_url: str = "",
        chunk_size: int = CHUNK_SIZE,
        progress_callback: UploadProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Upload an encoded file to AVideo via chunked PUT + final POST.

        Flow (mirrors Encoder.php ``sendFileChunk`` / ``sendFile``):
          1. PUT each chunk, streamed from disk, to
             ``aVideoEncoderChunk.json?file_id=…&chunk=…&total=…`` with the
             ``X-Encoder-User``/``X-Encoder-Pass`` headers; a failed chunk is retried
             with the same ``file_id`` (the server keeps the committed chunks).
          2. POST the assembled server-side path to ``aVideoEncoder.json`` as ``chunkFile``.
          If the site cannot take chunks (HTTP 413/404/403, an old single-PUT server
          with several chunks, or retries exhausted) the file is sent as a multipart
          ``video`` POST instead.
        """
        data: dict[str, Any] = {
            **self._auth_fields(),
            "videos_id": str(videos_id),
            "video_id_hash": video_id_hash,
            "title": title,
            "format": format_ext,
            "resolution": "" if resolution is None else str(resolution),
            "duration": format_duration(duration),
            "categories_id": str(categories_id),
            "description": description,
            "videoDownloadedLink": download_url,
            "encoderURL": "",
            "keepEncoding": "0",
            "return_vars": self._return_vars(),
        }

        assembled_file = self._upload_chunks(file_path, chunk_size, progress_callback)
        if assembled_file is None:
            return self._upload_multipart(file_path, data, progress_callback)

        data["chunkFile"] = assembled_file
        logger.debug("POST %saVideoEncoder.json (finalize)", self._base)
        resp = self._post(("aVideoEncoder.json", "objects/aVideoEncoder.json.php"), data=data)
        return self._finalize_result(resp)

    def _finalize_result(self, resp: httpx.Response) -> dict[str, Any]:
        self._check_status(resp, "saving the uploaded file")
        result = self._json(resp, "saving the uploaded file")
        if not isinstance(result, dict):
            result = {}
        logger.debug("upload finalize response: %s", result)
        if result.get("error") is True:
            detail = str(result.get("msg") or "")[:300]
            raise AVideoAPIError(
                f"The site could not save the file: {detail}",
                code="save_failed",
                params={"detail": detail},
            )
        return result

    def _chunk_body(
        self,
        file_path: Path,
        offset: int,
        length: int,
        on_bytes: Callable[[int], None],
    ) -> Iterator[bytes]:
        with open(file_path, "rb") as fh:
            fh.seek(offset)
            remaining = length
            while remaining > 0:
                piece = fh.read(min(_STREAM_PIECE, remaining))
                if not piece:
                    break
                remaining -= len(piece)
                on_bytes(len(piece))
                yield piece

    def _upload_chunks(
        self,
        file_path: Path,
        chunk_size: int,
        progress_callback: UploadProgressCallback | None,
    ) -> str | None:
        """PUT the file in chunks; return the assembled server path, or None to fall back."""
        file_size = file_path.stat().st_size
        total_chunks = max(1, -(-file_size // chunk_size))  # ceiling division
        file_id = generate_file_id()
        headers = {"X-Encoder-User": self._username, "X-Encoder-Pass": self._encrypted_pass}
        # Rewritten URL first; installs without .htaccess rewrites only have the direct file.
        chunk_paths = ["aVideoEncoderChunk.json", "objects/aVideoEncoderChunk.json.php"]
        assembled_file = ""

        def chunk_done(end: int) -> None:
            if progress_callback:
                progress_callback(file_path.name, end, file_size)

        for index in range(total_chunks):
            offset = index * chunk_size
            length = min(chunk_size, file_size - offset)
            is_last = index == total_chunks - 1
            attempt = 0
            while True:
                url = self._url(
                    f"{chunk_paths[0]}?file_id={file_id}&chunk={index}&total={total_chunks}"
                )
                sent = [offset]

                def on_bytes(n: int, _sent: list[int] = sent) -> None:
                    _sent[0] += n
                    if progress_callback:
                        progress_callback(file_path.name, _sent[0], file_size)

                logger.debug("PUT chunk %d/%d (%d bytes)", index + 1, total_chunks, length)
                problem = ""
                try:
                    resp = self._http.put(
                        url,
                        content=self._chunk_body(file_path, offset, length, on_bytes),
                        headers={**headers, "Content-Length": str(length)},
                    )
                except httpx.TransportError as exc:
                    problem = f"network error: {exc}"
                else:
                    status = resp.status_code
                    if status == 404 and len(chunk_paths) > 1:
                        chunk_paths.pop(0)
                        continue
                    if status in (401, 403, 404, 413):
                        logger.warning(
                            "Chunk upload not accepted (HTTP %d); falling back to a single upload",
                            status,
                        )
                        return None
                    try:
                        body = self._json(resp, "uploading")
                    except AVideoAPIError as exc:
                        body, problem = {}, str(exc)
                    if not isinstance(body, dict):
                        body = {}
                    if not problem and status < 300 and body.get("file") and "chunk" not in body:
                        # Legacy single-PUT server: it cannot assemble several chunks.
                        if total_chunks == 1:
                            chunk_done(file_size)
                            return str(body["file"])
                        logger.warning("Site only supports single-PUT uploads; falling back")
                        return None
                    if not problem:
                        ok = (
                            status < 300
                            and bool(body.get("file"))
                            and _as_int(body.get("chunk")) == index
                            and (
                                not is_last
                                or (
                                    bool(body.get("complete"))
                                    and _as_int(body.get("filesize")) == file_size
                                )
                            )
                        )
                        if ok:
                            assembled_file = str(body["file"])
                            chunk_done(offset + length)
                            break
                        problem = f"HTTP {status}, response {body}"

                attempt += 1
                if attempt > MAX_CHUNK_RETRIES:
                    logger.warning(
                        "Chunk %d/%d failed %d times (%s); falling back to a single upload",
                        index + 1,
                        total_chunks,
                        attempt,
                        problem,
                    )
                    return None
                backoff = min(30, 2**attempt)  # 2, 4, 8, 16, 30, 30 s
                logger.warning(
                    "Chunk %d/%d failed (%s); retrying in %ds",
                    index + 1,
                    total_chunks,
                    problem,
                    backoff,
                )
                _sleep(backoff)

        if not assembled_file:
            raise AVideoAPIError(
                "Server did not return assembled chunk file path", code="save_failed"
            )
        return assembled_file

    def _upload_multipart(
        self,
        file_path: Path,
        data: dict[str, Any],
        progress_callback: UploadProgressCallback | None,
    ) -> dict[str, Any]:
        """Send the whole file as a multipart ``video`` field (PHP: ``Encoder::sendFile``)."""
        file_size = file_path.stat().st_size
        logger.debug("POST %saVideoEncoder.json (multipart, %d bytes)", self._base, file_size)
        with open(file_path, "rb") as fh:
            resp = self._post(
                ("aVideoEncoder.json", "objects/aVideoEncoder.json.php"),
                data=data,
                files={"video": (file_path.name, fh, "application/octet-stream")},
            )
        if resp.status_code == 413:
            raise AVideoAPIError(
                "The file is larger than this site accepts. "
                "Ask the site administrator to raise the upload limit.",
                code="file_too_large",
            )
        if progress_callback:
            progress_callback(file_path.name, file_size, file_size)
        return self._finalize_result(resp)

    def upload_images(
        self,
        videos_id: int,
        video_id_hash: str,
        duration: float,
        jpg_path: Path | None = None,
        gif_path: Path | None = None,
        webp_path: Path | None = None,
    ) -> dict[str, Any]:
        """Upload JPG / GIF / WebP thumbnails to AVideo.

        Mirrors Encoder.php ``sendImages`` / getImage upload to
        ``objects/aVideoEncoderReceiveImage.json.php``.
        """
        fields: dict[str, Any] = {
            **self._auth_fields(),
            "videos_id": str(videos_id),
            "video_id_hash": video_id_hash,
            "duration": format_duration(duration),
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
            self._check_status(resp, "sending the thumbnails")
            result = self._json(resp, "sending the thumbnails")
            if not isinstance(result, dict):
                result = {}
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
        self._check_status(resp, "finishing the upload")
        result = self._json(resp, "finishing the upload")
        if not isinstance(result, dict):
            result = {}
        logger.debug("notify_done response: %s", result)
        return result

    def notify_failed(self, videos_id: int, video_id_hash: str) -> None:
        """Best-effort ``fail=1`` so the site does not keep the video in "encoding" forever."""
        try:
            self.notify_done(videos_id, video_id_hash, failed=True)
            logger.info("Told the site that videos_id=%d failed", videos_id)
        except Exception as exc:
            logger.warning("Could not notify the site about the failure: %s", exc)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
