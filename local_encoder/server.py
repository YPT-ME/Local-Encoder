"""FastAPI web server providing a browser UI for avideo-local-encoder.

Start with:
    avideo-local-encoder serve            # default: http://localhost:8000
    avideo-local-encoder serve --port 9000
"""

from __future__ import annotations

import json
import logging
import queue
import secrets
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from local_encoder import __version__, updates
from local_encoder.avideo_client import AVideoClient, LoginResult
from local_encoder.config import Config, default_work_dir
from local_encoder.downloader import download_video, get_video_info
from local_encoder.encoder import (
    ALLOWED_RESOLUTIONS,
    encode_hls,
    encode_mp4_multi,
    extract_mp3,
    extract_thumbnail_gif,
    extract_thumbnail_jpg,
    extract_thumbnail_webp,
    output_resolution,
)
from local_encoder.logging_setup import configure_logging
from local_encoder.utils import probe_duration, sanitize_filename

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="AVideo Local Encoder", version="0.1.0")

# ---------------------------------------------------------------------------
# In-memory job store + global sequential queue
# ---------------------------------------------------------------------------
_jobs: dict[str, dict[str, Any]] = {}  # job_id → job state
_job_order: list[str] = []  # insertion order for the queue UI
_work_queue: queue.Queue[str] = queue.Queue()  # job_ids pending execution


def _worker() -> None:
    """Single background thread that processes jobs one at a time."""
    while True:
        job_id = _work_queue.get()  # blocks until a job is available
        job = _jobs.get(job_id)
        if job is None:
            continue
        job["status"] = "running"
        job["queue"].put(f"event: status\ndata: {json.dumps({'status': 'running'})}\n\n")
        try:
            job["runner"](job_id)
        except Exception as exc:
            logger.exception("Worker caught unhandled error for %s: %s", job_id, exc)
        finally:
            _work_queue.task_done()


_worker_thread = threading.Thread(target=_worker, daemon=True, name="encode-worker")
_worker_thread.start()


def _enqueue(job_id: str, runner: Callable[[str], None]) -> None:
    """Register a job and push it onto the work queue."""
    msg_queue: queue.Queue[str | None] = queue.Queue()
    _jobs[job_id] = {
        "status": "pending",
        "queue": msg_queue,
        "runner": runner,
        "title": "",
        "thumbnail": "",
        "pct": {"download": 0, "encode": 0, "upload": 0},
    }
    _job_order.append(job_id)
    _work_queue.put(job_id)


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    """Return summary of all known jobs in submission order."""
    result = []
    for jid in _job_order:
        j = _jobs.get(jid)
        if j is None:
            continue
        result.append(
            {
                "job_id": jid,
                "status": j["status"],
                "title": j.get("title", ""),
                "thumbnail": j.get("thumbnail", ""),
                "pct": j.get("pct", {"download": 0, "encode": 0, "upload": 0}),
            }
        )
    return result


STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
    resolutions: list[int] = []  # empty = all allowed


class TestConnectionRequest(BaseModel):
    server_url: str
    username: str
    password: str
    ssl_verify: bool = True


