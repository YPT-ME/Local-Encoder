"""Entry point for PyInstaller frozen executable."""

import os
import sys


def _fix_windowed_streams() -> None:
    """Give the windowed Windows executable usable stdout/stderr.

    The Windows build has no console window (``console=False`` in local-encoder.spec), so
    ``sys.stdout``/``sys.stderr`` start as None and rich/typer/uvicorn would crash on the first
    write. When started from cmd/PowerShell with a command (``LocalEncoder.exe import <url>``),
    attach to that console so the output still appears; otherwise discard the output (the log
    file still records everything). Output that is already redirected (pipes, files) is kept.
    """
    if not (getattr(sys, "frozen", False) and sys.platform == "win32"):
        return
    if sys.stdout is not None and sys.stderr is not None:
        return
    commands = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    wants_console = len(sys.argv) > 1 and commands[:1] != ["serve"]
    stream = None
    if wants_console:
        try:
            import ctypes

            if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
                stream = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        except Exception:
            stream = None
    if stream is None:
        try:
            stream = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            return
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    if sys.stdin is None:
        try:
            sys.stdin = open(os.devnull, encoding="utf-8")
        except OSError:
            pass


if __name__ == "__main__":
    try:
        _fix_windowed_streams()
    except Exception:
        pass

    from local_encoder.cli import app

    # Double-clicking the executable passes no arguments: open the web UI.
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    app()
