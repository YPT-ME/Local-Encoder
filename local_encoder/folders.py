"""Browse the computer's folders and list the videos in one (the web UI's "Folder" tab).

Local Encoder runs on the user's own computer, so it reads the videos where they are instead of
copying them through the browser. Only folder names and video files are listed; hidden and
system folders are skipped.
"""

from __future__ import annotations

import logging
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from local_encoder.errors import LocalEncoderError

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mkv",
        ".mov",
        ".avi",
        ".webm",
        ".flv",
        ".wmv",
        ".m4v",
        ".mpg",
        ".mpeg",
        ".ts",
        ".mts",
        ".m2ts",
        ".3gp",
        ".ogv",
        ".vob",
    }
)
MAX_FOLDERS = 500
MAX_VIDEOS = 2000
MAX_DEPTH = 6


@dataclass
class VideoFile:
    path: str
    name: str
    rel: str  # path relative to the scanned folder, with "/"
    size: int
    mtime: float


@dataclass
class ScanResult:
    path: str
    videos: list[VideoFile]
    truncated: bool


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def _hidden(entry: os.DirEntry[str]) -> bool:
    if entry.name.startswith((".", "$")) or entry.name in ("System Volume Information",):
        return True
    if sys.platform == "win32":
        try:
            attrs = entry.stat(follow_symlinks=False).st_file_attributes
        except OSError:
            return True
        return bool(attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))
    return False


def _folder(path: str) -> Path:
    """Resolve a folder the user asked for; clear error when it does not exist."""
    raw = path.strip().strip('"')
    folder = Path(raw).expanduser() if raw else Path.home()
    try:
        folder = folder.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LocalEncoderError("folder_not_found", {"path": raw}) from exc
    if not folder.is_dir():
        raise LocalEncoderError("folder_not_found", {"path": raw})
    return folder


def _windows_drives() -> list[Path]:
    import ctypes

    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except (AttributeError, OSError):
        return []
    return [Path(f"{chr(65 + i)}:\\") for i in range(26) if mask & (1 << i)]


def places() -> list[dict[str, str]]:
    """Common starting points: the user's folders, then drives/volumes."""
    home = Path.home()
    result = [{"key": "home", "name": home.name or str(home), "path": str(home)}]
    for key, name in (
        ("videos", "Videos"),
        ("movies", "Movies"),
        ("desktop", "Desktop"),
        ("downloads", "Downloads"),
        ("documents", "Documents"),
    ):
        candidate = home / name
        if candidate.is_dir():
            result.append({"key": key, "name": name, "path": str(candidate)})
    if sys.platform == "win32":
        roots = _windows_drives()
    elif sys.platform == "darwin":
        roots = [p for p in Path("/Volumes").glob("*") if p.is_dir()]
    else:
        roots = [Path("/")]
        for base in (Path("/media") / home.name, Path("/mnt")):
            if base.is_dir():
                roots.extend(p for p in base.iterdir() if p.is_dir())
    result.extend({"key": "drive", "name": str(r), "path": str(r)} for r in roots)
    return result


def browse(path: str) -> dict[str, object]:
    """The sub-folders of *path* (home when empty) and how many videos it holds."""
    folder = _folder(path)
    folders: list[dict[str, str]] = []
    videos = 0
    try:
        with os.scandir(folder) as it:
            for entry in it:
                try:
                    if _hidden(entry):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        folders.append({"name": entry.name, "path": str(folder / entry.name)})
                    elif entry.is_file() and is_video(Path(entry.name)):
                        videos += 1
                except OSError:
                    continue
    except PermissionError as exc:
        raise LocalEncoderError("folder_denied", {"path": str(folder)}) from exc
    folders.sort(key=lambda f: f["name"].lower())
    parent = folder.parent
    return {
        "path": str(folder),
        "parent": str(parent) if parent != folder else None,
        "folders": folders[:MAX_FOLDERS],
        "video_count": videos,
        "places": places(),
    }


def scan(path: str, recursive: bool = False, skip: Path | None = None) -> ScanResult:
    """The video files in *path* (and its sub-folders when *recursive*), sorted by name.

    *skip* is a folder never listed (Local Encoder's own work folder).
    """
    root = _folder(path)
    skip_resolved = skip.resolve() if skip is not None and skip.exists() else None
    videos: list[VideoFile] = []
    truncated = False

    def walk(folder: Path, depth: int) -> None:
        nonlocal truncated
        if skip_resolved is not None and folder == skip_resolved:
            return
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError as exc:
            if folder == root:
                raise LocalEncoderError("folder_denied", {"path": str(folder)}) from exc
            logger.debug("Skipping %s: %s", folder, exc)
            return
        subfolders: list[Path] = []
        for entry in entries:
            if len(videos) >= MAX_VIDEOS:
                truncated = True
                return
            try:
                if _hidden(entry):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    subfolders.append(Path(entry.path))
                elif entry.is_file() and is_video(Path(entry.name)):
                    info = entry.stat()
                    file_path = Path(entry.path)
                    videos.append(
                        VideoFile(
                            path=str(file_path),
                            name=entry.name,
                            rel=file_path.relative_to(root).as_posix(),
                            size=info.st_size,
                            mtime=info.st_mtime,
                        )
                    )
            except OSError:
                continue
        if recursive and depth < MAX_DEPTH:
            for sub in subfolders:
                walk(sub, depth + 1)

    walk(root, 0)
    return ScanResult(path=str(root), videos=videos, truncated=truncated)


def video_file(path: str) -> Path:
    """Validate a file the page asked to import: an existing local video file."""
    candidate = Path(path)
    if not candidate.is_absolute():
        raise LocalEncoderError("file_not_video", {"path": path})
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LocalEncoderError("source_missing") from exc
    if not resolved.is_file() or not is_video(resolved):
        raise LocalEncoderError("file_not_video", {"path": path})
    return resolved
