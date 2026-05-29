"""CLI entry-point for avideo-local-encoder.

Usage:
  avideo-local-encoder import "https://youtu.be/..." [OPTIONS]

All options can also be set via environment variables or a .env file
(see .env.example for the full list).
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer

from local_encoder import __version__
from local_encoder.avideo_client import AVideoAPIError, AVideoClient
from local_encoder.config import load_config
from local_encoder.downloader import download_video, get_video_info
from local_encoder.encoder import (
    ALLOWED_RESOLUTIONS,
    encode_hls,
    encode_mp4_multi,
    extract_mp3,
    extract_thumbnail_gif,
    extract_thumbnail_jpg,
    extract_thumbnail_webp,
    nearest_resolution,
)
from local_encoder.progress import ProgressReporter, console
from local_encoder.utils import probe_duration, sanitize_filename

app = typer.Typer(
    name="avideo-local-encoder",
    help="Download, encode, and upload a video to an AVideo server.",
    add_completion=False,
    rich_markup_mode="rich",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"avideo-local-encoder {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    _version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Print version and exit.",
        ),
    ] = None,
) -> None:
    """AVideo Local Encoder – download, encode, and upload videos."""


@app.command("import")
def import_video(
    video_url: Annotated[str, typer.Argument(help="URL of the video to download and import.")],
    # Server / auth
    server: Annotated[
        str | None,
        typer.Option("--server", "-s", help="AVideo server URL (overrides AVIDEO_SERVER_URL)."),
    ] = None,
    user: Annotated[
        str | None,
        typer.Option("--user", "-u", help="AVideo username (overrides AVIDEO_USERNAME)."),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            "-p",
            help="AVideo password (overrides AVIDEO_PASSWORD).",
            hide_input=True,
        ),
    ] = None,
    # Encoding
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help=(
                "Output format: 'auto' (use server config), 'mp4' (multi-resolution MP4), "
                "or 'hls' (multi-resolution HLS ZIP with AES-128 encryption). "
                "Default: 'auto'."
            ),
        ),
    ] = "auto",
    resolution: Annotated[
        int,
        typer.Option(
            "--resolution",
            "-r",
            help=(
                f"Maximum height in pixels for MP4/HLS. Allowed: {ALLOWED_RESOLUTIONS}. "
                f"All eligible resolutions up to this value are encoded. "
                f"0 = encode all resolutions ≤ source height."
            ),
        ),
    ] = 0,
    # Metadata
    title: Annotated[
        str | None,
        typer.Option("--title", "-t", help="Video title (auto-detected from yt-dlp if omitted)."),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="Video description."),
    ] = None,
    categories_id: Annotated[
        int | None,
        typer.Option("--categories-id", "-c", help="AVideo category ID."),
    ] = None,
    # Files / directories
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", "-o", help="Directory for downloaded/encoded files."),
    ] = None,
    keep_files: Annotated[
        bool,
        typer.Option("--keep-files/--no-keep-files", "-k", help="Keep temp files after upload."),
    ] = False,
    # TLS
    ssl_no_verify: Annotated[
        bool,
        typer.Option(
            "--ssl-no-verify",
            help="Disable SSL certificate verification (for self-signed certs).",
        ),
    ] = False,
    # Misc
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Path to a .env configuration file."),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option("--debug/--no-debug", help="Enable verbose debug logging."),
    ] = False,
) -> None:
    """Download a video from *VIDEO_URL*, encode it, and upload it to AVideo."""

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # ------------------------------------------------------------------
    # Load config, then override with CLI flags
    # ------------------------------------------------------------------
    cfg = load_config(env_file)
    if server:
        cfg.server_url = server
        cfg.normalize_server_url()
    if user:
        cfg.username = user
    if password:
        cfg.password = password
    if output_dir:
        cfg.output_dir = output_dir
    if ssl_no_verify:
        cfg.ssl_verify = False
    if keep_files:
        cfg.keep_files = True
    if categories_id is not None:
        cfg.categories_id = categories_id

    try:
        cfg.validate()
    except ValueError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(1) from exc

    # Snap to the nearest supported resolution (only used for single-res fallback)
    actual_resolution = nearest_resolution(resolution) if resolution > 0 else 0
    if resolution > 0 and actual_resolution != resolution:
        console.print(
            f"  [yellow]⚠[/yellow] Resolution {resolution}p is not in the allowed list; "
            f"using {actual_resolution}p as the maximum."
        )

    # ------------------------------------------------------------------
    # Working directory
    # ------------------------------------------------------------------
    work_dir = cfg.output_dir
    work_dir.mkdir(parents=True, exist_ok=True)

    with ProgressReporter(verbose=debug) as rpt:
        files_to_clean: list[Path] = []

        try:
            # ----------------------------------------------------------
            # Step 1 – Fetch metadata (title, duration) without download
            # ----------------------------------------------------------
            rpt.info(f"Fetching metadata for: {video_url}")
            try:
                info = get_video_info(video_url)
            except Exception as exc:
                rpt.warning(f"Could not fetch metadata ({exc}); continuing anyway.")
                info = {}

            video_title = title or sanitize_filename(info.get("title") or "video")
            video_description = description or info.get("description") or ""
            meta_duration = float(info.get("duration") or 0)
            filename_stem = sanitize_filename(video_title)[:80]

            rpt.info(f"Title: {video_title}")

            # ----------------------------------------------------------
            # Step 2 – Download
            # ----------------------------------------------------------
            rpt.begin_download(video_url)
            raw_file = download_video(
                url=video_url,
                output_dir=work_dir,
                filename_stem=filename_stem,
                progress_callback=rpt.on_download,
            )
            files_to_clean.append(raw_file)
            rpt.success(f"Downloaded → {raw_file.name}")

            # Probe actual duration from the downloaded file
            duration = probe_duration(raw_file, cfg.ffprobe_bin) or meta_duration
            if duration == 0:
                rpt.warning("Could not determine video duration; using 0.")

            # Thumbnail seek point: 25 % into the video, capped at 600 s
            seek = min(duration * 0.25, 600.0) if duration > 0 else 5.0

            # ----------------------------------------------------------
            # Step 2b – Fetch server config (determines format + resolution cap)
            # ----------------------------------------------------------
            rpt.info(f"Fetching server config from {cfg.server_url}…")
            with AVideoClient(cfg.server_url, ssl_verify=cfg.ssl_verify) as _cfg_client:
                server_cfg = _cfg_client.get_server_config()
            rpt.info(
                f"Server config: auto_mp3={server_cfg.auto_convert_to_mp3}, "
                f"single_res={server_cfg.single_resolution}, "
                f"disable_hls={server_cfg.disable_hls}, disable_mp4={server_cfg.disable_mp4}"
            )

            # ----------------------------------------------------------
            # Step 3 – Encode
            # ----------------------------------------------------------
            fmt = format.lower()
            if fmt not in ("auto", "mp4", "hls"):
                console.print(f"[red]Unknown format '{format}'; use 'auto', 'mp4', or 'hls'.[/red]")
                raise typer.Exit(1)

            # Resolve 'auto' format using server config
            if fmt == "auto":
                fmt = "hls" if not server_cfg.disable_hls else "mp4"
                rpt.info(f"Auto format resolved to: {fmt}")

            # Resolve resolution cap: explicit flag > server singleResolution > all
            if actual_resolution > 0:
                res_cap = actual_resolution
            elif server_cfg.single_resolution > 0:
                res_cap = server_cfg.single_resolution
                rpt.info(f"Using server singleResolution cap: {res_cap}p")
            else:
                res_cap = max(ALLOWED_RESOLUTIONS)

            target_resolutions = [r for r in ALLOWED_RESOLUTIONS if r <= res_cap]
            if not target_resolutions:
                target_resolutions = [ALLOWED_RESOLUTIONS[0]]

            encoded_files: list[Path] = []  # list of (path, ext, resolution) tuples
            encoded_duration = duration

            if fmt == "mp4":
                res_label = (
                    f"up to {res_cap}p" if res_cap < max(ALLOWED_RESOLUTIONS) else "all resolutions"
                )
                rpt.begin_encode(f"Encoding MP4 ({res_label})", int(duration) or 100)
                mp4_files = encode_mp4_multi(
                    input_path=raw_file,
                    output_dir=work_dir,
                    resolutions=target_resolutions,
                    ffmpeg_bin=cfg.ffmpeg_bin,
                    ffprobe_bin=cfg.ffprobe_bin,
                    progress_callback=rpt.on_encode,
                )
                files_to_clean.extend(mp4_files)
                encoded_files.extend(mp4_files)
                rpt.success(f"Encoded {len(mp4_files)} MP4 file(s)")
                if mp4_files:
                    encoded_duration = probe_duration(mp4_files[-1], cfg.ffprobe_bin) or duration
                upload_resolution = (
                    max(int(f.stem.rsplit("_", 1)[-1].rstrip("p")) for f in mp4_files)
                    if mp4_files
                    else res_cap
                )

            else:  # hls
                rpt.begin_encode(
                    f"Encoding HLS (up to {res_cap}p)",
                    int(duration * len(target_resolutions)) or 100,
                )
                hls_zip = encode_hls(
                    input_path=raw_file,
                    output_dir=work_dir,
                    resolutions=target_resolutions,
                    ffmpeg_bin=cfg.ffmpeg_bin,
                    ffprobe_bin=cfg.ffprobe_bin,
                    progress_callback=rpt.on_encode,
                )
                files_to_clean.append(hls_zip)
                encoded_files = [hls_zip]
                rpt.success(f"HLS ZIP → {hls_zip.name}")
                upload_resolution = res_cap

            # ----------------------------------------------------------
            # Step 4 – Generate thumbnails
            # ----------------------------------------------------------
            rpt.info("Generating thumbnails…")
            jpg_file = work_dir / f"{filename_stem}.jpg"
            gif_file = work_dir / f"{filename_stem}.gif"
            webp_file = work_dir / f"{filename_stem}.webp"
            files_to_clean.extend([jpg_file, gif_file, webp_file])

            for fn, label in [
                (lambda: extract_thumbnail_jpg(raw_file, jpg_file, seek, cfg.ffmpeg_bin), "JPG"),
                (
                    lambda: extract_thumbnail_gif(raw_file, gif_file, seek, 3.0, cfg.ffmpeg_bin),
                    "GIF",
                ),
                (
                    lambda: extract_thumbnail_webp(raw_file, webp_file, seek, 3.0, cfg.ffmpeg_bin),
                    "WebP",
                ),
            ]:
                try:
                    fn()  # type: ignore[operator]
                    rpt.info(f"  Thumbnail {label} created")
                except Exception as exc:
                    rpt.warning(f"  Thumbnail {label} skipped: {exc}")

            # ----------------------------------------------------------
            # Step 5 – Upload to AVideo
            # ----------------------------------------------------------
            with AVideoClient(cfg.server_url, ssl_verify=cfg.ssl_verify) as client:
                # 5a. Login
                rpt.info(f"Logging in to {cfg.server_url} as {cfg.username}…")
                login_result = client.login(cfg.username, cfg.password)
                rpt.success(f"Logged in as {login_result.name or login_result.username}")

                # fmt and server_cfg already resolved before Step 3
                resolved_fmt = fmt

                # 5b. Register video record  (use highest resolution for registration)
                rpt.info("Registering video with AVideo…")
                reg_ext = "zip" if resolved_fmt == "hls" else "mp4"
                reg = client.register_video(
                    title=video_title,
                    format_ext=reg_ext,
                    resolution=upload_resolution,
                    duration=encoded_duration,
                    categories_id=cfg.categories_id,
                    description=video_description,
                )
                rpt.success(
                    f"Video registered: videos_id={reg.videos_id} hash={reg.video_id_hash[:12]}…"
                )
                if reg.msg:
                    rpt.info(f"  Server message: {reg.msg}")

                # 5c. Upload encoded file(s)
                # For multi-res MP4 upload smallest files first (like PHP encoder),
                # then the largest last so the server's format is set by the highest quality file.
                upload_queue = list(encoded_files)
                if resolved_fmt == "mp4" and len(upload_queue) > 1:
                    upload_queue.sort(key=lambda p: p.stat().st_size)

                for idx, enc_file in enumerate(upload_queue):
                    file_size = enc_file.stat().st_size
                    # Parse resolution from filename (e.g. video_720p.mp4 → 720)
                    try:
                        file_res = int(enc_file.stem.rsplit("_", 1)[-1].rstrip("p"))
                    except ValueError:
                        file_res = upload_resolution
                    file_ext = "zip" if enc_file.suffix == ".zip" else "mp4"

                    rpt.begin_upload(file_size)
                    upload_result = client.upload_file(
                        file_path=enc_file,
                        videos_id=reg.videos_id,
                        video_id_hash=reg.video_id_hash,
                        title=video_title,
                        format_ext=file_ext,
                        resolution=file_res,
                        duration=encoded_duration,
                        categories_id=cfg.categories_id,
                        description=video_description,
                        progress_callback=rpt.on_upload,
                    )
                    rpt.success(
                        f"Uploaded {enc_file.name} "
                        f"({file_size // 1_048_576} MiB)"
                        + (f" [{idx + 1}/{len(upload_queue)}]" if len(upload_queue) > 1 else "")
                    )
                    if upload_result.get("msg"):
                        rpt.info(f"  Server: {upload_result['msg']}")

                # 5c-ii. Auto-extract and upload MP3 if server config requires it
                if server_cfg.auto_convert_to_mp3 and resolved_fmt != "hls":
                    mp3_file = work_dir / f"{filename_stem}.mp3"
                    files_to_clean.append(mp3_file)
                    try:
                        rpt.info("Auto-extracting MP3 (server config: autoConvertVideosToMP3)…")
                        extract_mp3(raw_file, mp3_file, ffmpeg_bin=cfg.ffmpeg_bin)
                        mp3_size = mp3_file.stat().st_size
                        rpt.begin_upload(mp3_size)
                        client.upload_file(
                            file_path=mp3_file,
                            videos_id=reg.videos_id,
                            video_id_hash=reg.video_id_hash,
                            title=video_title,
                            format_ext="mp3",
                            resolution=0,
                            duration=encoded_duration,
                            categories_id=cfg.categories_id,
                            description=video_description,
                            progress_callback=rpt.on_upload,
                        )
                        rpt.success(f"MP3 uploaded ({mp3_size // 1_048_576} MiB)")
                    except Exception as exc:
                        rpt.warning(f"MP3 auto-extraction skipped: {exc}")

                # 5d. Upload thumbnails
                rpt.info("Uploading thumbnails…")
                img_result = client.upload_images(
                    videos_id=reg.videos_id,
                    video_id_hash=reg.video_id_hash,
                    duration=encoded_duration,
                    jpg_path=jpg_file if jpg_file.exists() else None,
                    gif_path=gif_file if gif_file.exists() else None,
                    webp_path=webp_file if webp_file.exists() else None,
                )
                if not img_result.get("error"):
                    rpt.success("Thumbnails uploaded")
                else:
                    rpt.warning(f"Thumbnail upload: {img_result.get('msg', 'error')}")

                # 5e. Notify encoding done
                rpt.info("Notifying AVideo that encoding is complete…")
                done_result = client.notify_done(reg.videos_id, reg.video_id_hash)
                if done_result.get("error"):
                    rpt.warning(f"Notify-done error: {done_result.get('msg', 'unknown')}")
                else:
                    rpt.success(f"Done! Video is live: {cfg.server_url}video/{reg.videos_id}")

        except AVideoAPIError as exc:
            rpt.error(f"AVideo API error: {exc}")
            raise typer.Exit(1) from exc
        except KeyboardInterrupt:
            rpt.warning("Interrupted by user.")
            raise typer.Exit(130) from None
        except Exception as exc:
            rpt.error(f"Unexpected error: {exc}")
            if debug:
                import traceback

                traceback.print_exc()
            raise typer.Exit(1) from exc
        finally:
            # ----------------------------------------------------------
            # Cleanup temp files unless --keep-files was specified
            # ----------------------------------------------------------
            if not cfg.keep_files:
                for f in files_to_clean:
                    try:
                        if f.exists():
                            f.unlink()
                    except OSError:
                        pass
                # Remove work_dir only if it is now empty
                try:
                    if work_dir.exists() and not any(work_dir.iterdir()):
                        shutil.rmtree(work_dir, ignore_errors=True)
                except OSError:
                    pass


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open a browser tab"),
) -> None:
    """Start the web UI (FastAPI + uvicorn)."""
    import webbrowser

    import uvicorn

    from local_encoder.server import app as fastapi_app

    url = f"http://{host}:{port}"
    typer.echo(f"Starting web UI at {url}")
    if not no_browser:
        # Open after a short delay so the server is ready
        import threading

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(fastapi_app, host=host, port=port)
