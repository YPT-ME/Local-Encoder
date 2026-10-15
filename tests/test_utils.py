"""Unit tests for utility helpers."""

from __future__ import annotations

import re

from local_encoder.utils import generate_file_id, sanitize_filename


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


def test_format_duration_matches_avideo_format() -> None:
    from local_encoder.utils import format_duration

    assert format_duration(0) == "00:00:00"
    assert format_duration(59.6) == "00:01:00"
    assert format_duration(3725) == "01:02:05"
    assert format_duration(-5) == "00:00:00"
    assert format_duration(500 * 3600) == "99:00:00"
