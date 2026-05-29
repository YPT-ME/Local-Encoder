"""Tests for the ProgressReporter class."""

from __future__ import annotations

from unittest.mock import patch

from rich.progress import TaskID

from local_encoder.progress import ProgressReporter

# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager_starts_and_stops() -> None:
    reporter = ProgressReporter()
    with patch.object(reporter._progress, "start") as mock_start:
        with patch.object(reporter._progress, "stop") as mock_stop:
            with reporter:
                mock_start.assert_called_once()
            mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# Task lifecycle helpers
# ---------------------------------------------------------------------------


def test_new_task_adds_task() -> None:
    reporter = ProgressReporter()
    with patch.object(reporter._progress, "add_task", return_value=TaskID(0)) as mock_add:
        reporter._new_task("test task", total=100)
    mock_add.assert_called_once_with("test task", total=100)
    assert reporter._task == TaskID(0)


def test_new_task_removes_previous_task() -> None:
    reporter = ProgressReporter()
    reporter._task = TaskID(5)
    with patch.object(reporter._progress, "remove_task") as mock_remove:
        with patch.object(reporter._progress, "add_task", return_value=TaskID(6)):
            reporter._new_task("new task")
    mock_remove.assert_called_once_with(TaskID(5))


# ---------------------------------------------------------------------------
# Download stage
# ---------------------------------------------------------------------------


def test_begin_download_sets_task() -> None:
    reporter = ProgressReporter()
    with patch.object(reporter._progress, "add_task", return_value=TaskID(1)):
        reporter.begin_download("https://example.com/v")
    assert reporter._task == TaskID(1)


def test_on_download_updating() -> None:
    reporter = ProgressReporter()
    reporter._task = TaskID(0)
    with patch.object(reporter._progress, "update") as mock_update:
        reporter.on_download("downloading", 500, 1000)
    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args[1]
    assert call_kwargs["completed"] == 500
    assert call_kwargs["total"] == 1000


def test_on_download_finished() -> None:
    reporter = ProgressReporter()
    reporter._task = TaskID(0)
    with patch.object(reporter._progress, "update") as mock_update:
        reporter.on_download("finished", 1000, 1000)
    call_kwargs = mock_update.call_args[1]
    assert call_kwargs["completed"] == 1000


def test_on_download_no_task_is_noop() -> None:
    reporter = ProgressReporter()
    reporter._task = None
    # Should not raise
    reporter.on_download("downloading", 100, 1000)


# ---------------------------------------------------------------------------
# Encode stage
# ---------------------------------------------------------------------------


def test_begin_encode_sets_task() -> None:
    reporter = ProgressReporter()
    with patch.object(reporter._progress, "add_task", return_value=TaskID(2)):
        reporter.begin_encode("Encoding 720p", total_seconds=300)
    assert reporter._task == TaskID(2)


def test_on_encode_updates_progress() -> None:
    reporter = ProgressReporter()
    reporter._task = TaskID(0)
    with patch.object(reporter._progress, "update") as mock_update:
        reporter.on_encode(150, 300)
    mock_update.assert_called_once_with(TaskID(0), completed=150)


def test_on_encode_zero_total_is_noop() -> None:
    reporter = ProgressReporter()
    reporter._task = TaskID(0)
    with patch.object(reporter._progress, "update") as mock_update:
        reporter.on_encode(0, 0)
    mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# Upload stage
# ---------------------------------------------------------------------------


def test_begin_upload_sets_task() -> None:
    reporter = ProgressReporter()
    with patch.object(reporter._progress, "add_task", return_value=TaskID(3)):
        reporter.begin_upload(1024 * 1024)
    assert reporter._task == TaskID(3)


def test_on_upload_updates_progress() -> None:
    reporter = ProgressReporter()
    reporter._task = TaskID(0)
    with patch.object(reporter._progress, "update") as mock_update:
        reporter.on_upload("uploading", 256, 1024)
    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args[1]
    assert call_kwargs["completed"] == 256


# ---------------------------------------------------------------------------
# Messaging methods (smoke tests — just shouldn't raise)
# ---------------------------------------------------------------------------


def test_info_does_not_raise() -> None:
    reporter = ProgressReporter()
    with patch.object(reporter._progress, "start"), patch.object(reporter._progress, "stop"):
        with reporter:
            reporter.info("some info")


def test_success_does_not_raise() -> None:
    reporter = ProgressReporter()
    with patch.object(reporter._progress, "start"), patch.object(reporter._progress, "stop"):
        with reporter:
            reporter.success("done")


def test_warning_does_not_raise() -> None:
    reporter = ProgressReporter()
    reporter.warning("watch out")


def test_error_does_not_raise() -> None:
    reporter = ProgressReporter()
    reporter.error("something broke")


# ---------------------------------------------------------------------------
# verbose mode
# ---------------------------------------------------------------------------


def test_verbose_mode_accepted() -> None:
    reporter = ProgressReporter(verbose=True)
    assert reporter._verbose is True
