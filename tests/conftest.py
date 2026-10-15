"""Shared test setup.

Keeps tests away from the user's real data directory: ``local_encoder.server`` configures
logging at import time, and the CLI writes job history, both under
``~/.local/share/local-encoder/``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from local_encoder import history, logging_setup

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="local-encoder-tests-"))

logging_setup._LOG_DIR = _TEST_DATA_DIR
logging_setup._LOG_FILE = _TEST_DATA_DIR / "local-encoder.log"
history._HISTORY_FILE = _TEST_DATA_DIR / "history.jsonl"
