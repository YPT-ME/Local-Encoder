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

from local_encoder import __version__, keep_awake
from local_encoder import history as _history
from local_encoder.avideo_client import AVideoClient
from local_encoder.config import load_config
from local_encoder.downloader import (
    download_video,
    get_video_info,
    is_web_url,
    reject_unsupported,
)
from local_encoder.encoder import (
    ALLOWED_RESOLUTIONS,
    detect_video_codec,
    encode_hls,
    encode_mp4_multi,
    extract_mp3,
    extract_thumbnail_gif,
    extract_thumbnail_jpg,
    extract_thumbnail_webp,
    nearest_resolution,
    output_resolution,
    probe_media,
)
from local_encoder.errors import LocalEncoderError, classify
from local_encoder.logging_setup import configure_logging
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
                "Output format: 'auto' (what the site supports), 'mp4' (multi-resolution MP4), "
                "or 'hls' (multi-resolution HLS ZIP with AES-128 encryption; only when the "
                "site has VideoHLS). Default: 'auto'."
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
    gpu: Annotated[
        bool,
        typer.Option(
            "--gpu/--no-gpu",
            help="Use the graphics card when it can convert the video (faster). Default: on.",
        ),
    ] = True,
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
    log_file = configure_logging(debug=debug, stream=sys.stderr)
    if debug:
        logging.getLogger().debug("Log file: %s", log_file)
    else:
        typer.echo(f"Logs: {log_file}")

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

    if not is_web_url(video_url):
        console.print(f"[red]{classify(LocalEncoderError('invalid_url')).message}[/red]")
        raise typer.Exit(1)

    fmt = format.lower()
    if fmt not in ("auto", "mp4", "hls"):
        console.print(f"[red]Unknown format '{format}'; use 'auto', 'mp4', or 'hls'.[/red]")
        raise typer.Exit(1)

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

    hist_entry = _history.new_entry(video_url, cfg.server_url, cfg.username)

    with ProgressReporter(verbose=debug) as rpt, keep_awake.inhibit():
        files_to_clean: list[Path] = []
        succeeded = False

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
            reject_unsupported(info)

            video_title = title or sanitize_filename(info.get("title") or "video")
            video_description = description or info.get("description") or ""
            meta_duration = float(info.get("duration") or 0)
            filename_stem = sanitize_filename(video_title)[:80]

            hist_entry.title = video_title
            _history.update_entry(hist_entry)

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

            media = probe_media(raw_file, cfg.ffprobe_bin)
            if not media.has_video:
                raise LocalEncoderError("audio_only" if media.has_audio else "unreadable_file")

            # Probe actual duration from the downloaded file
            duration = probe_duration(raw_file, cfg.ffprobe_bin) or meta_duration
            if duration == 0:
                rpt.warning("Could not determine video duration; using 0.")

            # Thumbnail seek point: middle of the video, capped at 600 s (Encoder.php)
            seek = min(duration / 2, 600.0) if duration > 0 else 5.0

            # ----------------------------------------------------------
            # Step 2b – Log in and read what the site accepts. The login
            # tells whether the site plays HLS (VideoHLS) and which
            # resolutions this user may receive.
            # ----------------------------------------------------------
            rpt.info(f"Logging in to {cfg.server_url} as {cfg.username}…")
            with AVideoClient(cfg.server_url, ssl_verify=cfg.ssl_verify) as _login_client:
                login_result = _login_client.login(cfg.username, cfg.password)
                server_cfg = _login_client.get_server_config()
            rpt.success(f"Logged in as {login_result.name or login_result.username}")
            hls_available = login_result.video_hls and not server_cfg.disable_hls
            rpt.info(
                f"Site: hls={hls_available}, auto_mp3={server_cfg.auto_convert_to_mp3}, "
                f"single_res={server_cfg.single_resolution}"
            )

            # ----------------------------------------------------------
            # Step 3 – Encode
            # ----------------------------------------------------------
            if fmt == "hls" and not hls_available:
                rpt.warning("This site does not play HLS (VideoHLS is off); sending MP4 instead.")
                fmt = "mp4"
            elif fmt == "auto":
                fmt = "hls" if hls_available else "mp4"
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
            allowed = login_result.allowed_resolutions
            if allowed:
                # Like Format.php getFinalResolutions: no overlap keeps the list
                target_resolutions = [r for r in target_resolutions if r in allowed] or (
                    target_resolutions
                )
            if not target_resolutions:
                target_resolutions = [ALLOWED_RESOLUTIONS[0]]

            codec = detect_video_codec(cfg.ffmpeg_bin, prefer_hardware=gpu)
            rpt.info(f"Converting with: {codec.label}")

            def on_notice(code: str) -> None:
                rpt.warning("The graphics card could not convert this video; using the processor.")

            encoded_files: list[Path] = []
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
                    codec=codec,
                    notice_callback=on_notice,
                )
                files_to_clean.extend(mp4_files)
                encoded_files.extend(mp4_files)
                rpt.success(f"Encoded {len(mp4_files)} MP4 file(s)")
                if mp4_files:
                    encoded_duration = probe_duration(mp4_files[-1], cfg.ffprobe_bin) or duration
                upload_resolution: int | None = max(
                    (r for r in (output_resolution(f) for f in mp4_files) if r is not None),
                    default=res_cap,
                )

            else:  # hls
                rpt.begin_encode(f"Encoding HLS (up to {res_cap}p)", int(duration) or 100)
                hls_zip = encode_hls(
                    input_path=raw_file,
                    output_dir=work_dir,
                    resolutions=target_resolutions,
                    ffmpeg_bin=cfg.ffmpeg_bin,
                    ffprobe_bin=cfg.ffprobe_bin,
                    progress_callback=rpt.on_encode,
                    codec=codec,
                    notice_callback=on_notice,
                )
                files_to_clean.append(hls_zip)
                encoded_files = [hls_zip]
                rpt.success(f"HLS ZIP → {hls_zip.name}")
                upload_resolution = None  # the HLS zip is stored without a resolution

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
                    fn()  # type: ignore[no-untyped-call]
                    rpt.info(f"  Thumbnail {label} created")
                except Exception as exc:
                    rpt.warning(f"  Thumbnail {label} skipped: {exc}")

            # ----------------------------------------------------------
            # Step 5 – Upload to AVideo (reusing the login token)
            # ----------------------------------------------------------
            with AVideoClient(cfg.server_url, ssl_verify=cfg.ssl_verify) as client:
                client.use_login(login_result)
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
                    download_url=video_url,
                )
                rpt.success(
                    f"Video registered: videos_id={reg.videos_id} hash={reg.video_id_hash[:12]}…"
                )
                if reg.msg:
                    rpt.info(f"  Server message: {reg.msg}")

                # From here on the site has a video record: tell it when anything fails,
                # otherwise the video stays in "encoding" forever (Encoder.php does the same).
                try:
                    # 5c. Upload encoded file(s)
                    # For multi-res MP4 upload smallest files first (like PHP encoder),
                    # then the largest last so the server's format is set by the highest quality file.
                    upload_queue = list(encoded_files)
                    if resolved_fmt == "mp4" and len(upload_queue) > 1:
                        upload_queue.sort(key=lambda p: p.stat().st_size)

                    for idx, enc_file in enumerate(upload_queue):
                        file_size = enc_file.stat().st_size
                        # video_720p.mp4 → 720; the HLS zip has no resolution
                        file_res = output_resolution(enc_file)
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
                            download_url=video_url,
                            progress_callback=rpt.on_upload,
                        )
                        rpt.success(
                            f"Uploaded {enc_file.name} "
                            f"({file_size // 1_048_576} MiB)"
                            + (f" [{idx + 1}/{len(upload_queue)}]" if len(upload_queue) > 1 else "")
                        )
                        if upload_result.get("msg"):
                            rpt.info(f"  Server: {upload_result['msg']}")

                    hist_entry.videos_id = reg.videos_id

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
                                resolution=None,
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
                    client.notify_done(reg.videos_id, reg.video_id_hash)
                    rpt.success(f"Done! Video is live: {cfg.server_url}video/{reg.videos_id}")

                except BaseException:
                    client.notify_failed(reg.videos_id, reg.video_id_hash)
                    raise

                hist_entry.status = "success"
                hist_entry.title = video_title
                _history.update_entry(hist_entry)
                succeeded = True

        except KeyboardInterrupt:
            hist_entry.status = "failed"
            hist_entry.error = "Interrupted"
            _history.update_entry(hist_entry)
            rpt.warning("Interrupted by user.")
            raise typer.Exit(130) from None
        except Exception as exc:
            # One plain-language message with the next step; the details are in the log.
            problem = classify(exc)
            logging.getLogger(__name__).exception("Import failed")
            hist_entry.status = "failed"
            hist_entry.error = problem.message
            _history.update_entry(hist_entry)
            rpt.error(problem.message)
            rpt.info(f"Details: {log_file}")
            if debug:
                import traceback

                traceback.print_exc()
            raise typer.Exit(1) from exc
        finally:
            # ----------------------------------------------------------
            # Cleanup temp files unless --keep-files was specified.
            # After a failure the files are kept so the work is not lost.
            # ----------------------------------------------------------
            if not succeeded and any(f.exists() for f in files_to_clean):
                console.print(f"[yellow]Files kept for a new attempt in:[/yellow] {work_dir}")
            if succeeded and not cfg.keep_files:
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


