# Releasing Local Encoder

End users download a ready-to-run program from
[GitHub Releases](https://github.com/YPT-ME/Local-Encoder/releases). Asset names never change,
so `https://github.com/YPT-ME/Local-Encoder/releases/latest/download/<asset>` always points to
the newest version. These are the links used in this README and in the AVideo and AVideo-Encoder
READMEs.

| Asset | Built on (GitHub runner) | FFmpeg |
| --- | --- | --- |
| `LocalEncoder-windows-x64.zip` | `windows-latest` | BtbN GPL build, next to the exe |
| `LocalEncoder-macos-arm64.zip` | `macos-15` | Martin Riedl release build, embedded |
| `LocalEncoder-macos-x64.zip` | `macos-15-intel` | Martin Riedl release build, embedded |
| `LocalEncoder-linux-x64.tar.gz` | `ubuntu-22.04` (older glibc, runs on more distros) | BtbN GPL build, next to the executable |
| `LocalEncoder-linux-arm64.tar.gz` | `ubuntu-22.04-arm` | BtbN GPL build, next to the executable |
| `ffmpeg-source-*` | — | FFmpeg source code matching the bundled builds (GPL) |

Every package also contains the official **deno** binary (MIT, `scripts/fetch_deno.py`). yt-dlp
uses it to solve YouTube's JavaScript challenges; without it, some formats are missing. Like
FFmpeg, deno sits next to the executable on Windows/Linux and is embedded on macOS.
| `SHA256SUMS.txt` | — | Checksums of all assets |

Windows on ARM runs the x64 build through emulation, so it has no separate asset.

## How a release happens

[`.github/workflows/release.yml`](../.github/workflows/release.yml) runs these jobs in order:

1. **version** (job *Decide version*): picks the version in this order:
   - a pushed tag `vX.Y.Z`;
   - the exact version typed in the *Run workflow* form;
   - the next version after the latest release, using the *bump* field (`patch` by default,
     `minor` or `major`): 1.2.3 becomes 1.2.4, 1.3.0 or 2.0.0;
   - for the very first release, the version in `local_encoder/__init__.py`.

   It refuses a version that already exists or is not `X.Y.Z`. The chosen version and the reason
   appear at the top of the run page.
2. **tests**: runs [`ci.yml`](../.github/workflows/ci.yml) on that commit:
   - pytest on Linux (Python 3.11–3.13), Windows and macOS, including the web page checks
     (`tests/test_web_ui.py`: the page compiles, every text exists in English/Portuguese/Spanish,
     and `tests/web_ui.test.cjs`);
   - ruff, and mypy for `linux`, `win32` and `darwin`;
   - `local-encoder selftest` with a real FFmpeg on Linux (MP4, encrypted HLS, thumbnails, MP3).
3. **build** (one job per platform):
   1. stamps the version into `local_encoder/__init__.py` (`scripts/set_version.py`);
   2. installs the app with `packaging/build-constraints.txt`;
   3. downloads the web UI libraries, FFmpeg (`scripts/fetch_ffmpeg.py`) and deno (`scripts/fetch_deno.py`);
   4. builds with PyInstaller (`local-encoder.spec`);
   5. packages it with `scripts/make_dist.py`;
   6. smoke-tests **the package users download** (`scripts/smoke_test.py`), extracted into a
      temporary folder: `--version`; `selftest --require-bundled` (the FFmpeg, FFprobe and deno
      inside the package run, a test clip is converted, the page files are inside, and
      `SMOKE_DOWNLOAD_URL` downloads; YouTube is only tried, on linux-x64, because it often
      blocks datacenter IPs); `serve --no-tray` (page, scripts, `/api/version`, and a request
      without the page header refused); and `serve` in tray mode (a warning only).
      A failure stops the release – also the daily yt-dlp one, so a yt-dlp version that cannot
      download is never shipped.
4. **publish**:
   1. downloads the FFmpeg source code for every bundled FFmpeg build;
   2. writes `SHA256SUMS.txt` and the release notes;
   3. creates the GitHub release and its tag.

Ways to start it:

- **Tag**: `git tag v1.2.3 && git push origin v1.2.3`.
- **Button**: *Actions → Release → Run workflow*. Leave the version empty and choose the increment (patch by default).
- **Automatic**: [`.github/workflows/yt-dlp-update.yml`](../.github/workflows/yt-dlp-update.yml)
  runs every day at 06:17 UTC and compares PyPI's latest yt-dlp with
  `packaging/build-constraints.txt`.
  - When yt-dlp is newer, it commits the new pin to the default branch
    (`chore(deps): update yt-dlp to …`) and calls the release workflow.
  - If the pin is already current but the latest release notes do not list that yt-dlp version
    (because the previous release failed), it releases again.
  - It needs push access to the default branch with `GITHUB_TOKEN`. If branch protection
    blocks bot pushes, allow GitHub Actions to bypass it or change the job to open a PR.

The first release must be started by hand (tag or button). The daily job only releases when a
release already exists or yt-dlp changes.

## Building locally

```bash
pip install -e ".[build]"
python scripts/download_vendor.py
python scripts/fetch_ffmpeg.py windows-x64   # or linux-x64, linux-arm64, macos-arm64, macos-x64
python scripts/fetch_deno.py windows-x64     # same platform names
pyinstaller --noconfirm --clean local-encoder.spec
python scripts/make_dist.py windows-x64      # → dist/LocalEncoder-windows-x64.zip
```

PyInstaller cannot cross-compile, so build each platform on that platform. The Linux x64 build
can be checked from any machine with Docker before pushing. Copy the repository into a
`python:3.12` container and run the same steps as the workflow, with `PYTHONUTF8=1` and
`GH_TOKEN`, ending with `make_dist.py linux-x64` and `scripts/smoke_test.py linux-x64`.

After a local build, `python scripts/smoke_test.py windows-x64` (with `VERSION`,
`SMOKE_DOWNLOAD_URLS` and `SMOKE_TRY_DOWNLOAD_URLS` set like the workflow) runs the same checks.
On Windows the one-file app is a launcher plus a child process: stop it with
`taskkill /T` (the script does), or the child keeps running.

`scripts/download_vendor.py` sends its own User-Agent, because `cdn.tailwindcss.com` answers 403
to Python's default one. It also checks every file's SHA-256. When upgrading a library, update
the URL and the hash together.

Release builds start from a clean checkout, so they download everything again. A file that
already exists in your local `static/vendor` or `bin` is skipped and can hide download problems:
use `download_vendor.py --force` to reproduce a clean build. `bin/`, `build/` and
`dist/` are gitignored.

## Where the app finds FFmpeg and deno (`local_encoder/_frozen.py`)

The order is:

1. the folder of the executable;
2. its `bin/` subfolder;
3. the PyInstaller bundle (macOS);
4. `FFMPEG_BIN`/`FFPROBE_BIN`/`DENO_BIN`;
5. `PATH`.

`downloader._external_tools()` passes the FFmpeg and deno it finds to yt-dlp (`ffmpeg_location`,
`js_runtimes`).

On Windows and Linux FFmpeg is not embedded: the two GPL builds take about 330 MB, and an
embedded copy would be extracted to a temp folder on every start. On macOS it is embedded, so
Gatekeeper asks for permission once for the whole app instead of blocking each downloaded binary.

## Tray icon and the Windows window

`serve` (what a double-click runs) shows a tray icon (`local_encoder/tray.py`, `pystray` +
`Pillow`, icon drawn at runtime) and runs uvicorn in a background thread; the icon loop needs the
main thread on macOS. `--no-tray`, a missing `pystray`, or an icon that cannot start (Linux
without a desktop/AppIndicator, headless CI) fall back to the old blocking console mode.
Starting the app while another copy answers `GET /api/version` on the preferred port only
opens the browser at that copy.

- **Windows** is built with `console=False`, so no black window opens. A windowed executable
  starts with `sys.stdout`/`sys.stderr` set to `None`; `main.py` replaces them before anything
  is imported. For CLI commands typed in cmd/PowerShell (`LocalEncoder.exe import <url>`,
  `--version`) it attaches to the calling console (`AttachConsole(-1)` + `CONOUT$`); cmd does
  not wait for a windowed program, so its prompt may come back before the output ends.
  Redirected output (pipes, files — the release smoke test) is kept as is. A double-click or
  `serve` writes to `os.devnull`; everything still goes to the log file.
- **macOS/Linux** keep `console=True`: the macOS build is a bare executable that Finder opens
  through Terminal, and the Linux build is started from a terminal.
- `hiddenimports` lists the pystray backends (`pystray._win32`, `_darwin`, `_xorg`,
  `_appindicator`, `_gtk`); the Linux build only gets `_xorg` working, because `gi`
  (AppIndicator/GTK) is not bundled. On GNOME without the AppIndicator extension or on pure
  Wayland the icon may not be visible, which is why the Linux console stays.

## Python package licenses (pystray is LGPL-3.0)

`make_dist.py` lists every runtime package of `local-encoder` (following `pyproject.toml`
dependencies) with `pip-licenses`, so `pystray`, `Pillow` (MIT-CMU) and `six` (MIT) appear in
`THIRD_PARTY_NOTICES.md` and `licenses/python-packages.txt` automatically. `pystray` is
**LGPL-3.0**: it is shipped unmodified, and anyone can rebuild the executable with a different
`pystray` from this repository's MIT source, which is what the LGPL asks for a combined work.
Note that `pip-licenses --with-license-file` only copies pystray's `COPYING` (the GPL-3.0
text, also in `licenses/GPL-3.0.txt`), not its `COPYING.LGPL` with the LGPL additional
permissions; ship the LGPL-3.0 text in `packaging/licenses/` so the package is complete. This
is a good-faith setup, not legal advice.

