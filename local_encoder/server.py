"""FastAPI web server providing a browser UI for avideo-local-encoder.

Start with:
    avideo-local-encoder serve            # default: http://localhost:8000
    avideo-local-encoder serve --port 9000
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from local_encoder.avideo_client import AVideoAPIError, AVideoClient
from local_encoder.config import Config
from local_encoder.downloader import download_video, get_video_info
from local_encoder.encoder import (
    ALLOWED_RESOLUTIONS,
    encode_hls,
    encode_mp4_multi,
    extract_mp3,
    extract_thumbnail_gif,
    extract_thumbnail_jpg,
    extract_thumbnail_webp,
)
from local_encoder.utils import probe_duration, sanitize_filename

logger = logging.getLogger(__name__)

app = FastAPI(title="AVideo Local Encoder", version="0.1.0")

# ---------------------------------------------------------------------------
# In-memory job store + global sequential queue
# ---------------------------------------------------------------------------
_jobs: dict[str, dict[str, Any]] = {}          # job_id → job state
_job_order: list[str] = []                      # insertion order for the queue UI
_work_queue: queue.Queue[str] = queue.Queue()   # job_ids pending execution


def _worker() -> None:
    """Single background thread that processes jobs one at a time."""
    while True:
        job_id = _work_queue.get()  # blocks until a job is available
        job = _jobs.get(job_id)
        if job is None:
            continue
        job["status"] = "running"
        try:
            job["runner"](job_id)
        except Exception as exc:
            logger.exception("Worker caught unhandled error for %s: %s", job_id, exc)
        finally:
            _work_queue.task_done()


_worker_thread = threading.Thread(target=_worker, daemon=True, name="encode-worker")
_worker_thread.start()


def _enqueue(job_id: str, runner) -> None:
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
        result.append({
            "job_id": jid,
            "status": j["status"],
            "title": j.get("title", ""),
            "thumbnail": j.get("thumbnail", ""),
            "pct": j.get("pct", {"download": 0, "encode": 0, "upload": 0}),
        })
    return result

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ImportRequest(BaseModel):
    url: str
    server_url: str
    username: str
    password: str
    categories_id: int = 0
    title: str = ""
    description: str = ""
    format: str = "auto"           # "auto" | "mp4" | "hls"
    resolutions: list[int] = []     # empty = all allowed
    ssl_verify: bool = True


class TestConnectionRequest(BaseModel):
    server_url: str
    username: str
    password: str
    ssl_verify: bool = True


# ---------------------------------------------------------------------------
# Routes – connection test & categories
# ---------------------------------------------------------------------------

@app.post("/api/test-connection")
def test_connection(req: TestConnectionRequest) -> dict[str, Any]:
    url = req.server_url if req.server_url.endswith("/") else req.server_url + "/"
    try:
        with AVideoClient(url, ssl_verify=req.ssl_verify) as client:
            result = client.login(req.username, req.password)
        logo_url = url + "videos/userPhoto/logo.png"
        return {"ok": True, "name": result.name or result.username, "logo_url": logo_url}
    except AVideoAPIError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/categories")
def list_categories(
    server_url: str,
    username: str,
    password: str,
    ssl_verify: bool = True,
) -> list[dict[str, Any]]:
    url = server_url if server_url.endswith("/") else server_url + "/"
    try:
        with AVideoClient(url, ssl_verify=ssl_verify) as client:
            client.login(username, password)
            cats = client.get_categories()
            return cats
    except Exception as exc:
        logger.warning("list_categories failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Import job
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shared encode+upload pipeline (used by both URL and file-upload jobs)
# ---------------------------------------------------------------------------

def _run_pipeline(
    emit,
    raw_file: Path,
    work_dir: Path,
    files_to_clean: list,
    server_url: str,
    username: str,
    password: str,
    categories_id: int,
    ssl_verify: bool,
    video_title: str,
    video_description: str,
    duration: float,
    fmt: str,
    resolutions: list[int],
    cfg,
) -> None:
    """Encode and upload a local raw_file. Called from both import endpoints."""
    seek = min(duration * 0.25, 600.0) if duration > 0 else 5.0

    # Server config
    emit("log", {"msg": "Fetching server config…"})
    with AVideoClient(server_url, ssl_verify=ssl_verify) as _c:
        server_cfg = _c.get_server_config()
    emit("log", {"msg": f"Server: auto_mp3={server_cfg.auto_convert_to_mp3}, "
                         f"disable_hls={server_cfg.disable_hls}"})

    # Resolve format
    if fmt == "auto":
        fmt = "hls" if not server_cfg.disable_hls else "mp4"
        emit("log", {"msg": f"Auto format → {fmt}"})

    # Resolve target resolutions
    res_cap: int | None = None
    if resolutions:
        # Use explicitly chosen list, filtered to what we support
        target_resolutions = sorted(r for r in resolutions if r in ALLOWED_RESOLUTIONS) or [ALLOWED_RESOLUTIONS[0]]
        res_cap = max(target_resolutions)
    elif server_cfg.single_resolution > 0:
        res_cap = server_cfg.single_resolution
        target_resolutions = [r for r in ALLOWED_RESOLUTIONS if r <= res_cap] or [ALLOWED_RESOLUTIONS[0]]
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
    upload_resolution = res_cap
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
            (int(f.stem.rsplit("_", 1)[-1].rstrip("p")) for f in mp4_files),
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
            fn()  # type: ignore[operator]
        except Exception as exc:
            emit("log", {"msg": f"Thumbnail {label} skipped: {exc}"})

    # Upload
    emit("progress", {"step": "upload", "pct": 0, "msg": "Uploading…"})
    with AVideoClient(server_url, ssl_verify=ssl_verify) as client:
        login_result = client.login(username, password)
        emit("log", {"msg": f"Logged in as {login_result.name or login_result.username}"})

        reg = client.register_video(
            title=video_title,
            format_ext="zip" if fmt == "hls" else "mp4",
            resolution=upload_resolution,
            duration=encoded_duration or duration,
            categories_id=categories_id,
            description=video_description,
        )
        emit("log", {"msg": f"Registered: videos_id={reg.videos_id}"})

        total_files = len(encoded_files)
        for idx, enc_file in enumerate(encoded_files):
            file_size = enc_file.stat().st_size
            try:
                file_res = int(enc_file.stem.rsplit("_", 1)[-1].rstrip("p"))
            except ValueError:
                file_res = upload_resolution
            file_ext = "zip" if enc_file.suffix == ".zip" else "mp4"

            def on_upload(fname: str, sent: int, total: int, _idx=idx) -> None:
                base_pct = _idx * 100 // total_files
                file_pct = int(sent * 100 / total) if total else 0
                overall = base_pct + file_pct // total_files
                emit("progress", {"step": "upload", "pct": overall,
                                  "msg": f"Uploading {fname} {file_pct}%"})

            client.upload_file(
                file_path=enc_file,
                videos_id=reg.videos_id,
                video_id_hash=reg.video_id_hash,
                title=video_title,
                format_ext=file_ext,
                resolution=file_res,
                duration=encoded_duration or duration,
                categories_id=categories_id,
                description=video_description,
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
                    resolution=0,
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

    emit("progress", {"step": "upload", "pct": 100, "msg": "Upload complete"})
    emit("done", {"videos_id": reg.videos_id, "url": f"{server_url}video/{reg.videos_id}"})


# ---------------------------------------------------------------------------
# Import job – URL
# ---------------------------------------------------------------------------

@app.post("/api/import")
def start_import(req: ImportRequest) -> dict[str, str]:
    job_id = str(uuid.uuid4())

    def runner(jid: str) -> None:
        job = _jobs[jid]
        msg_queue = job["queue"]

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

        files_to_clean: list[Path] = []
        try:
            server_url = req.server_url if req.server_url.endswith("/") else req.server_url + "/"
            cfg = Config(
                server_url=server_url,
                username=req.username,
                password=req.password,
                categories_id=req.categories_id,
                ssl_verify=req.ssl_verify,
            )
            work_dir = Path("output") / jid
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
            emit("info", {
                "title": video_title,
                "uploader": uploader,
                "duration_s": int(meta_duration),
                "thumbnail": info.get("thumbnail") or "",
            })

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
            emit("info", {
                "title": video_title,
                "uploader": uploader,
                "duration_s": int(duration),
                "file_size_bytes": file_size_bytes,
                "thumbnail": info.get("thumbnail") or "",
            })

            _run_pipeline(
                emit=emit,
                raw_file=raw_file,
                work_dir=work_dir,
                files_to_clean=files_to_clean,
                server_url=server_url,
                username=req.username,
                password=req.password,
                categories_id=req.categories_id,
                ssl_verify=req.ssl_verify,
                video_title=video_title,
                video_description=video_description,
                duration=duration,
                fmt=req.format.lower(),
                resolutions=req.resolutions,
                cfg=cfg,
            )
            job["status"] = "done"

        except Exception as exc:
            emit("error", {"msg": str(exc)})
            job["status"] = "error"
        finally:
            for f in files_to_clean:
                try:
                    if f.exists():
                        f.unlink()
                except OSError:
                    pass
            msg_queue.put(None)

    _enqueue(job_id, runner)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Import job – local file upload
# ---------------------------------------------------------------------------

@app.post("/api/import-file")
async def start_import_file(
    file: UploadFile,
    server_url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    categories_id: int = Form(0),
    title: str = Form(""),
    description: str = Form(""),
    format: str = Form("auto"),
    resolution: str = Form(""),   # comma-separated ints e.g. "360,720"
    ssl_verify: bool = Form(True),
) -> dict[str, str]:
    """Upload a local video file for encoding and publishing."""
    job_id = str(uuid.uuid4())
    raw_bytes = await file.read()
    original_filename = file.filename or "video.mp4"

    def runner(jid: str) -> None:
        job = _jobs[jid]
        msg_queue = job["queue"]

        def emit(event: str, data: Any) -> None:
            if event == "info":
                if data.get("title"):
                    job["title"] = data["title"]
            if event == "progress":
                step = data.get("step")
                if step:
                    job["pct"][step] = data.get("pct", 0)
            msg_queue.put(f"event: {event}\ndata: {json.dumps(data)}\n\n")

        files_to_clean: list[Path] = []
        try:
            srv = server_url if server_url.endswith("/") else server_url + "/"
            cfg = Config(
                server_url=srv,
                username=username,
                password=password,
                categories_id=categories_id,
                ssl_verify=ssl_verify,
            )
            work_dir = Path("output") / jid
            work_dir.mkdir(parents=True, exist_ok=True)

            raw_file = work_dir / original_filename
            raw_file.write_bytes(raw_bytes)
            files_to_clean.append(raw_file)
            file_size_bytes = len(raw_bytes)
            emit("progress", {"step": "download", "pct": 100, "msg": f"File received: {original_filename}"})
            emit("log", {"msg": f"File: {original_filename} ({file_size_bytes // 1_048_576} MiB)"})

            video_title = sanitize_filename(title or Path(original_filename).stem)[:80]
            video_description = description
            duration = probe_duration(raw_file, cfg.ffprobe_bin) or 0.0
            emit("log", {"msg": f"Title: {video_title}, duration: {duration:.1f}s"})
            emit("info", {
                "title": video_title,
                "uploader": "",
                "duration_s": int(duration),
                "file_size_bytes": file_size_bytes,
                "thumbnail": "",
            })

            _run_pipeline(
                emit=emit,
                raw_file=raw_file,
                work_dir=work_dir,
                files_to_clean=files_to_clean,
                server_url=srv,
                username=username,
                password=password,
                categories_id=categories_id,
                ssl_verify=ssl_verify,
                video_title=video_title,
                video_description=video_description,
                duration=duration,
                fmt=format.lower(),
                resolutions=[int(r) for r in resolution.split(',') if r.strip().isdigit()] if resolution else [],
                cfg=cfg,
            )
            job["status"] = "done"

        except Exception as exc:
            emit("error", {"msg": str(exc)})
            job["status"] = "error"
        finally:
            for f in files_to_clean:
                try:
                    if f.exists():
                        f.unlink()
                except OSError:
                    pass
            msg_queue.put(None)

    _enqueue(job_id, runner)
    return {"job_id": job_id}


@app.get("/api/import/{job_id}/progress")
def job_progress(job_id: str) -> StreamingResponse:
    """SSE stream for job progress."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    msg_queue = _jobs[job_id]["queue"]

    def _generate():
        yield ": connected\n\n"
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
