"""Entry point for PyInstaller frozen executable."""

import sys

from local_encoder.cli import app

if __name__ == "__main__":
    # Double-clicking the executable passes no arguments: open the web UI.
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    app()