## FFmpeg license (GPL)

The bundled FFmpeg builds are configured with `--enable-gpl --enable-version3`, so they are
GPL-3.0-or-later. They are needed for libx264. Local Encoder (MIT) only runs them as separate
programs and distributes them **unmodified**. Each release does the following:

- Ships `THIRD_PARTY_NOTICES.md` in every download. It lists:
  - the exact `ffmpeg -version`;
  - the build provider and where the binary came from;
  - the build scripts that list every bundled library;
  - the source URL;
  - a written offer to provide the source.
- Ships `licenses/` in every download:
  - GPL-3.0 and GPL-2.0 texts;
  - the build's own `LICENSE.txt`;
  - the license texts of every Python package (`pip-licenses`);
  - the MIT text for the vendored JavaScript.
- Attaches the matching FFmpeg source code to the release (`ffmpeg-source-*`):
  - for a git snapshot build, a GitHub archive of the commit in `ffmpeg -version`;
  - for a tagged build, the `ffmpeg.org` tarball.

If the build providers change (`scripts/fetch_ffmpeg.py`), keep all of this working. Check the
generated `THIRD_PARTY_NOTICES.md` and the release assets. This is the project's good-faith
compliance setup, not legal advice.

## Code signing (not enabled yet)

The executables are unsigned:

- **Windows**: SmartScreen shows "Windows protected your PC" → *More info* → *Run anyway*.
- **macOS**: PyInstaller signs the executable ad-hoc, but it is not notarized. The user has to
  allow it once in *System Settings → Privacy & Security → Open Anyway*.

Both steps are explained in the README and in `README.txt` inside each download.

To sign later:

- **macOS**:
  - Join the Apple Developer Program. A plain Apple ID is not enough to get a *Developer ID
    Application* certificate.
  - Store the certificate (`.p12` + password), the Apple ID, an app-specific password and the
    team ID as repository secrets.
  - Add `codesign --options runtime` and `xcrun notarytool submit --wait` steps to the macOS
    build jobs, after the PyInstaller step and before `make_dist.py`.
- **Windows**: Azure Trusted Signing, or an OV/EV certificate, with a signing step before
  `make_dist.py`.
