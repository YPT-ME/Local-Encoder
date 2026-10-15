"""Shared test setup.

Keeps tests away from the user's real data directory: ``local_encoder.server`` configures
logging at import time, the CLI and the server write job history, and the web UI saves its
settings, all under
``~/.local/share/local-encoder/``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from local_encoder import history, logging_setup, settings

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="local-encoder-tests-"))

logging_setup._LOG_DIR = _TEST_DATA_DIR
logging_setup._LOG_FILE = _TEST_DATA_DIR / "local-encoder.log"
history._HISTORY_FILE = _TEST_DATA_DIR / "history.jsonl"
settings._SETTINGS_FILE = _TEST_DATA_DIR / "settings.json"
