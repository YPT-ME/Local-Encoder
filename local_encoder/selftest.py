"""Check that this installation really works: bundled tools, encoding, web UI files, downloads.

Used by ``local-encoder selftest`` – by users ("is my copy OK?") and by the release workflow on
the packaged app (``scripts/smoke_test.py``), so a build whose FFmpeg cannot be found or cannot
encode is never published. Nothing is sent to an AVideo site.
"""

from __future__ import annotations

import functools
import logging
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from local_encoder import __version__, _frozen, updates
from local_encoder.encoder import (
    SOFTWARE_CODEC,
    detect_video_codec,
    encode_hls,
    encode_mp4_multi,
    extract_mp3,
    extract_thumbnail_gif,
    extract_thumbnail_jpg,
    extract_thumbnail_webp,
    probe_media,
)
from local_encoder.utils import probe_duration

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
VENDOR_FILES = ("react.development.js", "react-dom.development.js", "babel.min.js", "tailwind.js")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


Reporter = Callable[[Check], None]


def _tool_version(binary: str, flag: str = "-version") -> str:
    result = subprocess.run(
        [binary, flag],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"exit code {result.returncode}")
    return (result.stdout.strip().splitlines() or ["?"])[0]


def _make_clip(ffmpeg: str, path: Path) -> str:
    """A 2-second 640×360 video with a tone (no input file needed)."""
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=30:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode != 0 or not path.exists():
        tail = result.stderr.decode(errors="replace")[-300:]
        raise RuntimeError(f"could not create the test clip: {tail}")
    return "2 s, 640x360"


class _Runner:
    def __init__(self, report: Reporter | None) -> None:
        self.checks: list[Check] = []
        self._report = report

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        if self._report:
            self._report(check)
        return check

    def run(self, name: str, step: Callable[[], str], required: bool = True) -> bool:
        try:
            detail = step()
        except Exception as exc:
            logger.exception("Self-test step failed: %s", name)
            self.add(Check(name, False, str(exc) or type(exc).__name__, required))
            return False
        self.add(Check(name, True, detail, required))
        return True


def run_selftest(
    download_urls: list[str] | None = None,
    optional_download_urls: list[str] | None = None,
    require_bundled: bool | None = None,
    work_dir: Path | None = None,
    report: Reporter | None = None,
) -> list[Check]:
    """Run every check and return the results (``report`` sees each one as it finishes).

    ``require_bundled`` (default: when packaged) fails unless FFmpeg, FFprobe and deno come from
    the app itself rather than from the computer's PATH.
    """
    frozen = updates.is_frozen()
    if require_bundled is None:
        require_bundled = frozen
    runner = _Runner(report)
    runner.add(Check("Local Encoder", True, f"{__version__}{' (packaged)' if frozen else ''}"))

    ffmpeg, ffprobe = _frozen.resolve_ffmpeg(), _frozen.resolve_ffprobe()
    deno = _frozen.resolve_deno()
    bundle_dirs = [d.resolve() for d in _frozen._bundle_dirs()]

    def bundled(path: str | None) -> bool:
        if not path or not Path(path).is_file():
            return False
        return Path(path).resolve().parent in bundle_dirs

    def included(name: str, path: str | None) -> str:
        if not bundled(path):
            raise RuntimeError(f"{name} is not inside the app (found: {path or 'nothing'})")
        return str(path)

    if require_bundled:
        for name, path in (("FFmpeg", ffmpeg), ("FFprobe", ffprobe), ("deno", deno)):
            runner.run(f"{name} is included", functools.partial(included, name, path))
    runner.run("FFmpeg runs", lambda: _tool_version(ffmpeg))
    runner.run("FFprobe runs", lambda: _tool_version(ffprobe))
    if deno:
        deno_bin = deno
        runner.run("deno runs", lambda: _tool_version(deno_bin, "--version"))
    else:
        runner.add(Check("deno runs", False, "not found (YouTube needs it)", require_bundled))

    def static_files() -> str:
        names = ["index.html", "i18n.js"]
        if frozen or (STATIC_DIR / "vendor").is_dir():
            names += [f"vendor/{n}" for n in VENDOR_FILES]
        missing = [n for n in names if not (STATIC_DIR / n).is_file()]
        if missing:
            raise RuntimeError("missing: " + ", ".join(missing))
        return f"{len(names)} files"

    runner.run("Web page files", static_files)

    temp = Path(tempfile.mkdtemp(prefix="local-encoder-selftest-", dir=work_dir))
    try:
        _encoding_checks(runner, ffmpeg, ffprobe, temp)
        wanted = [(url, True) for url in download_urls or []]
        wanted += [(url, False) for url in optional_download_urls or []]
        for index, (url, required) in enumerate(wanted):
            # One folder per link: yt-dlp would reuse an earlier file with the same name.
            _download_check(runner, url, temp / f"download-{index}", required=required)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return runner.checks


