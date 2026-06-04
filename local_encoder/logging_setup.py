"""Centralised logging configuration for local-encoder.

Log file location: ~/.local/share/local-encoder/local-encoder.log
(same directory as the job history file)

Usage
-----
    from local_encoder.logging_setup import configure_logging
    configure_logging(debug=True)   # call once at startup
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_DIR = Path.home() / ".local" / "share" / "local-encoder"
_LOG_FILE = _LOG_DIR / "local-encoder.log"

_CONSOLE_FORMAT = "%(levelname)s %(name)s: %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging(debug: bool = False, stream=None) -> Path:
    """Set up root logger with a rotating file handler + optional console handler.

    Parameters
    ----------
    debug:
        When *True* the root level is set to DEBUG; otherwise WARNING for
        console output and INFO for the log file.
    stream:
        A writable stream for console output (e.g. ``sys.stderr``).
        Pass ``None`` to suppress console output entirely.

    Returns
    -------
    Path
        Absolute path of the log file so callers can surface it to the user.
    """
    global _configured

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    # Always capture DEBUG+ at the root so the file handler can see everything.
    root.setLevel(logging.DEBUG)

    if _configured:
        return _LOG_FILE

    # ------------------------------------------------------------------
    # Rotating file handler – 5 MB × 3 backups
    # ------------------------------------------------------------------
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(file_handler)

    # ------------------------------------------------------------------
    # Console / stream handler (optional)
    # ------------------------------------------------------------------
    if stream is not None:
        console_handler = logging.StreamHandler(stream)
        console_handler.setLevel(logging.DEBUG if debug else logging.WARNING)
        console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
        root.addHandler(console_handler)

    _configured = True
    logging.getLogger(__name__).info("Logging initialised – file: %s (debug=%s)", _LOG_FILE, debug)
    return _LOG_FILE
