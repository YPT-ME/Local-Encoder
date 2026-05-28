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
from typing import Annotated, Optional

import typer

from avideo_local_encoder import __version__
from avideo_local_encoder.avideo_client import AVideoAPIError, AVideoClient
from avideo_local_encoder.config import Config, load_config
from avideo_local_encoder.downloader import download_video, get_video_info
from avideo_local_encoder.encoder import (
    ALLOWED_RESOLUTIONS,
    encode_mp4,
    extract_thumbnail_gif,
    extract_thumbnail_jpg,
    extract_thumbnail_webp,
    nearest_resolution,
)
from avideo_local_encoder.progress import ProgressReporter, console
from avideo_local_encoder.utils import probe_duration, sanitize_filename

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
        Optional[bool],
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
        Optional[str],
        typer.Option("--server", "-s", help="AVideo server URL (overrides AVIDEO_SERVER_URL)."),
    ] = None,
    user: Annotated[
        Optional[str],
        typer.Option("--user", "-u", help="AVideo username (overrides AVIDEO_USERNAME)."),
    ] = None,
    password: Annotated[
        Optional[str],
        typer.Option(
            "--password",
            "-p",
            help="AVideo password (overrides AVIDEO_PASSWORD).",
            hide_input=True,
        ),
    ] = None,
    # Encoding
    resolution: Annotated[
        int,
        typer.Option(
            "--resolution",
            "-r",
            help=f"Target height in pixels. Allowed: {ALLOWED_RESOLUTIONS}.",
        ),
    ] = 1080,
    # Metadata
    title: Annotated[
        Optional[str],
        typer.Option("--title", "-t", help="Video title (auto-detected from yt-dlp if omitted)."),
    ] = None,
    description: Annotated[
        Optional[str],
        typer.Option("--description", "-d", help="Video description."),
    ] = None,
    categories_id: Annotated[
        Optional[int],
        typer.Option("--categories-id", "-c", help="AVideo category ID."),
    ] = None,
    # Files / directories
    output_dir: Annotated[
        Optional[Path],
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
        Optional[Path],
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
        raise typer.Exit(1)

    # Snap to the nearest supported resolution
    actual_resolution = nearest_resolution(resolution)
    if actual_resolution != resolution:
        console.print(
            f"  [yellow]⚠[/yellow] Resolution {resolution}p is not in the allowed list; "
            f"using {actual_resolution}p instead."
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
            # Step 3 – Encode
            # ----------------------------------------------------------
            encoded_name = f"{filename_stem}_{actual_resolution}p.mp4"
            encoded_file = work_dir / encoded_name
            files_to_clean.append(encoded_file)

            rpt.begin_encode(f"Encoding {actual_resolution}p", int(duration) or 100)
            encode_mp4(
                input_path=raw_file,
                output_path=encoded_file,
                resolution=actual_resolution,
                ffmpeg_bin=cfg.ffmpeg_bin,
                progress_callback=rpt.on_encode,
            )
            rpt.success(f"Encoded  → {encoded_file.name}")

            # Re-probe duration from the encoded file for accuracy
            encoded_duration = probe_duration(encoded_file, cfg.ffprobe_bin) or duration

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
                (lambda: extract_thumbnail_gif(raw_file, gif_file, seek, 3.0, cfg.ffmpeg_bin), "GIF"),
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

                # 5b. Register video record
                rpt.info("Registering video with AVideo…")
                reg = client.register_video(
                    title=video_title,
                    format_ext="mp4",
                    resolution=actual_resolution,
                    duration=encoded_duration,
                    categories_id=cfg.categories_id,
                    description=video_description,
                )
                rpt.success(
                    f"Video registered: videos_id={reg.videos_id} "
                    f"hash={reg.video_id_hash[:12]}…"
                )
                if reg.msg:
                    rpt.info(f"  Server message: {reg.msg}")

                # 5c. Upload encoded file
                file_size = encoded_file.stat().st_size
                rpt.begin_upload(file_size)
                upload_result = client.upload_file(
                    file_path=encoded_file,
                    videos_id=reg.videos_id,
                    video_id_hash=reg.video_id_hash,
                    title=video_title,
                    format_ext="mp4",
                    resolution=actual_resolution,
                    duration=encoded_duration,
                    categories_id=cfg.categories_id,
                    description=video_description,
                    progress_callback=rpt.on_upload,
                )
                rpt.success(f"File uploaded ({file_size // 1_048_576} MiB)")
                if upload_result.get("msg"):
                    rpt.info(f"  Server: {upload_result['msg']}")

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
                    rpt.success(
                        f"Done! Video is live: {cfg.server_url}video?v={reg.videos_id}"
                    )

        except AVideoAPIError as exc:
            rpt.error(f"AVideo API error: {exc}")
            raise typer.Exit(1)
        except KeyboardInterrupt:
            rpt.warning("Interrupted by user.")
            raise typer.Exit(130)
        except Exception as exc:
            rpt.error(f"Unexpected error: {exc}")
            if debug:
                import traceback
                traceback.print_exc()
            raise typer.Exit(1)
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