class SessionRequest(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Sessions – the password is used once to log in; later calls reuse the token
# AVideo returned (valid ~1 day), so the browser never stores the password and
# each job does not log in again (AVideo rate-limits encoder logins).
# ---------------------------------------------------------------------------

SESSION_TTL_SECONDS = 12 * 3600

# Where jobs download and encode (one sub-folder per job).
OUTPUT_DIR = default_work_dir()


@dataclass
class _Session:
    server_url: str
    ssl_verify: bool
    login: LoginResult
    created: float


_sessions: dict[str, _Session] = {}


def _get_session(session_id: str) -> _Session:
    session = _sessions.get(session_id)
    if session is None or time.time() - session.created > SESSION_TTL_SECONDS:
        _sessions.pop(session_id, None)
        raise HTTPException(
            status_code=401, detail="Please connect to your AVideo site again (session expired)."
        )
    return session


def _session_info(session_id: str, session: _Session) -> dict[str, Any]:
    categories = session.login.categories
    if not categories:
        with AVideoClient(session.server_url, ssl_verify=session.ssl_verify) as client:
            categories = client.get_categories()
    return {
        "ok": True,
        "session_id": session_id,
        "name": session.login.name or session.login.username,
        "logo_url": session.server_url + "videos/userPhoto/logo.png",
        "categories": categories,
    }


# ---------------------------------------------------------------------------
# Routes – connection test & categories
# ---------------------------------------------------------------------------


@app.post("/api/test-connection")
def test_connection(req: TestConnectionRequest) -> dict[str, Any]:
    url = req.server_url if req.server_url.endswith("/") else req.server_url + "/"
    try:
        with AVideoClient(url, ssl_verify=req.ssl_verify) as client:
            result = client.login(req.username, req.password)
    except Exception as exc:
        logger.warning("test_connection failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    session_id = secrets.token_urlsafe(24)
    session = _Session(server_url=url, ssl_verify=req.ssl_verify, login=result, created=time.time())
    _sessions[session_id] = session
    return _session_info(session_id, session)


# ---------------------------------------------------------------------------
# Version / update notice
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


@app.post("/api/session")
def check_session(req: SessionRequest) -> dict[str, Any]:
    """Return the connection info of a session still alive in this server process."""
    return _session_info(req.session_id, _get_session(req.session_id))


# ---------------------------------------------------------------------------
# Import job
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shared encode+upload pipeline (used by both URL and file-upload jobs)
# ---------------------------------------------------------------------------


def _run_pipeline(
    emit: Callable[[str, dict[str, Any]], None],
    raw_file: Path,
    work_dir: Path,
    files_to_clean: list[Path],
    session: _Session,
    categories_id: int,
    video_title: str,
    video_description: str,
    duration: float,
    fmt: str,
    resolutions: list[int],
    cfg: Config,
    source_url: str = "",
) -> None:
    """Encode and upload a local raw_file. Called from both import endpoints."""
    server_url = session.server_url
    ssl_verify = session.ssl_verify
    seek = min(duration * 0.25, 600.0) if duration > 0 else 5.0

    # Server config
    emit("log", {"msg": "Fetching server config…"})
    with AVideoClient(server_url, ssl_verify=ssl_verify) as _c:
        server_cfg = _c.get_server_config()
    emit(
        "log",
        {
            "msg": f"Server: auto_mp3={server_cfg.auto_convert_to_mp3}, "
            f"disable_hls={server_cfg.disable_hls}"
        },
    )

    # Resolve format
    if fmt == "auto":
        fmt = "hls" if not server_cfg.disable_hls else "mp4"
        emit("log", {"msg": f"Auto format → {fmt}"})

    # Resolve target resolutions
    res_cap: int | None = None
    if resolutions:
        # Use explicitly chosen list, filtered to what we support
        target_resolutions = sorted(r for r in resolutions if r in ALLOWED_RESOLUTIONS) or [
            ALLOWED_RESOLUTIONS[0]
        ]
        res_cap = max(target_resolutions)
    elif server_cfg.single_resolution > 0:
        res_cap = server_cfg.single_resolution
        target_resolutions = [r for r in ALLOWED_RESOLUTIONS if r <= res_cap] or [
            ALLOWED_RESOLUTIONS[0]
        ]
    else:
        target_resolutions = list(ALLOWED_RESOLUTIONS)
        res_cap = max(ALLOWED_RESOLUTIONS)

    res_label = ", ".join(f"{r}p" for r in target_resolutions)
    emit("info", {"encoding_format": fmt.upper(), "encoding_resolutions": res_label})

    # Encode
    emit("progress", {"step": "encode", "pct": 0, "msg": "Encoding…"})

    def on_encode(current: int, total: int) -> None:
        pct = int(current * 100 / total) if total else 0
        emit("progress", {"step": "encode", "pct": pct, "msg": f"Encoding {pct}%"})

    encoded_files: list[Path] = []
    upload_resolution: int | None = res_cap
    encoded_duration = duration

    if fmt == "mp4":
        mp4_files = encode_mp4_multi(
            input_path=raw_file,
            output_dir=work_dir,
            resolutions=target_resolutions,
            ffmpeg_bin=cfg.ffmpeg_bin,
            ffprobe_bin=cfg.ffprobe_bin,
            progress_callback=on_encode,
        )
        files_to_clean.extend(mp4_files)
        encoded_files.extend(mp4_files)
        upload_resolution = max(
            (r for r in (output_resolution(f) for f in mp4_files) if r is not None),
            default=res_cap or ALLOWED_RESOLUTIONS[0],
        )
        encoded_duration = probe_duration(mp4_files[-1], cfg.ffprobe_bin) if mp4_files else duration
        emit("log", {"msg": f"Encoded {len(mp4_files)} MP4 file(s)"})
    else:  # hls
        hls_zip = encode_hls(
            input_path=raw_file,
            output_dir=work_dir,
            resolutions=target_resolutions,
            ffmpeg_bin=cfg.ffmpeg_bin,
            ffprobe_bin=cfg.ffprobe_bin,
            progress_callback=on_encode,
        )
        files_to_clean.append(hls_zip)
        encoded_files = [hls_zip]
        upload_resolution = None  # the HLS zip is stored without a resolution
        emit("log", {"msg": f"HLS ZIP: {hls_zip.name}"})

    emit("progress", {"step": "encode", "pct": 100, "msg": "Encode complete"})

    # Thumbnails
    filename_stem = raw_file.stem
    emit("log", {"msg": "Generating thumbnails…"})
    jpg_file = work_dir / f"{filename_stem}.jpg"
    gif_file = work_dir / f"{filename_stem}.gif"
    webp_file = work_dir / f"{filename_stem}.webp"
    files_to_clean.extend([jpg_file, gif_file, webp_file])
    for fn, label in [
        (lambda: extract_thumbnail_jpg(raw_file, jpg_file, seek, cfg.ffmpeg_bin), "JPG"),
        (lambda: extract_thumbnail_gif(raw_file, gif_file, seek, 3.0, cfg.ffmpeg_bin), "GIF"),
        (lambda: extract_thumbnail_webp(raw_file, webp_file, seek, 3.0, cfg.ffmpeg_bin), "WebP"),
    ]:
        try:
            fn()  # type: ignore[no-untyped-call]
        except Exception as exc:
            emit("log", {"msg": f"Thumbnail {label} skipped: {exc}"})

    # Upload
    emit("progress", {"step": "upload", "pct": 0, "msg": "Uploading…"})
    with AVideoClient(server_url, ssl_verify=ssl_verify) as client:
        client.use_login(session.login)
        emit("log", {"msg": f"Uploading as {session.login.name or session.login.username}"})

        reg = client.register_video(
            title=video_title,
            format_ext="zip" if fmt == "hls" else "mp4",
            resolution=upload_resolution,
            duration=encoded_duration or duration,
            categories_id=categories_id,
            description=video_description,
            download_url=source_url,
        )
        emit("log", {"msg": f"Registered: videos_id={reg.videos_id}"})

        # From here on the site has a video record: tell it when anything fails,
        # otherwise the video stays in "encoding" forever (Encoder.php does the same).
        try:
            total_files = len(encoded_files)
            for idx, enc_file in enumerate(encoded_files):
                file_size = enc_file.stat().st_size
                file_ext = "zip" if enc_file.suffix == ".zip" else "mp4"

                def on_upload(fname: str, sent: int, total: int, _idx: int = idx) -> None:
                    base_pct = _idx * 100 // total_files
                    file_pct = int(sent * 100 / total) if total else 0
                    overall = base_pct + file_pct // total_files
                    emit(
                        "progress",
                        {"step": "upload", "pct": overall, "msg": f"Uploading {fname} {file_pct}%"},
                    )

                client.upload_file(
                    file_path=enc_file,
                    videos_id=reg.videos_id,
                    video_id_hash=reg.video_id_hash,
                    title=video_title,
                    format_ext=file_ext,
                    resolution=output_resolution(enc_file),
                    duration=encoded_duration or duration,
                    categories_id=categories_id,
                    description=video_description,
                    download_url=source_url,
                    progress_callback=on_upload,
                )
                emit("log", {"msg": f"Uploaded {enc_file.name} ({file_size // 1_048_576} MiB)"})

            # Auto MP3
            if server_cfg.auto_convert_to_mp3 and fmt != "hls":
                mp3_file = work_dir / f"{filename_stem}.mp3"
                files_to_clean.append(mp3_file)
                try:
                    emit("log", {"msg": "Extracting MP3…"})
                    extract_mp3(raw_file, mp3_file, ffmpeg_bin=cfg.ffmpeg_bin)
                    client.upload_file(
                        file_path=mp3_file,
                        videos_id=reg.videos_id,
                        video_id_hash=reg.video_id_hash,
                        title=video_title,
                        format_ext="mp3",
                        resolution=None,
                        duration=encoded_duration or duration,
                        categories_id=categories_id,
                        description=video_description,
                    )
                    emit("log", {"msg": "MP3 uploaded"})
                except Exception as exc:
                    emit("log", {"msg": f"MP3 skipped: {exc}"})

            # Thumbnails upload
            client.upload_images(
                videos_id=reg.videos_id,
                video_id_hash=reg.video_id_hash,
                duration=encoded_duration or duration,
                jpg_path=jpg_file if jpg_file.exists() else None,
                gif_path=gif_file if gif_file.exists() else None,
                webp_path=webp_file if webp_file.exists() else None,
            )

            client.notify_done(reg.videos_id, reg.video_id_hash)
        except BaseException:
            client.notify_failed(reg.videos_id, reg.video_id_hash)
            raise

    emit("progress", {"step": "upload", "pct": 100, "msg": "Upload complete"})
    emit("done", {"videos_id": reg.videos_id, "url": f"{server_url}video/{reg.videos_id}"})


def _finish_job(
    job: dict[str, Any],
    emit: Callable[[str, Any], None],
    files_to_clean: list[Path],
    work_dir: Path,
) -> None:
    """Delete the job's files after success; keep them after a failure so no work is lost."""
    if job["status"] != "done":
        if any(f.exists() for f in files_to_clean):
            emit("log", {"msg": f"Files kept for a new attempt in: {work_dir.resolve()}"})
        return
    for f in files_to_clean:
        try:
            if f.exists():
                f.unlink()
        except OSError:
            pass
    shutil.rmtree(work_dir, ignore_errors=True)


def _make_emit(job: dict[str, Any]) -> Callable[[str, Any], None]:
    msg_queue: queue.Queue[str | None] = job["queue"]

    def emit(event: str, data: Any) -> None:
        if event == "info":
            if data.get("title"):
                job["title"] = data["title"]
            if data.get("thumbnail"):
                job["thumbnail"] = data["thumbnail"]
        if event == "progress":
            step = data.get("step")
            if step:
                job["pct"][step] = data.get("pct", 0)
        msg_queue.put(f"event: {event}\ndata: {json.dumps(data)}\n\n")

    return emit


# ---------------------------------------------------------------------------
# Import job – URL
# ---------------------------------------------------------------------------


@app.post("/api/import")
def start_import(req: ImportRequest) -> dict[str, str]:
    session = _get_session(req.session_id)
    job_id = str(uuid.uuid4())

    def runner(jid: str) -> None:
        job = _jobs[jid]
        emit = _make_emit(job)
        work_dir = OUTPUT_DIR / jid
        files_to_clean: list[Path] = []
        try:
            cfg = Config(
                server_url=session.server_url,
                categories_id=req.categories_id,
                ssl_verify=session.ssl_verify,
            )
            work_dir.mkdir(parents=True, exist_ok=True)

            # Step 1 – Metadata
            emit("log", {"msg": f"Fetching metadata: {req.url}"})
            try:
                info = get_video_info(req.url)
            except Exception as exc:
                info = {}
                emit("log", {"msg": f"Metadata warning: {exc}"})

            video_title = req.title or sanitize_filename(info.get("title") or "video")
            video_description = req.description or info.get("description") or ""
            meta_duration = float(info.get("duration") or 0)
            filename_stem = sanitize_filename(video_title)[:80]
            emit("log", {"msg": f"Title: {video_title}"})
            uploader = info.get("uploader") or info.get("channel") or ""
            emit(
                "info",
                {
                    "title": video_title,
                    "uploader": uploader,
                    "duration_s": int(meta_duration),
                    "thumbnail": info.get("thumbnail") or "",
                },
            )

            # Step 2 – Download
            emit("progress", {"step": "download", "pct": 0, "msg": "Downloading…"})

            def on_download(status: str, downloaded: int, total: int) -> None:
                pct = int(downloaded * 100 / total) if total else 0
                emit("progress", {"step": "download", "pct": pct, "msg": f"Downloading {pct}%"})

            raw_file = download_video(
                url=req.url,
                output_dir=work_dir,
                filename_stem=filename_stem,
                progress_callback=on_download,
            )
            files_to_clean.append(raw_file)
            file_size_bytes = raw_file.stat().st_size
            emit("log", {"msg": f"Downloaded: {raw_file.name}"})
            emit("progress", {"step": "download", "pct": 100, "msg": "Download complete"})

            duration = probe_duration(raw_file, cfg.ffprobe_bin) or meta_duration
            emit(
                "info",
                {
                    "title": video_title,
                    "uploader": uploader,
                    "duration_s": int(duration),
                    "file_size_bytes": file_size_bytes,
                    "thumbnail": info.get("thumbnail") or "",
                },
            )

            _run_pipeline(
                emit=emit,
                raw_file=raw_file,
                work_dir=work_dir,
                files_to_clean=files_to_clean,
                session=session,
                categories_id=req.categories_id,
                video_title=video_title,
                video_description=video_description,
                duration=duration,
                fmt=req.format.lower(),
                resolutions=req.resolutions,
                cfg=cfg,
                source_url=req.url,
            )
            job["status"] = "done"

        except Exception as exc:
            logger.exception("Import job %s failed", jid)
            emit("error", {"msg": str(exc)})
            job["status"] = "error"
        finally:
            _finish_job(job, emit, files_to_clean, work_dir)
            job["queue"].put(None)

    _enqueue(job_id, runner)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Import job – local file upload
# ---------------------------------------------------------------------------


@app.post("/api/import-file")
def start_import_file(
    file: UploadFile,
    session_id: str = Form(...),
    categories_id: int = Form(0),
    title: str = Form(""),
    description: str = Form(""),
    format: str = Form("auto"),
    resolution: str = Form(""),  # comma-separated ints e.g. "360,720"
) -> dict[str, str]:
    """Upload a local video file for encoding and publishing."""
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
    file_size_bytes = raw_file.stat().st_size

    def runner(jid: str) -> None:
        job = _jobs[jid]
        emit = _make_emit(job)
        files_to_clean: list[Path] = [raw_file]
        try:
            cfg = Config(
                server_url=session.server_url,
                categories_id=categories_id,
                ssl_verify=session.ssl_verify,
            )
            emit(
                "progress",
                {"step": "download", "pct": 100, "msg": f"File received: {original_filename}"},
            )
            emit("log", {"msg": f"File: {original_filename} ({file_size_bytes // 1_048_576} MiB)"})

            video_title = sanitize_filename(title or Path(original_filename).stem)[:80]
            video_description = description
            duration = probe_duration(raw_file, cfg.ffprobe_bin) or 0.0
            emit("log", {"msg": f"Title: {video_title}, duration: {duration:.1f}s"})
            emit(
                "info",
                {
                    "title": video_title,
                    "uploader": "",
                    "duration_s": int(duration),
                    "file_size_bytes": file_size_bytes,
                    "thumbnail": "",
                },
            )

            _run_pipeline(
                emit=emit,
                raw_file=raw_file,
                work_dir=work_dir,
                files_to_clean=files_to_clean,
                session=session,
                categories_id=categories_id,
                video_title=video_title,
                video_description=video_description,
                duration=duration,
                fmt=format.lower(),
                resolutions=[int(r) for r in resolution.split(",") if r.strip().isdigit()]
                if resolution
                else [],
                cfg=cfg,
            )
            job["status"] = "done"

        except Exception as exc:
            logger.exception("File import job %s failed", jid)
            emit("error", {"msg": str(exc)})
            job["status"] = "error"
        finally:
            _finish_job(job, emit, files_to_clean, work_dir)
            job["queue"].put(None)

    _enqueue(job_id, runner)
    return {"job_id": job_id}


@app.get("/api/import/{job_id}/progress")
def job_progress(job_id: str) -> StreamingResponse:
    """SSE stream for job progress."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    msg_queue = _jobs[job_id]["queue"]

    def _generate() -> Generator[str, None, None]:
        yield ": connected\n\n"
        # Send current status immediately so the client knows if job is pending
        current_status = _jobs[job_id].get("status", "pending")
        yield f"event: status\ndata: {json.dumps({'status': current_status})}\n\n"
        while True:
            try:
                msg = msg_queue.get(timeout=30)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if msg is None:
                break
            yield msg

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Serve the frontend
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html_file = STATIC_DIR / "index.html"
    if html_file.exists():
        return HTMLResponse(html_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>UI not found</h1><p>Place index.html in local_encoder/static/</p>")