@app.command("logs")
def show_logs(
    server: Annotated[
        str | None,
        typer.Option("--server", "-s", help="Filter by AVideo server URL."),
    ] = None,
    user: Annotated[
        str | None,
        typer.Option("--user", "-u", help="Filter by username."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Max entries to show (0 = all)."),
    ] = 20,
) -> None:
    """Show the history of past import jobs."""
    from rich.table import Table

    entries = _history.list_entries(server=server, username=user)
    if limit > 0:
        entries = entries[:limit]

    if not entries:
        console.print("[yellow]No history found.[/yellow]")
        raise typer.Exit()

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Date", min_width=16)
    table.add_column("Title", min_width=30, no_wrap=False)
    table.add_column("Server", min_width=20)
    table.add_column("User", min_width=10)
    table.add_column("Status", width=8)
    table.add_column("ID", width=6)

    _STATUS_STYLE = {"success": "green", "failed": "red", "pending": "yellow"}

    for idx, e in enumerate(entries, start=1):
        style = _STATUS_STYLE.get(e.status, "white")
        vid_id = str(e.videos_id) if e.videos_id else "—"
        table.add_row(
            str(idx),
            e.display_time(),
            e.title,
            e.server,
            e.username,
            f"[{style}]{e.status}[/{style}]",
            vid_id,
        )

    console.print(table)


@app.command("selftest")
def selftest(
    download: Annotated[
        list[str] | None,
        typer.Option(
            "--download",
            help="Also download this link (repeatable); a failed download fails the test.",
        ),
    ] = None,
    try_download: Annotated[
        list[str] | None,
        typer.Option(
            "--try-download",
            help="Also try this link (repeatable); a failure is only reported.",
        ),
    ] = None,
    require_bundled: Annotated[
        bool | None,
        typer.Option(
            "--require-bundled/--allow-system-tools",
            help="Require the FFmpeg, FFprobe and deno shipped with the app (default: when packaged).",
        ),
    ] = None,
) -> None:
    """Check this installation: bundled tools, video conversion, web page files, downloads.

    Nothing is sent to an AVideo site. Exit code 1 when a required check fails.
    """
    from local_encoder.selftest import Check, passed, run_selftest

    configure_logging(stream=None)

    def show(check: Check) -> None:
        # Plain-text marks: they print on every console (CI logs, old Windows code pages).
        mark = (
            "[green]\\[ OK ][/green]"
            if check.ok
            else ("[red]\\[FAIL][/red]" if check.required else "[yellow]\\[WARN][/yellow]")
        )
        detail = f" [dim]- {check.detail}[/dim]" if check.detail else ""
        console.print(f"{mark} {check.name}{detail}", highlight=False)

    checks = run_selftest(
        download_urls=download or [],
        optional_download_urls=try_download or [],
        require_bundled=require_bundled,
        report=show,
    )
    if passed(checks):
        console.print("[bold green]Local Encoder is working.[/bold green]")
        return
    failed = [c.name for c in checks if c.required and not c.ok]
    console.print(f"[bold red]Problems found:[/bold red] {', '.join(failed)}")
    raise typer.Exit(1)


# Fixed by default so the browser keeps the saved site/user settings (they are stored per
# address, port included). Uncommon, to avoid clashing with other local web apps.
DEFAULT_PORT = 47800


def _pick_port(host: str, port: int) -> int:
    """Return *port* when it is free, otherwise any free port chosen by the OS."""
    import socket

    candidates = (*range(port, port + 10), 0) if port == DEFAULT_PORT else (port, 0)
    for candidate in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, candidate))
            except OSError:
                continue
            chosen: int = sock.getsockname()[1]
            return chosen
    raise OSError(f"No free port available on {host}")


