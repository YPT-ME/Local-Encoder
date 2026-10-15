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
| `SHA256SUMS.txt` | — | Checksums of all assets |

Windows on ARM runs the x64 build through emulation, so it has no separate asset.

## How a release happens

[`.github/workflows/release.yml`](../.github/workflows/release.yml) runs these jobs in order:

1. **version**: picks the version from the tag, from the workflow input, or as the next patch
   after the latest release. It refuses a version that already exists.
2. **tests**: runs [`ci.yml`](../.github/workflows/ci.yml) (pytest, ruff, mypy) on that commit.
3. **build** (one job per platform):
   1. stamps the version into `local_encoder/__init__.py` (`scripts/set_version.py`);
   2. installs the app with `packaging/build-constraints.txt`;
   3. downloads the web UI libraries and FFmpeg (`scripts/fetch_ffmpeg.py`);
   4. builds with PyInstaller (`local-encoder.spec`);
   5. smoke-tests the executable: `--version`, then `serve`, the page, `/api/version` and the vendored JS;
   6. packages it with `scripts/make_dist.py`.
4. **publish**:
   1. downloads the FFmpeg source code for every bundled FFmpeg build;
   2. writes `SHA256SUMS.txt` and the release notes;
   3. creates the GitHub release and its tag.

Ways to start it:

- **Tag**: `git tag v1.2.3 && git push origin v1.2.3`.
- **Button**: *Actions → Release → Run workflow*. Leave the version empty for the next patch version.
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
pyinstaller --noconfirm --clean local-encoder.spec
python scripts/make_dist.py windows-x64      # → dist/LocalEncoder-windows-x64.zip
```

PyInstaller cannot cross-compile, so build each platform on that platform. `bin/`, `build/` and
`dist/` are gitignored.

## Where the app finds FFmpeg (`local_encoder/_frozen.py`)

The order is:

1. the folder of the executable;
2. its `bin/` subfolder;
3. the PyInstaller bundle (macOS);
4. `FFMPEG_BIN`/`FFPROBE_BIN`;
5. `PATH`.

On Windows and Linux FFmpeg is not embedded: the two GPL builds take about 330 MB, and an
embedded copy would be extracted to a temp folder on every start. On macOS it is embedded, so
Gatekeeper asks for permission once for the whole app instead of blocking each downloaded binary.

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
