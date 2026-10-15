"""Unit tests for encoder helpers."""

from __future__ import annotations

from local_encoder.encoder import ALLOWED_RESOLUTIONS, ENCODING_SETTINGS, nearest_resolution


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


def test_output_resolution_reads_only_encoder_suffix() -> None:
    from pathlib import Path

    from local_encoder.encoder import output_resolution

    assert output_resolution(Path("My video_720p.mp4")) == 720
    assert output_resolution(Path("Episode_2024_360p.mp4")) == 360
    assert output_resolution(Path("Episode_2024.zip")) is None
    assert output_resolution(Path("clip_123p.mp4")) is None  # not an AVideo resolution
    assert output_resolution(Path("audio.mp3")) is None
