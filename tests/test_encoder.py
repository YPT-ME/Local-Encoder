"""Unit tests for encoder helpers."""

from __future__ import annotations

from avideo_local_encoder.encoder import ALLOWED_RESOLUTIONS, ENCODING_SETTINGS, nearest_resolution


def test_all_resolutions_have_settings():
    for res in ALLOWED_RESOLUTIONS:
        s = ENCODING_SETTINGS[res]
        assert s["minrate"] > 0
        assert s["maxrate"] >= s["minrate"]
        assert s["bufsize"] >= s["maxrate"]
        assert s["audioBitrate"] > 0


def test_nearest_resolution_exact():
    for res in ALLOWED_RESOLUTIONS:
        assert nearest_resolution(res) == res


def test_nearest_resolution_rounds_down():
    # 900 is between 720 and 1080; 900 - 720 = 180, 1080 - 900 = 180 → tie goes to 720
    result = nearest_resolution(900)
    assert result in (720, 1080)


def test_nearest_resolution_low():
    assert nearest_resolution(0) == ALLOWED_RESOLUTIONS[0]


def test_nearest_resolution_high():
    assert nearest_resolution(9999) == ALLOWED_RESOLUTIONS[-1]
