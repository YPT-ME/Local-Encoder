"""FastAPI web server providing a browser UI for avideo-local-encoder.

Start with:
    local-encoder serve            # default: http://127.0.0.1:47800
    local-encoder serve --port 9000
"""

from __future__ import annotations

import json
import logging
import os
import platform
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Generator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from local_encoder import __version__, folders, history, keep_awake, settings, updates
from local_encoder.avideo_client import (
    AVideoClient,
    LoginResult,
    ServerConfig,
    SiteStatus,
)
from local_encoder.config import APP_DATA_DIR, Config, default_work_dir
from local_encoder.downloader import (
    download_video,
    get_video_info,
    is_web_url,
    reject_unsupported,
)
from local_encoder.encoder import (
    ALLOWED_RESOLUTIONS,
    ENCODING_SETTINGS,
    VideoCodec,
    detect_video_codec,
    encode_hls,
    encode_mp4_multi,
    extract_mp3,
    extract_thumbnail_gif,
    extract_thumbnail_jpg,
    extract_thumbnail_webp,
    output_resolution,
    probe_media,
)
from local_encoder.errors import JobCancelled, LocalEncoderError, classify
from local_encoder.logging_setup import configure_logging, log_file_path
from local_encoder.utils import probe_duration, sanitize_filename

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    # Quitting Local Encoder: stop the running FFmpeg instead of leaving it behind.
    stop_running_jobs()


app = FastAPI(title="AVideo Local Encoder", version=__version__, lifespan=_lifespan)

# ---------------------------------------------------------------------------
# Only this computer's browser, only from the Local Encoder page
# ---------------------------------------------------------------------------
# Any web page the user visits can send requests to 127.0.0.1. The Host check stops DNS
# rebinding, and the custom header (which a cross-site form cannot set without a CORS
# preflight, which this server never allows) stops cross-site posts to state-changing endpoints.

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
API_HEADER = "x-local-encoder"


