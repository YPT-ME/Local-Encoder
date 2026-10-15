"""Keep the computer from going to sleep while videos are being processed.

Usage::

    from local_encoder import keep_awake

    with keep_awake.inhibit():
        ...  # download, encode, upload

Nested and concurrent ``inhibit()`` blocks share one sleep block: it starts when the first block
is entered and ends when the last one exits. The screen may still turn off; only automatic sleep
is prevented. Nothing here ever raises: if the operating system refuses, the problem is logged
and the work continues.

* Windows: ``SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)``. The setting belongs
  to the thread that made the call, so one dedicated thread sets and clears it.
* macOS: ``caffeinate -i -w <pid>`` (also ends by itself if Local Encoder dies).
* Linux: ``systemd-inhibit --what=sleep:idle ... cat`` when ``systemd-inhibit`` exists. ``cat``
  waits on a pipe from Local Encoder, so the block is released even if Local Encoder is killed.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from typing import Protocol

logger = logging.getLogger(__name__)

REASON = "Local Encoder is processing videos"

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


class _Backend(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class _NoopBackend:
    def start(self) -> None:
        logger.debug("Keep awake: not supported on this system")

    def stop(self) -> None:
        pass


def _set_thread_execution_state(flags: int) -> bool:
    """Call SetThreadExecutionState on the current thread; True on success."""
    if sys.platform != "win32":
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.SetThreadExecutionState.restype = ctypes.c_uint32
    kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
    return bool(kernel32.SetThreadExecutionState(flags))


class _WindowsBackend:
    """Applies the execution state from one long-lived daemon thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._wanted = False
        self._applied = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._request(True)

    def stop(self) -> None:
        self._request(False)

    def _request(self, wanted: bool) -> None:
        with self._lock:
            self._wanted = wanted
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="keep-awake", daemon=True)
                self._thread.start()
        self._wake.set()

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                wanted = self._wanted
            if wanted == self._applied:
                continue
            flags = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if wanted else 0)
            try:
                ok = _set_thread_execution_state(flags)
            except Exception:  # never stop the keep-awake thread
                logger.warning("Keep awake: SetThreadExecutionState failed", exc_info=True)
                ok = False
            if ok:
                logger.debug("Keep awake: sleep %s", "blocked" if wanted else "allowed")
            else:
                logger.warning("Keep awake: Windows refused to change the sleep setting")
            # Remember the request even on failure, so a refusal is not retried in a loop.
            self._applied = wanted


class _ProcessBackend:
    """Keeps a helper program running while sleep must be blocked."""

    def __init__(self, argv: list[str], *, stdin_pipe: bool = False) -> None:
        self._argv = argv
        self._stdin_pipe = stdin_pipe
        self._proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        try:
            self._proc = subprocess.Popen(
                self._argv,
                stdin=subprocess.PIPE if self._stdin_pipe else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.warning("Keep awake: could not start %s: %s", self._argv[0], exc)
            self._proc = None
            return
        logger.debug("Keep awake: started %s (pid %s)", self._argv[0], self._proc.pid)

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Keep awake: could not stop %s: %s", self._argv[0], exc)
        logger.debug("Keep awake: stopped %s", self._argv[0])


def _make_backend(platform: str) -> _Backend:
    if platform == "win32":
        return _WindowsBackend()
    if platform == "darwin":
        caffeinate = shutil.which("caffeinate")
        if caffeinate:
            return _ProcessBackend([caffeinate, "-i", "-w", str(os.getpid())])
        return _NoopBackend()
    if platform.startswith("linux"):
        systemd_inhibit = shutil.which("systemd-inhibit")
        if systemd_inhibit:
            return _ProcessBackend(
                [
                    systemd_inhibit,
                    "--what=sleep:idle",
                    "--who=Local Encoder",
                    f"--why={REASON}",
                    "--mode=block",
                    "cat",
                ],
                stdin_pipe=True,
            )
    return _NoopBackend()


# ---------------------------------------------------------------------------
# Reference counting
# ---------------------------------------------------------------------------


class _Inhibitor:
    def __init__(self, backend: _Backend) -> None:
        self._backend = backend
        self._count = 0
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        return self._count

    def acquire(self) -> None:
        with self._lock:
            self._count += 1
            if self._count == 1:
                self._call(self._backend.start)

    def release(self) -> None:
        with self._lock:
            if self._count == 0:
                return
            self._count -= 1
            if self._count == 0:
                self._call(self._backend.stop)

    def shutdown(self) -> None:
        """Release the sleep block at exit, even if work is still running."""
        with self._lock:
            if self._count > 0:
                self._count = 0
                self._call(self._backend.stop)

    @staticmethod
    def _call(action: Callable[[], None]) -> None:
        try:
            action()
        except Exception:  # keeping awake is best effort
            logger.warning("Keep awake: unexpected error", exc_info=True)


_inhibitor: _Inhibitor | None = None
_inhibitor_lock = threading.Lock()


def _get_inhibitor() -> _Inhibitor:
    global _inhibitor
    with _inhibitor_lock:
        if _inhibitor is None:
            try:
                backend = _make_backend(sys.platform)
            except Exception:
                logger.warning("Keep awake: not available", exc_info=True)
                backend = _NoopBackend()
            _inhibitor = _Inhibitor(backend)
            atexit.register(_inhibitor.shutdown)
        return _inhibitor


@contextlib.contextmanager
def inhibit() -> Iterator[None]:
    """Block automatic sleep while the ``with`` block runs (nestable, thread-safe)."""
    inhibitor = _get_inhibitor()
    inhibitor.acquire()
    try:
        yield
    finally:
        inhibitor.release()
