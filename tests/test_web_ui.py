"""Exercise the page's upload and account-selection logic without network or a browser."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the UI checks")
def test_web_ui_upload_recovery() -> None:
    result = subprocess.run(
        ["node", "--test", str(Path(__file__).with_name("web_ui.test.cjs"))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
