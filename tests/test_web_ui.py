"""Checks on the web page itself: it compiles, every text exists in every language, and its
upload/account logic works (tests/web_ui.test.cjs, run by Node).

A syntax error in static/index.html leaves users with a blank page, and no Python test would
notice. The page is compiled with the vendored Babel in Node (skipped when Node or the vendored
files are missing locally; CI sets LOCAL_ENCODER_REQUIRE_UI_CHECK=1 to make that a failure).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from local_encoder import errors

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "local_encoder" / "static"
INDEX = STATIC / "index.html"
I18N = STATIC / "i18n.js"
BABEL = STATIC / "vendor" / "babel.min.js"
LANGS = ("en", "pt", "es")

_COMPILE = r"""
const fs = require('fs');
const Babel = require(process.argv[1]);
const html = fs.readFileSync(process.argv[2], 'utf8');
const match = html.match(/<script type="text\/babel">([\s\S]*?)<\/script>/);
if (!match) { console.error('no <script type="text/babel"> block'); process.exit(2); }
try { Babel.transform(match[1], { presets: ['react'] }); }
catch (e) { console.error(e.message); process.exit(1); }
"""


def _translations() -> dict[str, dict[str, str]]:
    """Parse i18n.js: one block per language, one `'key': 'text',` per line."""
    result: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in I18N.read_text(encoding="utf-8").splitlines():
        block = re.match(r"^  (\w+): \{$", line)
        if block:
            current = result.setdefault(block.group(1), {})
            continue
        entry = re.match(r"^\s+'([\w.]+)':\s*'(.*)',\s*$", line)
        if entry and current is not None:
            assert entry.group(1) not in current, f"duplicate key {entry.group(1)}"
            current[entry.group(1)] = entry.group(2)
    return result


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", text))


def test_every_language_has_the_same_texts() -> None:
    texts = _translations()
    assert set(texts) == set(LANGS)
    for lang in LANGS[1:]:
        missing = set(texts["en"]) - set(texts[lang])
        extra = set(texts[lang]) - set(texts["en"])
        assert not missing, f"{lang} is missing {sorted(missing)}"
        assert not extra, f"{lang} has unknown keys {sorted(extra)}"


def test_translations_keep_the_placeholders() -> None:
    texts = _translations()
    for key, english in texts["en"].items():
        for lang in LANGS[1:]:
            assert _placeholders(texts[lang][key]) == _placeholders(english), (lang, key)


def test_every_text_used_by_the_page_exists() -> None:
    english = _translations()["en"]
    used = set(re.findall(r"\bt\('([\w.]+)'", INDEX.read_text(encoding="utf-8")))
    assert used, "no t('…') calls found"
    # t('status.' + job.status) and friends: prefixes, checked one by one below.
    prefixes = {key for key in used if key.endswith((".", "_"))}
    assert not sorted(used - prefixes - set(english))
    assert prefixes <= {"status.", "notice.", "folder.place_", "codec.", "err."}
    for status in ("pending", "running", "done", "error", "cancelled", "transfer"):
        assert f"status.{status}" in english, status


def test_every_server_code_has_a_text() -> None:
    english = _translations()["en"]
    for code in errors.MESSAGES:
        assert f"err.{code}" in english, code
    server_source = (ROOT / "local_encoder" / "server.py").read_text(encoding="utf-8")
    notices = set(re.findall(r'"notice", \{"code": "(\w+)"', server_source))
    assert notices, "no notice codes found in server.py"
    notices.add("hw_fallback")  # passed through from encoder.py's notice_callback
    for code in notices:
        assert f"notice.{code}" in english, code
    for key in ("home", "videos", "movies", "desktop", "downloads", "documents"):
        assert f"folder.place_{key}" in english, key


def test_page_compiles() -> None:
    node = shutil.which("node")
    if node is None or not BABEL.is_file():
        if os.environ.get("LOCAL_ENCODER_REQUIRE_UI_CHECK") == "1":
            pytest.fail("Node and local_encoder/static/vendor/babel.min.js are required here")
        pytest.skip("needs Node and `python scripts/download_vendor.py`")
    result = subprocess.run(
        [node, "-e", _COMPILE, str(BABEL), str(INDEX)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_web_ui_upload_recovery() -> None:
    """The page's upload and account-selection logic, run by Node (tests/web_ui.test.cjs)."""
    node = shutil.which("node")
    if node is None:
        if os.environ.get("LOCAL_ENCODER_REQUIRE_UI_CHECK") == "1":
            pytest.fail("Node.js is required here")
        pytest.skip("Node.js is needed for the UI checks")
    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_name("web_ui.test.cjs"))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