def _local_url(host: str, port: int) -> str:
    """Address the browser on this computer uses to reach a server bound to *host*."""
    browse_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
    if ":" in browse_host:
        browse_host = f"[{browse_host}]"
    return f"http://{browse_host}:{port}"


def _running_instance_url(host: str, port: int) -> str | None:
    """Return the address of a Local Encoder already answering on *port*, if any."""
    import httpx

    url = _local_url(host, port)
    try:
        # The packaged app may check GitHub for updates (up to 5 s) before answering.
        response = httpx.get(
            f"{url}/api/version", timeout=httpx.Timeout(10.0, connect=2.0), trust_env=False
        )
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if (
        response.status_code == 200
        and isinstance(data, dict)
        and "version" in data
        and (
            data.get("application") == "avideo-local-encoder"
            or data.get("download_url") == "https://github.com/YPT-ME/Local-Encoder/releases/latest"
        )
    ):
        return url
    return None


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(DEFAULT_PORT, help="Bind port (another free port is used if busy)"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open a browser tab"),
    no_tray: bool = typer.Option(
        False, "--no-tray", help="Do not show the icon near the clock; stop with Ctrl+C"
    ),
    open_url: str = typer.Option("", "--open-url", hidden=True),
) -> None:
    """Start the web UI (FastAPI + uvicorn)."""
    import webbrowser

    from local_encoder import desktop

    try:
        request = desktop.parse_link(open_url) if open_url else None
        with desktop.StartupLock() as guard:
            existing = desktop.running_url()
            if existing and (
                request
                or (host == "127.0.0.1" and port == DEFAULT_PORT)
                or existing == _local_url(host, port)
            ):
                if not no_browser:
                    webbrowser.open(desktop.page_url(existing, request))
                return
            desktop.startup_guard = guard
            try:
                _serve(host, port, no_browser, no_tray, request)
            finally:
                desktop.startup_guard = None
    except (ValueError, TimeoutError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None


@app.command("open-url", hidden=True)
def open_from_browser(url: str) -> None:
    """Open a validated browser link; never start a video automatically."""
    serve("127.0.0.1", DEFAULT_PORT, False, False, url)


@app.command("register-browser")
def register_browser() -> None:
    """Enable AVideo's Open Local Encoder button for this computer user."""
    from local_encoder import desktop

    if not desktop.register_handler(explicit=True):
        console.print(
            "[red]Browser opening could not be enabled. Open Local Encoder manually.[/red]"
        )
        raise typer.Exit(1)
    console.print("Browser opening is enabled for this user.")


def _serve(
    host: str, port: int, no_browser: bool, no_tray: bool, request: dict[str, str] | None = None
) -> None:
    import signal
    import threading
    import webbrowser

    from local_encoder import desktop

    desktop.register_handler()
    actual_port = _pick_port(host, port)
    if actual_port != port:
        existing = _running_instance_url(host, port)
        if existing and (not request or desktop.supports_handoff(existing)):
            console.print(f"Local Encoder is already running at {existing}")
            if not no_browser:
                webbrowser.open(desktop.page_url(existing, request))
            raise typer.Exit(0)
        console.print(f"[yellow]Port {port} is busy; using {actual_port} instead.[/yellow]")

    import uvicorn

    from local_encoder import tray
    from local_encoder.server import app as fastapi_app

    base_url = _local_url(host, actual_port)
    desktop.runtime_url = base_url
    url = desktop.page_url(base_url, request)
    uv_server = uvicorn.Server(
        uvicorn.Config(
            fastapi_app,
            host=host,
            port=actual_port,
            log_level="warning",
            # Open progress streams (SSE) would otherwise keep Quit waiting forever.
            timeout_graceful_shutdown=5,
        )
    )
    pystray = None if no_tray else tray.load_pystray()

    if pystray is None:
        console.print(f"[bold green]Local Encoder {__version__} is running at {url}[/bold green]")
        console.print("Keep this window open while you use it. Close it to stop Local Encoder.")
        if not no_browser:
            threading.Thread(
                target=tray.open_browser_when_ready, args=(uv_server, url), daemon=True
            ).start()
        uv_server.run()
        return

    thread = threading.Thread(target=uv_server.run, name="web-server", daemon=True)
    thread.start()
    if not tray.wait_until_started(uv_server, thread, timeout=30.0) and not thread.is_alive():
        logging.getLogger(__name__).error("The web server did not start on %s", url)
        console.print(f"[red]Local Encoder could not start on {url}.[/red]")
        raise typer.Exit(1)

    console.print(f"[bold green]Local Encoder {__version__} is running at {url}[/bold green]")
    console.print(
        "Local Encoder now lives in its icon near the clock (it may be hidden under the "
        "arrow). Use that icon to open the page or to quit."
    )
    if sys.platform != "win32":
        console.print("You can also press Ctrl+C here to stop it.")
    if not no_browser:
        webbrowser.open(url)

    active_jobs, set_notifier = tray.server_hooks()

    def stop_server() -> None:
        uv_server.should_exit = True

    tray_app = tray.TrayApp(
        pystray,
        open_page=lambda: webbrowser.open(url),
        on_quit=stop_server,
        active_jobs=active_jobs,
    )
    previous_sigint = None
    try:
        # The tray loop owns the main thread, so let Ctrl+C end the process directly.
        previous_sigint = signal.signal(signal.SIGINT, signal.SIG_DFL)
    except (ValueError, OSError):
        pass
    set_notifier(tray_app.notify)
    try:
        shown = tray_app.run()
    finally:
        set_notifier(None)
        if previous_sigint is not None:
            signal.signal(signal.SIGINT, previous_sigint)

    if not shown:
        console.print("Keep this window open while you use it. Close it to stop Local Encoder.")
        try:
            while thread.is_alive():
                thread.join(0.5)
        except KeyboardInterrupt:
            pass
    stop_server()
    thread.join(15)