def _encoding_checks(runner: _Runner, ffmpeg: str, ffprobe: str, temp: Path) -> None:
    clip = temp / "clip.mp4"
    if not runner.run("Create a test clip", functools.partial(_make_clip, ffmpeg, clip)):
        return

    def probe() -> str:
        media = probe_media(clip, ffprobe)
        duration = probe_duration(clip, ffprobe)
        if not (media.has_video and media.has_audio and media.height == 360 and duration > 1):
            raise RuntimeError(f"unexpected probe result: {media}, {duration:.1f} s")
        return f"{media.width}x{media.height}, {duration:.1f} s"

    runner.run("Read the video (ffprobe)", probe)

    def mp4() -> str:
        outputs = encode_mp4_multi(
            clip, temp / "mp4", [240, 360], ffmpeg, ffprobe, codec=SOFTWARE_CODEC
        )
        if [p.name for p in outputs] != ["clip_240p.mp4", "clip_360p.mp4"]:
            raise RuntimeError(f"unexpected outputs: {[p.name for p in outputs]}")
        for out in outputs:
            if not probe_media(out, ffprobe).has_video:
                raise RuntimeError(f"{out.name} has no video")
        return "240p + 360p"

    runner.run("Convert to MP4", mp4)

    def hls() -> str:
        zip_path = encode_hls(clip, temp / "hls", [240], ffmpeg, ffprobe, codec=SOFTWARE_CODEC)
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        bad = [n for n in names if n.startswith(("/", "\\")) or ".." in n or ":" in n]
        if bad:
            raise RuntimeError(f"unsafe paths in the zip: {bad[:3]}")
        needed = ["index.m3u8", "res240/index.m3u8"]
        if any(n not in names for n in needed) or not any(n.endswith(".key") for n in names):
            raise RuntimeError(f"incomplete package: {names[:10]}")
        return f"{len(names)} files in the zip"

    runner.run("Convert to HLS (encrypted)", hls)

    def thumbnails() -> str:
        made = [
            extract_thumbnail_jpg(clip, temp / "t.jpg", 1, ffmpeg),
            extract_thumbnail_gif(clip, temp / "t.gif", 0, 1.0, ffmpeg),
            extract_thumbnail_webp(clip, temp / "t.webp", 0, 1.0, ffmpeg),
        ]
        empty = [p.name for p in made if not p.exists() or p.stat().st_size == 0]
        if empty:
            raise RuntimeError("not created: " + ", ".join(empty))
        return "JPG, GIF, WebP"

    runner.run("Create thumbnails", thumbnails)
    runner.run(
        "Create MP3",
        lambda: f"{extract_mp3(clip, temp / 'clip.mp3', ffmpeg).stat().st_size // 1024} KB",
    )
    runner.run("Graphics card", lambda: detect_video_codec(ffmpeg).label, required=False)


def _download_check(runner: _Runner, url: str, folder: Path, required: bool) -> None:
    from local_encoder.downloader import download_video, get_video_info

    def download() -> str:
        info = get_video_info(url)
        target = download_video(url, folder, "download")
        media = probe_media(target, _frozen.resolve_ffprobe())
        if not media.has_video:
            raise RuntimeError(f"{target.name} has no video")
        return f"{str(info.get('title') or target.name)[:60]} ({target.stat().st_size // 1024} KB)"

    runner.run(f"Download {url}", download, required=required)


def passed(checks: list[Check]) -> bool:
    return all(c.ok for c in checks if c.required)