def _host_name(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end > 0 else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


@app.middleware("http")
async def _local_requests_only(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if _host_name(request.headers.get("host", "")) not in LOCAL_HOSTS:
        return JSONResponse(
            {"detail": "Local Encoder only answers to this computer."}, status_code=403
        )
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(API_HEADER) != "1":
        return JSONResponse(
            {"detail": "Missing the Local Encoder request header."}, status_code=403
        )
    return await call_next(request)


STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Where jobs download and encode (one sub-folder per job).
OUTPUT_DIR = default_work_dir()
REPORTS_DIR = APP_DATA_DIR / "reports"

# ---------------------------------------------------------------------------
# Sessions – the password is used once to log in; later calls reuse the token
# AVideo returned (valid ~1 day), so the browser never stores the password and
# each job does not log in again (AVideo rate-limits encoder logins).
# ---------------------------------------------------------------------------

SESSION_TTL_SECONDS = 12 * 3600


@dataclass
class _Session:
    server_url: str
    ssl_verify: bool
    login: LoginResult
    created: float
    config: ServerConfig = field(default_factory=ServerConfig)
    status: SiteStatus = field(default_factory=SiteStatus)


_sessions: dict[str, _Session] = {}


def _get_session(session_id: str) -> _Session:
    session = _sessions.get(session_id)
    if session is None or time.time() - session.created > SESSION_TTL_SECONDS:
        _sessions.pop(session_id, None)
        raise HTTPException(
            status_code=401, detail="Please connect to your AVideo site again (session expired)."
        )
    return session


def _hls_available(session: _Session) -> bool:
    """The site can play HLS (VideoHLS enabled) and does not hide automatic HLS."""
    return session.login.video_hls and not session.config.disable_hls


def _site_resolutions(session: _Session) -> list[int]:
    """The qualities this site and user accept (single-resolution cap, user groups)."""
    result = list(ALLOWED_RESOLUTIONS)
    allowed = session.login.allowed_resolutions
    if allowed:
        # Like the PHP Encoder (Format.php getFinalResolutions): no overlap → keep the list.
        result = [r for r in result if r in allowed] or result
    cap = session.config.single_resolution
    if cap > 0:
        result = [r for r in result if r <= cap] or [ALLOWED_RESOLUTIONS[0]]
    return result


def _site_summary(session: _Session) -> dict[str, Any]:
    status = session.status
    storage_left: int | None = None
    if status.storage_limit_minutes > 0:
        storage_left = max(0, status.storage_limit_minutes - status.storage_used_seconds // 60)
    return {
        "url": session.server_url,
        "host": urlsplit(session.server_url).netloc,
        "hls": _hls_available(session),
        "mp4": True,
        "mp3": session.config.auto_convert_to_mp3,
        "resolutions": _site_resolutions(session),
        "max_file_size": status.max_file_size,
        "storage_left_minutes": storage_left,
        "version": status.version,
    }


def _session_info(session_id: str, session: _Session) -> dict[str, Any]:
    categories = session.login.categories
    if not categories:
        with AVideoClient(session.server_url, ssl_verify=session.ssl_verify) as client:
            categories = client.get_categories()
    return {
        "ok": True,
        "session_id": session_id,
        "username": session.login.username,
        "user_id": session.login.user_id,
        "name": session.login.name or session.login.username,
        "logo_url": session.server_url + "videos/userPhoto/logo.png",
        "categories": categories,
        "site": _site_summary(session),
    }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ImportRequest(BaseModel):
    url: str
    session_id: str
    categories_id: int = 0
    title: str = ""
    description: str = ""
    format: str = "auto"  # "auto" | "mp4" | "hls"
    resolutions: list[int] = []  # empty = all the site allows
    use_gpu: bool = True


class TestConnectionRequest(BaseModel):
    server_url: str
    username: str
    password: str
    ssl_verify: bool = True


class SessionRequest(BaseModel):
    session_id: str


class PreviewRequest(BaseModel):
    url: str


class RetryRequest(BaseModel):
    session_id: str = ""


class RemoveRequest(BaseModel):
    delete_files: bool = True


class FolderRequest(BaseModel):
    path: str = ""


class ScanRequest(BaseModel):
    path: str
    recursive: bool = False
    site_url: str = ""
    username: str = ""


class LocalImportRequest(BaseModel):
    session_id: str
    paths: list[str]
    categories_id: int = 0
    description: str = ""
    format: str = "auto"
    resolutions: list[int] = []
    use_gpu: bool = True


class ReportRequest(BaseModel):
    job_id: str = ""


# ---------------------------------------------------------------------------
# Jobs – state kept on the server, so reloading the page loses nothing
# ---------------------------------------------------------------------------

ACTIVE = ("pending", "running")
MAX_LOG_LINES = 400


@dataclass
class JobOptions:
    categories_id: int = 0
    title: str = ""
    description: str = ""
    fmt: str = "auto"
    resolutions: list[int] = field(default_factory=list)
    use_gpu: bool = True


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# One event stream for the whole queue (browsers allow only ~6 connections per host, so one
# stream per job would block the page with a long queue). A new subscriber first receives every
# job's full state; the lock makes that snapshot and the following events consistent.
_state_lock = threading.RLock()
_subscribers: list[queue.Queue[str | None]] = []


def _publish(event: str, data: dict[str, Any]) -> None:
    message = _sse(event, data)
    with _state_lock:
        for subscriber in _subscribers:
            subscriber.put(message)


def _subscribe() -> queue.Queue[str | None]:
    subscriber: queue.Queue[str | None] = queue.Queue()
    with _state_lock:
        jobs = [_jobs[jid].snapshot() for jid in _job_order if jid in _jobs]
        subscriber.put(_sse("jobs", {"jobs": jobs}))
        _subscribers.append(subscriber)
    return subscriber


def _unsubscribe(subscriber: queue.Queue[str | None]) -> None:
    with _state_lock:
        if subscriber in _subscribers:
            _subscribers.remove(subscriber)


def page_open() -> bool:
    """True while a browser page follows the queue."""
    return bool(_subscribers)


class Job:
    """One video: its options, progress, logs and the files kept for a new attempt."""

    def __init__(
        self,
        kind: str,
        source: str,
        session: _Session,
        options: JobOptions,
        work_dir: Path | None = None,
        job_id: str | None = None,
    ) -> None:
        self.id = job_id or str(uuid.uuid4())
        self.kind = kind  # "url" | "file"
        self.source = source  # the link, or the file name
        self.session = session
        self.options = options
        self.work_dir = work_dir or OUTPUT_DIR / self.id
        self.created = time.time()
        self.status = "pending"
        self.title = options.title or (source if kind == "file" else "")
        self.description = options.description
        self.thumbnail = ""
        self.stage = ""
        self.pct: dict[str, int] = {"download": 0, "encode": 0, "upload": 0}
        self.info: dict[str, Any] = {}
        self.notices: list[dict[str, Any]] = []
        self.result: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self.logs: deque[str] = deque(maxlen=MAX_LOG_LINES)
        self.cancel_event = threading.Event()
        # Work kept for a new attempt
        self.raw_file: Path | None = None
        self.encoded: list[Path] = []
        self.encoded_fmt = ""
        self.encoded_resolutions: list[int] = []
        self.videos_id: int | None = None

    # -- state -----------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "kind": self.kind,
            "source": self.source,
            "site": urlsplit(self.session.server_url).netloc,
            "site_url": self.session.server_url,
            "username": self.session.login.username,
            "user_id": self.session.login.user_id,
            "status": self.status,
            "title": self.title,
            "thumbnail": self.thumbnail,
            "stage": self.stage,
            "pct": dict(self.pct),
            "info": dict(self.info),
            "notices": list(self.notices),
            "result": self.result,
            "error": self.error,
            "created": self.created,
            "has_files": self.work_dir.exists(),
            "path": str(self.raw_file) if self.kind == "local" and self.raw_file else "",
        }

    def snapshot(self) -> dict[str, Any]:
        return {**self.summary(), "logs": list(self.logs)}

    def _apply(self, event: str, data: dict[str, Any]) -> None:
        if event == "log":
            self.logs.append(f"[{time.strftime('%H:%M:%S')}] {data.get('msg', '')}")
        elif event == "progress":
            step = str(data.get("step", ""))
            if step in self.pct:
                self.pct[step] = max(0, min(100, int(data.get("pct", 0))))
                self.stage = step
        elif event == "info":
            for key, value in data.items():
                if key == "title" and value:
                    self.title = str(value)
                elif key == "thumbnail" and value:
                    self.thumbnail = str(value)
                elif key not in ("title", "thumbnail"):
                    self.info[key] = value
        elif event == "notice":
            if all(n.get("code") != data.get("code") for n in self.notices):
                self.notices.append(data)
        elif event == "status":
            self.status = str(data.get("status", self.status))
        elif event == "done":
            self.status = "done"
            self.result = data
            self.pct = {"download": 100, "encode": 100, "upload": 100}
        elif event in ("error", "cancelled"):
            self.status = "error" if event == "error" else "cancelled"
            self.error = data

    def emit(self, event: str, data: dict[str, Any]) -> None:
        with _state_lock:
            self._apply(event, data)
            if self.id in _jobs:
                _publish(event, {"job_id": self.id, **data})

    def log(self, msg: str) -> None:
        logger.info("Job %s: %s", self.id, msg)
        self.emit("log", {"msg": msg})

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled()


_jobs: dict[str, Job] = {}
_job_order: list[str] = []  # insertion order for the queue UI
_work_queue: queue.Queue[str] = queue.Queue()  # job ids waiting for the worker

# Set by the tray icon: called as notifier(kind, video_title) when a job ends unwatched.
_notifier: Callable[[str, str], None] | None = None


def set_notifier(fn: Callable[[str, str], None] | None) -> None:
    global _notifier
    _notifier = fn


def active_job_count() -> int:
    """Jobs waiting or running (the tray asks before quitting while there are any)."""
    return sum(1 for job in _jobs.values() if job.status in ACTIVE)


def stop_running_jobs(timeout: float = 10.0) -> None:
    """Cancel every job and wait a little for the running one to stop its FFmpeg."""
    for job in list(_jobs.values()):
        if job.status in ACTIVE:
            job.cancel_event.set()
            if job.status == "pending":
                job.status = "cancelled"
    deadline = time.time() + timeout
    while time.time() < deadline and any(j.status == "running" for j in _jobs.values()):
        time.sleep(0.2)


def _enqueue(job: Job) -> None:
    """Register a job and push it onto the work queue."""
    with _state_lock:
        if job.id not in _jobs:
            _jobs[job.id] = job
            _job_order.append(job.id)
            _publish("added", job.snapshot())
    _work_queue.put(job.id)


def _worker() -> None:
    """Single background thread that processes jobs one at a time."""
    while True:
        job_id = _work_queue.get()
        try:
            job = _jobs.get(job_id)
            if job is None or job.status != "pending":
                continue  # removed or cancelled while waiting
            with keep_awake.inhibit():
                _run_job(job)
        except Exception as exc:
            logger.exception("Worker caught unhandled error for %s: %s", job_id, exc)
        finally:
            _work_queue.task_done()


_worker_thread = threading.Thread(target=_worker, daemon=True, name="encode-worker")
_worker_thread.start()


def _run_job(job: Job) -> None:
    job.emit("status", {"status": "running"})
    try:
        _pipeline(job)
    except Exception as exc:
        problem = classify(exc)
        if problem.code == "cancelled":
            job.log("Cancelled.")
            job.emit("cancelled", problem.to_dict())
        else:
            logger.exception("Job %s failed", job.id)
            job.log(f"Failed: {exc}")
            job.emit("error", problem.to_dict())
    finally:
        _finish_job(job)


def _record_history(job: Job) -> None:
    """Remember the result, so a folder scan can show which videos were already sent."""
    if job.status not in ("done", "error"):
        return
    source = job.source
    if job.kind == "local" and job.raw_file is not None:
        source = str(job.raw_file)
    entry = history.HistoryEntry(
        id=job.id,
        url=source,
        server=job.session.server_url,
        username=job.session.login.username,
        title=job.title,
        status="success" if job.status == "done" else "failed",
        error=str((job.error or {}).get("message", "")),
        videos_id=job.videos_id,
    )
    try:
        history.update_entry(entry)
    except OSError as exc:
        logger.warning("Could not write the history: %s", exc)


def _finish_job(job: Job) -> None:
    """Delete the job's files after success; keep them after a failure so no work is lost."""
    if job.status == "done":
        shutil.rmtree(job.work_dir, ignore_errors=True)
    elif job.work_dir.exists() and any(job.work_dir.iterdir()):
        logger.info("Job %s: files kept for a new attempt in %s", job.id, job.work_dir)
    job.emit("info", {"has_files": job.work_dir.exists()})
    _record_history(job)
    if not page_open() and _notifier is not None and job.status in ("done", "error"):
        try:
            _notifier(job.status, job.title or job.source)
        except Exception as exc:
            logger.debug("Notifier failed: %s", exc)


# ---------------------------------------------------------------------------
# Pipeline: download → probe → plan → encode → thumbnails → register → upload → notify
# Every step reuses what an earlier attempt already produced.
# ---------------------------------------------------------------------------

_info_cache: dict[str, tuple[float, dict[str, Any]]] = {}
INFO_CACHE_SECONDS = 600


def _video_info(url: str) -> dict[str, Any]:
    """yt-dlp metadata for *url*, cached so the preview and the job ask only once."""
    hit = _info_cache.get(url)
    if hit and time.time() - hit[0] < INFO_CACHE_SECONDS:
        return hit[1]
    info = get_video_info(url)
    if len(_info_cache) > 50:
        _info_cache.clear()
    _info_cache[url] = (time.time(), info)
    return info


def _check_disk(path: Path, needed: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(path).free
    if free < needed:
        raise LocalEncoderError(
            "no_disk_space",
            {"needed_gb": f"{needed / 1e9:.1f}", "free_gb": f"{free / 1e9:.1f}"},
        )


@dataclass
class _Plan:
    fmt: str
    resolutions: list[int]


def _plan(job: Job, duration: float) -> _Plan:
    """Pick the format and qualities from the user's choice and what the site accepts."""
    session, opts = job.session, job.options
    wanted = opts.fmt if opts.fmt in ("mp4", "hls") else "auto"
    if wanted == "mp4":
        fmt = "mp4"
    elif _hls_available(session):
        fmt = "hls"
    else:
        fmt = "mp4"
        if wanted == "hls":
            job.emit("notice", {"code": "hls_unavailable"})
    site = _site_resolutions(session)
    chosen = [r for r in sorted(set(opts.resolutions)) if r in ALLOWED_RESOLUTIONS]
    resolutions = [r for r in chosen if r in site] if chosen else site
    if chosen and not resolutions:
        resolutions = [min(site)]
    if session.login.allowed_resolutions and max(resolutions) < max(ALLOWED_RESOLUTIONS):
        job.emit("notice", {"code": "quality_limited", "params": {"max": max(resolutions)}})
    left = _site_summary(session)["storage_left_minutes"]
    if left is not None and duration / 60 > left:
        job.emit("notice", {"code": "storage_low", "params": {"left_minutes": left}})
    return _Plan(fmt=fmt, resolutions=resolutions)


def _estimate_bytes(plan: _Plan, height: int, duration: float) -> int:
    """Rough size of the encoded files, to check the free disk space before encoding."""
    top = height or 1080
    eligible = [r for r in plan.resolutions if r <= top] or plan.resolutions[:1]
    kbps = sum(
        ENCODING_SETTINGS[r]["maxrate"] + ENCODING_SETTINGS[r]["audioBitrate"] for r in eligible
    )
    size = kbps * 1000 / 8 * max(duration, 1.0)
    if plan.fmt == "hls":
        size *= 2  # segments + the zip
    return int(size * 1.2) + 200 * 1024 * 1024


def _download(job: Job) -> Path:
    url = job.source
    job.log(f"Reading the link: {url}")
    try:
        info = _video_info(url)
    except Exception as exc:  # the download below gives the real error
        info = {}
        job.log(f"Could not read the link details: {exc}")
    reject_unsupported(info)
    if not job.title:
        job.emit("info", {"title": sanitize_filename(str(info.get("title") or "video"))})
    if not job.description:
        job.description = str(info.get("description") or "")
    job.emit(
        "info",
        {
            "thumbnail": str(info.get("thumbnail") or ""),
            "uploader": str(info.get("uploader") or info.get("channel") or ""),
            "duration_s": int(info.get("duration") or 0),
        },
    )
    approx = int(info.get("filesize") or info.get("filesize_approx") or 0)
    if approx:
        _check_disk(job.work_dir, int(approx * 1.1) + 100 * 1024 * 1024)

    def on_download(status: str, downloaded: int, total: int) -> None:
        pct = int(downloaded * 100 / total) if total else 0
        job.emit("progress", {"step": "download", "pct": pct})

    raw = download_video(
        url=url,
        output_dir=job.work_dir,
        filename_stem=sanitize_filename(job.title or "video")[:80],
        progress_callback=on_download,
        cancel_event=job.cancel_event,
    )
    job.log(f"Downloaded: {raw.name}")
    return raw


def _encode(job: Job, cfg: Config, plan: _Plan) -> list[Path]:
    codec: VideoCodec = detect_video_codec(cfg.ffmpeg_bin, prefer_hardware=job.options.use_gpu)
    job.emit(
        "info",
        {"encoder": codec.label, "encoder_key": codec.key, "encoder_hardware": codec.hardware},
    )
    job.log(f"Converting with: {codec.label}")
    assert job.raw_file is not None

    def on_encode(current: int, total: int) -> None:
        pct = int(current * 100 / total) if total else 0
        job.emit("progress", {"step": "encode", "pct": pct})

    def on_notice(code: str) -> None:
        job.log("The graphics card could not convert this video; using the processor instead.")
        job.emit("notice", {"code": code})

    if plan.fmt == "mp4":
        files = encode_mp4_multi(
            input_path=job.raw_file,
            output_dir=job.work_dir,
            resolutions=plan.resolutions,
            ffmpeg_bin=cfg.ffmpeg_bin,
            ffprobe_bin=cfg.ffprobe_bin,
            progress_callback=on_encode,
            codec=codec,
            cancel_event=job.cancel_event,
            notice_callback=on_notice,
        )
        job.log(f"Converted {len(files)} MP4 file(s)")
        return files
    zip_path = encode_hls(
        input_path=job.raw_file,
        output_dir=job.work_dir,
        resolutions=plan.resolutions,
        ffmpeg_bin=cfg.ffmpeg_bin,
        ffprobe_bin=cfg.ffprobe_bin,
        progress_callback=on_encode,
        codec=codec,
        cancel_event=job.cancel_event,
        notice_callback=on_notice,
    )
    job.log(f"Streaming package ready: {zip_path.name}")
    return [zip_path]


def _thumbnails(job: Job, cfg: Config, duration: float) -> dict[str, Path]:
    assert job.raw_file is not None
    raw = job.raw_file
    # Middle of the video, capped at 600 s – the PHP Encoder's choice (Encoder.php sendImages).
    seek = min(duration / 2, 600.0) if duration > 0 else 5.0
    stem = raw.stem
    paths = {
        "jpg": job.work_dir / f"{stem}.jpg",
        "gif": job.work_dir / f"{stem}.gif",
        "webp": job.work_dir / f"{stem}.webp",
    }
    makers: dict[str, Callable[[], Path]] = {
        "jpg": lambda: extract_thumbnail_jpg(raw, paths["jpg"], seek, cfg.ffmpeg_bin),
        "gif": lambda: extract_thumbnail_gif(raw, paths["gif"], seek, 3.0, cfg.ffmpeg_bin),
        "webp": lambda: extract_thumbnail_webp(raw, paths["webp"], seek, 3.0, cfg.ffmpeg_bin),
    }
    for kind, make in makers.items():
        if paths[kind].exists():
            continue
        try:
            make()
        except Exception as exc:
            job.log(f"Thumbnail {kind.upper()} skipped: {exc}")
    return {kind: path for kind, path in paths.items() if path.exists()}


def _upload(job: Job, cfg: Config, plan: _Plan, duration: float, thumbs: dict[str, Path]) -> None:
    session = job.session
    files = sorted(job.encoded, key=lambda p: p.stat().st_size)  # smallest first, like Encoder.php
    download_url = job.source if job.kind == "url" else ""
    is_hls = plan.fmt == "hls"
    top = max((r for r in (output_resolution(f) for f in files) if r is not None), default=None)
    job.emit("progress", {"step": "upload", "pct": 0})

    with AVideoClient(session.server_url, ssl_verify=session.ssl_verify) as client:
        client.use_login(session.login)
        job.log(f"Sending as {session.login.name or session.login.username}")
        reg = client.register_video(
            title=job.title,
            format_ext="zip" if is_hls else "mp4",
            resolution=None if is_hls else top,
            duration=duration,
            categories_id=job.options.categories_id,
            description=job.description,
            download_url=download_url,
            videos_id=job.videos_id,  # a new attempt updates the same video
        )
        job.videos_id = reg.videos_id
        job.log(f"Video created on the site (id {reg.videos_id})")

        # From here on the site has a video record: tell it when anything fails,
        # otherwise the video stays in "encoding" forever (Encoder.php does the same).
        try:
            total = sum(f.stat().st_size for f in files) or 1
            done_bytes = 0
            for enc_file in files:
                size = enc_file.stat().st_size

                def on_upload(_name: str, sent: int, _total: int, _base: int = done_bytes) -> None:
                    job.check_cancel()
                    pct = int((_base + sent) * 100 / total)
                    job.emit("progress", {"step": "upload", "pct": min(pct, 99)})

                client.upload_file(
                    file_path=enc_file,
                    videos_id=reg.videos_id,
                    video_id_hash=reg.video_id_hash,
                    title=job.title,
                    format_ext="zip" if enc_file.suffix == ".zip" else "mp4",
                    resolution=output_resolution(enc_file),
                    duration=duration,
                    categories_id=job.options.categories_id,
                    description=job.description,
                    download_url=download_url,
                    progress_callback=on_upload,
                )
                done_bytes += size
                job.log(f"Sent {enc_file.name} ({size // 1_048_576} MiB)")

            if session.config.auto_convert_to_mp3 and not is_hls:
                assert job.raw_file is not None
                mp3_file = job.work_dir / f"{job.raw_file.stem}.mp3"
                try:
                    job.check_cancel()
                    if not mp3_file.exists():
                        job.log("Creating the MP3 the site asks for…")
                        extract_mp3(job.raw_file, mp3_file, ffmpeg_bin=cfg.ffmpeg_bin)
                    client.upload_file(
                        file_path=mp3_file,
                        videos_id=reg.videos_id,
                        video_id_hash=reg.video_id_hash,
                        title=job.title,
                        format_ext="mp3",
                        resolution=None,
                        duration=duration,
                        categories_id=job.options.categories_id,
                        description=job.description,
                    )
                    job.log("MP3 sent")
                except JobCancelled:
                    raise
                except Exception as exc:
                    job.log(f"MP3 skipped: {exc}")

            job.check_cancel()
            if thumbs:
                client.upload_images(
                    videos_id=reg.videos_id,
                    video_id_hash=reg.video_id_hash,
                    duration=duration,
                    jpg_path=thumbs.get("jpg"),
                    gif_path=thumbs.get("gif"),
                    webp_path=thumbs.get("webp"),
                )
            client.notify_done(reg.videos_id, reg.video_id_hash)
        except BaseException:
            client.notify_failed(reg.videos_id, reg.video_id_hash)
            raise

    site = session.server_url
    job.emit(
        "done",
        {
            "videos_id": reg.videos_id,
            "url": f"{site}video/{reg.videos_id}",
            "edit_url": f"{site}view/managerVideosLight.php?videos_id={reg.videos_id}",
        },
    )


def _pipeline(job: Job) -> None:
    session, opts = job.session, job.options
    cfg = Config(
        server_url=session.server_url,
        categories_id=opts.categories_id,
        ssl_verify=session.ssl_verify,
    )
    job.work_dir.mkdir(parents=True, exist_ok=True)

    # 1. The video file
    if job.raw_file is None or not job.raw_file.exists():
        if job.kind != "url":
            raise LocalEncoderError("source_missing")
        job.raw_file = _download(job)
    job.emit("progress", {"step": "download", "pct": 100})
    job.check_cancel()

    # 2. What is in it
    media = probe_media(job.raw_file, cfg.ffprobe_bin)
    if not media.has_video:
        raise LocalEncoderError("audio_only" if media.has_audio else "unreadable_file")
    duration = probe_duration(job.raw_file, cfg.ffprobe_bin) or float(
        job.info.get("duration_s") or 0
    )
    job.emit(
        "info",
        {"duration_s": int(duration), "file_size_bytes": job.raw_file.stat().st_size},
    )

    # 3. What the site accepts (re-read: the administrator may have changed it)
    with AVideoClient(session.server_url, ssl_verify=session.ssl_verify) as client:
        session.config = client.get_server_config()
    plan = _plan(job, duration)
    job.emit("info", {"encoding_format": plan.fmt, "encoding_resolutions": plan.resolutions})
    job.log(
        f"Format: {plan.fmt.upper()}, qualities: {', '.join(f'{r}p' for r in plan.resolutions)}"
    )

    # 4. Convert (skipped when an earlier attempt already did it)
    if (
        job.encoded
        and job.encoded_fmt == plan.fmt
        and job.encoded_resolutions == plan.resolutions
        and all(f.exists() for f in job.encoded)
    ):
        job.log("Reusing the files converted in the previous attempt")
    else:
        _check_disk(job.work_dir, _estimate_bytes(plan, media.height, duration))
        job.emit("progress", {"step": "encode", "pct": 0})
        job.encoded = _encode(job, cfg, plan)
        job.encoded_fmt = plan.fmt
        job.encoded_resolutions = list(plan.resolutions)
    job.emit("progress", {"step": "encode", "pct": 100})
    job.check_cancel()

    # 5. Thumbnails, then send everything
    thumbs = _thumbnails(job, cfg, duration)
    job.check_cancel()
    _upload(job, cfg, plan, duration, thumbs)


# ---------------------------------------------------------------------------
# Routes – connection
# ---------------------------------------------------------------------------


@app.post("/api/test-connection")
def test_connection(req: TestConnectionRequest) -> dict[str, Any]:
    url = req.server_url.strip()
    url = url if url.endswith("/") else url + "/"
    try:
        with AVideoClient(url, ssl_verify=req.ssl_verify) as client:
            result = client.login(req.username, req.password)
            config = client.get_server_config()
            status = client.get_site_status()
    except Exception as exc:
        logger.warning("test_connection failed: %s", exc)
        problem = classify(exc)
        return {"ok": False, "error": problem.message, "error_info": problem.to_dict()}
    session_id = secrets.token_urlsafe(24)
    session = _Session(
        server_url=url,
        ssl_verify=req.ssl_verify,
        login=result,
        created=time.time(),
        config=config,
        status=status,
    )
    _sessions[session_id] = session
    return _session_info(session_id, session)


@app.post("/api/session")
def check_session(req: SessionRequest) -> dict[str, Any]:
    """Return the connection info of a session still alive in this server process."""
    return _session_info(req.session_id, _get_session(req.session_id))


@app.post("/api/logout")
def logout(req: SessionRequest) -> dict[str, Any]:
    """Forget a site's session (the browser removed the saved site)."""
    _sessions.pop(req.session_id, None)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Version / system
# ---------------------------------------------------------------------------

UPDATE_CHECK_SECONDS = 6 * 3600
_update_cache: dict[str, Any] = {}


@app.get("/api/version")
def version_info() -> dict[str, Any]:
    """Current version and, for the packaged app, whether a newer release exists."""
    result: dict[str, Any] = {
        "version": __version__,
        "update_available": False,
        "latest": None,
        "download_url": updates.DOWNLOAD_PAGE,
    }
    if not updates.is_frozen():
        return result  # running from source: the developer updates with git
    if time.time() - _update_cache.get("checked", 0.0) > UPDATE_CHECK_SECONDS:
        _update_cache["info"] = updates.check_for_update()
        _update_cache["checked"] = time.time()
    info = _update_cache.get("info")
    if info is not None:
        result["latest"] = info.latest
        result["update_available"] = info.update_available
    return result


_gpu: dict[str, Any] = {"status": "idle", "key": "", "label": "", "hardware": False}
_gpu_lock = threading.Lock()


def _detect_gpu() -> None:
    codec = detect_video_codec(Config().ffmpeg_bin)
    _gpu.update(status="done", key=codec.key, label=codec.label, hardware=codec.hardware)


@app.get("/api/system")
def system_info() -> dict[str, Any]:
    """Graphics-card detection (started on the first call) and free disk space."""
    with _gpu_lock:
        if _gpu["status"] == "idle":
            _gpu["status"] = "detecting"
            threading.Thread(target=_detect_gpu, daemon=True, name="gpu-detect").start()
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(OUTPUT_DIR).free
    except OSError:
        free = 0
    return {"version": __version__, "gpu": dict(_gpu), "free_disk_bytes": free}


# ---------------------------------------------------------------------------
# Routes – new jobs
# ---------------------------------------------------------------------------


@app.post("/api/preview")
def preview(req: PreviewRequest) -> dict[str, Any]:
    """Title, picture and length of a link, before adding it."""
    url = req.url.strip()
    try:
        if not is_web_url(url):
            raise LocalEncoderError("invalid_url")
        info = _video_info(url)
        reject_unsupported(info)
    except Exception as exc:
        return {"ok": False, "error": classify(exc).to_dict()}
    return {
        "ok": True,
        "title": str(info.get("title") or ""),
        "thumbnail": str(info.get("thumbnail") or ""),
        "duration_s": int(info.get("duration") or 0),
        "uploader": str(info.get("uploader") or info.get("channel") or ""),
        "source_site": str(info.get("extractor_key") or ""),
    }


@app.post("/api/import")
def start_import(req: ImportRequest) -> dict[str, str]:
    session = _get_session(req.session_id)
    url = req.url.strip()
    if not is_web_url(url):
        raise HTTPException(
            status_code=400, detail=classify(LocalEncoderError("invalid_url")).message
        )
    options = JobOptions(
        categories_id=req.categories_id,
        title=req.title.strip(),
        description=req.description,
        fmt=req.format.lower(),
        resolutions=list(req.resolutions),
        use_gpu=req.use_gpu,
    )
    job = Job("url", url, session, options)
    _enqueue(job)
    return {"job_id": job.id}


@app.post("/api/import-file")
def start_import_file(
    file: UploadFile,
    session_id: str = Form(...),
    categories_id: int = Form(0),
    title: str = Form(""),
    description: str = Form(""),
    format: str = Form("auto"),
    resolution: str = Form(""),  # comma-separated ints e.g. "360,720"
    use_gpu: str = Form("1"),
) -> dict[str, str]:
    """Receive a local video file for encoding and publishing."""
    session = _get_session(session_id)
    job_id = str(uuid.uuid4())
    work_dir = OUTPUT_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    # Never trust the browser-supplied name as a path.
    original_filename = sanitize_filename(Path(file.filename or "video.mp4").name)
    raw_file = work_dir / original_filename
    # Copy to disk in pieces instead of reading the whole video into memory.
    with open(raw_file, "wb") as fh:
        shutil.copyfileobj(file.file, fh, length=1024 * 1024)
    options = JobOptions(
        categories_id=categories_id,
        title=sanitize_filename(title.strip() or Path(original_filename).stem)[:80],
        description=description,
        fmt=format.lower(),
        resolutions=[int(r) for r in resolution.split(",") if r.strip().isdigit()],
        use_gpu=use_gpu not in ("0", "false", ""),
    )
    job = Job("file", original_filename, session, options, work_dir=work_dir, job_id=job_id)
    job.raw_file = raw_file
    job.emit("info", {"file_size_bytes": raw_file.stat().st_size})
    _enqueue(job)
    return {"job_id": job.id}


# ---------------------------------------------------------------------------
# Routes – the queue
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Routes – videos already on this computer (a folder)
# ---------------------------------------------------------------------------


def _folder_error(exc: LocalEncoderError) -> HTTPException:
    return HTTPException(status_code=400, detail=classify(exc).to_dict())


def _active_local_paths(site_url: str = "", username: str = "") -> set[str]:
    """Local videos queued for this destination (an unconnected scan shows all jobs)."""
    with _state_lock:
        return {
            os.path.normcase(str(job.raw_file))
            for job in _jobs.values()
            if job.kind == "local"
            and job.status in ACTIVE
            and job.raw_file is not None
            and (not site_url or job.session.server_url == site_url)
            and (not username or job.session.login.username == username)
        }


@app.post("/api/folders/browse")
def browse_folder(req: FolderRequest) -> dict[str, Any]:
    """Sub-folders of a folder (home when empty), plus the usual starting places."""
    try:
        return folders.browse(req.path)
    except LocalEncoderError as exc:
        raise _folder_error(exc) from exc


@app.post("/api/folders/scan")
def scan_folder(req: ScanRequest) -> dict[str, Any]:
    """The videos in a folder, each marked when it was already sent to *site_url*."""
    try:
        result = folders.scan(req.path, recursive=req.recursive, skip=OUTPUT_DIR)
    except LocalEncoderError as exc:
        raise _folder_error(exc) from exc
    sent = history.sent_items(req.site_url, req.username) if req.site_url else {}
    active = _active_local_paths(req.site_url, req.username)
    videos = []
    for video in result.videos:
        key = os.path.normcase(video.path)
        entry = sent.get(key)
        videos.append(
            {
                "path": video.path,
                "name": video.name,
                "rel": video.rel,
                "size": video.size,
                "mtime": video.mtime,
                "sent": {"videos_id": entry.videos_id, "date": entry.updated_at} if entry else None,
                "queued": key in active,
            }
        )
    return {"path": result.path, "videos": videos, "truncated": result.truncated}


@app.post("/api/import-local")
def start_import_local(req: LocalImportRequest) -> dict[str, Any]:
    """Queue videos that are already on this computer; they are read where they are."""
    session = _get_session(req.session_id)
    active = _active_local_paths(session.server_url, session.login.username)
    job_ids: list[str] = []
    skipped: list[dict[str, Any]] = []
    for raw_path in req.paths:
        try:
            path = folders.video_file(raw_path)
        except LocalEncoderError as exc:
            skipped.append({"path": raw_path, "error": classify(exc).to_dict()})
            continue
        if os.path.normcase(str(path)) in active:
            continue  # already waiting or running
        options = JobOptions(
            categories_id=req.categories_id,
            title=sanitize_filename(path.stem)[:80],
            description=req.description,
            fmt=req.format.lower(),
            resolutions=list(req.resolutions),
            use_gpu=req.use_gpu,
        )
        job = Job("local", path.name, session, options)
        job.raw_file = path
        job.emit("info", {"file_size_bytes": path.stat().st_size})
        _enqueue(job)
        active.add(os.path.normcase(str(path)))
        job_ids.append(job.id)
    return {"job_ids": job_ids, "skipped": skipped}


# ---------------------------------------------------------------------------
# Routes – remembered choices
# ---------------------------------------------------------------------------


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return settings.load()


@app.post("/api/settings")
def save_settings(changes: dict[str, Any]) -> dict[str, Any]:
    """Save the page's choices (unknown keys and wrong types are ignored)."""
    try:
        return settings.save(changes)
    except OSError as exc:
        logger.warning("Could not save the settings: %s", exc)
        raise HTTPException(status_code=500, detail="Could not save the settings.") from exc


def _get_job(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    """Every known job in submission order (the page rebuilds its queue from this)."""
    return [_jobs[jid].summary() for jid in _job_order if jid in _jobs]


@app.get("/api/events")
def queue_events() -> StreamingResponse:
    """SSE for the whole queue: first ``jobs`` (every job's full state), then each change."""
    subscriber = _subscribe()

    def _generate() -> Generator[str, None, None]:
        try:
            yield ": connected\n\n"
            while True:
                try:
                    msg = subscriber.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if msg is None:
                    break
                yield msg
        finally:
            _unsubscribe(subscriber)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    if job.status == "pending":
        job.emit("cancelled", classify(JobCancelled()).to_dict())
    elif job.status == "running":
        job.cancel_event.set()  # the worker stops at the next check and keeps the files
    return {"ok": True, "status": job.status}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, req: RetryRequest) -> dict[str, Any]:
    """Try again, reusing the downloaded and converted files of the earlier attempt."""
    job = _get_job(job_id)
    if job.status in ACTIVE:
        raise HTTPException(status_code=409, detail="This video is already in the queue.")
    if req.session_id:
        session = _get_session(req.session_id)
        if session.server_url != job.session.server_url:
            raise HTTPException(status_code=400, detail="That connection is for another site.")
        if (
            session.login.user_id != job.session.login.user_id
            or session.login.username != job.session.login.username
        ):
            raise HTTPException(
                status_code=400, detail="Connect with the same account that added this video."
            )
        job.session = session
    elif time.time() - job.session.created > SESSION_TTL_SECONDS:
        raise HTTPException(status_code=401, detail="Please connect to your AVideo site again.")
    job.cancel_event = threading.Event()
    job.error = None
    job.result = None
    job.emit("status", {"status": "pending"})
    job.log("Trying again…")
    _enqueue(job)
    return {"ok": True}


def _inside_output_dir(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(OUTPUT_DIR.resolve())
    except OSError:
        return False


@app.post("/api/jobs/{job_id}/remove")
def remove_job(job_id: str, req: RemoveRequest) -> dict[str, Any]:
    job = _get_job(job_id)
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Cancel the video before removing it.")
    if job.status == "pending":
        job.emit("cancelled", classify(JobCancelled()).to_dict())
    if req.delete_files and job.work_dir.exists() and _inside_output_dir(job.work_dir):
        shutil.rmtree(job.work_dir, ignore_errors=True)
    with _state_lock:
        _jobs.pop(job_id, None)
        if job_id in _job_order:
            _job_order.remove(job_id)
        _publish("removed", {"job_id": job_id})
    return {"ok": True}


def _open_path(path: Path) -> None:
    """Show a folder in the system's file manager."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        logger.warning("Could not open %s: %s", path, exc)


@app.post("/api/jobs/{job_id}/open-folder")
def open_job_folder(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    if not job.work_dir.exists() or not _inside_output_dir(job.work_dir):
        raise HTTPException(status_code=404, detail="The files of this video were deleted.")
    _open_path(job.work_dir)
    return {"ok": True, "path": str(job.work_dir)}


# ---------------------------------------------------------------------------
# Report a problem – logs (secrets removed) zipped for a GitHub issue
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = [
    (re.compile(r"_user_hash_[A-Za-z0-9_\-.]+"), "_user_hash_[hidden]"),
    (
        re.compile(
            r"(?i)([\"']?(?:pass|password|encryptedpass|video_id_hash|x-encoder-pass)[\"']?"
            r"\s*[:=]\s*[\"']?)[^\s\"',&}]+"
        ),
        r"\1[hidden]",
    ),
]


def redact(text: str) -> str:
    """Remove passwords and AVideo tokens from log text."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _ffmpeg_version(ffmpeg_bin: str) -> str:
    try:
        out = subprocess.run(
            [ffmpeg_bin, "-version"], capture_output=True, text=True, timeout=10
        ).stdout
        return out.splitlines()[0] if out else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "not found"


def _system_text() -> str:
    cfg = Config()
    return "\n".join(
        [
            f"Local Encoder: {__version__}{' (packaged)' if updates.is_frozen() else ''}",
            f"System: {platform.platform()} ({platform.machine()})",
            f"Python: {platform.python_version()}",
            f"FFmpeg: {_ffmpeg_version(cfg.ffmpeg_bin)}",
            f"Graphics card: {_gpu.get('label') or 'not checked'}",
        ]
    )


def _build_report(job: Job | None) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"local-encoder-report-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    log_file = log_file_path()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("system.txt", _system_text() + "\n")
        if job is not None:
            zf.writestr("video.json", redact(json.dumps(job.snapshot(), indent=2)))
        for candidate in [log_file, *(log_file.with_name(f"{log_file.name}.{i}") for i in (1, 2))]:
            if candidate.exists():
                text = candidate.read_text(encoding="utf-8", errors="replace")
                zf.writestr(candidate.name, redact(text))
    return path


def _issue_url(job: Job | None, file_name: str) -> str:
    problem = (job.error or {}).get("code", "") if job else ""
    title = f"Problem: {problem}" if problem else "Problem report"
    body = "\n".join(
        [
            "**What happened?**",
            "",
            "",
            "**What did you expect?**",
            "",
            "",
            "**Steps to reproduce**",
            "1. ",
            "",
            "---",
            _system_text(),
            "",
            f"Please attach the file `{file_name}` (Local Encoder opened its folder). "
            "It contains the logs without passwords; you can open it to check before attaching.",
        ]
    )
    query = urlencode({"title": title, "body": body})
    return f"https://github.com/{updates.REPOSITORY}/issues/new?{query}"


@app.post("/api/report")
def report_problem(req: ReportRequest) -> dict[str, Any]:
    job = _jobs.get(req.job_id) if req.job_id else None
    path = _build_report(job)
    _open_path(path.parent)
    return {
        "ok": True,
        "file": str(path),
        "file_name": path.name,
        "issue_url": _issue_url(job, path.name),
    }


# ---------------------------------------------------------------------------
# Serve the frontend
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html_file = STATIC_DIR / "index.html"
    if html_file.exists():
        return HTMLResponse(html_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>UI not found</h1><p>Place index.html in local_encoder/static/</p>")
