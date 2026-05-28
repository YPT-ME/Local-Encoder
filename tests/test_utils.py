"""Unit tests for utility helpers."""

from __future__ import annotations

import re

from avideo_local_encoder.utils import generate_file_id, sanitize_filename, seconds_to_hms


def test_sanitize_filename_removes_forbidden_chars():
    result = sanitize_filename('foo<bar>:"/\\|?*baz')
    assert "<" not in result
    assert ">" not in result
    assert ":" not in result
    assert "/" not in result
    assert "\\" not in result


def test_sanitize_filename_truncates():
    long_name = "a" * 300
    assert len(sanitize_filename(long_name)) <= 200


def test_sanitize_filename_empty_fallback():
    assert sanitize_filename("") == "video"
    assert sanitize_filename("...") == "video"


def test_generate_file_id_is_hex():
    fid = generate_file_id()
    assert len(fid) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", fid)


def test_generate_file_id_is_unique():
    ids = {generate_file_id() for _ in range(100)}
    assert len(ids) == 100


def test_seconds_to_hms_basic():
    assert seconds_to_hms(0) == "00:00:00.00"
    assert seconds_to_hms(3661.5) == "01:01:01.50"
    assert seconds_to_hms(90) == "00:01:30.00"
