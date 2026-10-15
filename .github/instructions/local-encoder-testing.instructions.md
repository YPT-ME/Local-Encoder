---
name: "Local Encoder Testing"
description: "Use when writing or changing tests, or when validating any change before calling it done. Covers pytest conventions, mocking HTTP/FFmpeg/yt-dlp, the required checks, and end-to-end testing against the local AVideo Docker site."
applyTo: "tests/**"
---

# Local Encoder — Testing and Validation

## Required Checks (all four must pass — same as CI and CONTRIBUTING.md)

```bash
pytest                    # tests (CI adds --cov=local_encoder)
ruff check .              # lint
ruff format --check .     # formatting (run `ruff format .` to fix)
mypy local_encoder        # strict type-check
```

Run them with the project virtualenv (`.venv`). On Windows: `.venv\Scripts\python -m pytest`,
`.venv\Scripts\ruff`, `.venv\Scripts\mypy`. Report the real output; never claim a check passed
without running it.

CI runs mypy on Linux, where Windows-only APIs (`ctypes.windll`, `os.startfile`, …) do not exist
in the type stubs. When code touches them, put them behind `if sys.platform == "win32":` in the
same function and check every platform: `mypy --platform linux local_encoder` (and `darwin`,
`win32`).

## Unit Test Conventions

- One file per module: `tests/test_<module>.py`. Typed test functions (`-> None`), plain `assert`.
- Group related tests with the existing `# ----` section comments.
- **No network, no real FFmpeg, no real yt-dlp in unit tests.** Mock instead:
  - HTTP to AVideo: `unittest.mock.patch` on `AVideoClient._http` / helper `_mock_response()` as in
    `tests/test_avideo_client.py` (or `pytest-httpx`, already a dev dependency).
  - FFmpeg/FFprobe: patch `subprocess.run` / `subprocess.Popen` in the module under test and
    assert the **argument list** (this is how the command contract with the PHP Encoder is kept).
  - yt-dlp: patch `local_encoder.downloader.yt_dlp.YoutubeDL` as in `tests/test_downloader.py`.
  - FastAPI: `TestClient(app, base_url="http://127.0.0.1:47800", headers={"X-Local-Encoder": "1"})`
    (the default `testserver` host and requests without the header get 403). Isolate global
    state like the `_isolated_state` fixture in `tests/test_server.py` (`_jobs`, `_job_order`,
    `_subscribers`, a fresh `_work_queue` no worker reads, `OUTPUT_DIR`).
  - Web UI: `tests/test_errors.py` checks that every error code has an `err.<code>` text in the
    three languages of `static/i18n.js`. To catch JSX syntax errors without a browser, compile the
    page with the vendored `babel.min.js` in Node.
- Use `tmp_path` for every file the test writes. Never write into the repository or the real
  `~/.local/share/local-encoder/`. `tests/conftest.py` already redirects the log file and the
  history to a temp folder; tests that start jobs must patch `server.OUTPUT_DIR` (the
  `_isolated_output` fixture in `tests/test_server.py` does it).
- When you fix a bug, add a regression test that fails before the fix.
- When you change a request sent to AVideo (fields, endpoint, method), assert the exact fields in a
  test — those fields are a compatibility contract with many AVideo versions.

## End-to-End Testing Against a Real AVideo (manual, required for protocol changes)

Unit tests cannot prove that an AVideo site accepts an upload. Any change to login, registration,
upload, images, notify, formats, resolutions, HLS packaging or server-config detection needs an
end-to-end run.

- Local test site: **https://vlu.me/** — the AVideo Docker stack from `D:\git\htdocs\AVideo\`
  (Streamer at `https://vlu.me/`, PHP Encoder at `https://vlu.me/Encoder/`). The repository is
  bind-mounted into the container (`./` → `/var/www/html/AVideo`, `.compose/encoder` →
  `/var/www/html/AVideo/Encoder`), so PHP edits there are live without rebuilding.
- `vlu.me` resolves to a LAN IP via the hosts file and uses a self-signed/local certificate: pass
  `--ssl-no-verify` (CLI) or untick SSL verification (web UI) when testing against it.
- AVideo treats requests differently by User-Agent: `curl`'s default UA gets `Bot Found [curl]`
  (`$global['stopBotsList']`), and a browser UA gets a 302 to the login page on vlu.me. For manual
  probes of encoder endpoints use an encoder UA: `curl -sk -A "AVideoEncoder test" ...`. If an
  AVideo response is not JSON, print its first bytes before assuming a protocol bug.
- Ask the user for test credentials; never hardcode them, never commit them, never print them.
- Typical run (from this repo):
  ```bash
  local-encoder import "<url or file>" --server https://vlu.me/ --user <user> --password <pass> --ssl-no-verify --format mp4
  local-encoder serve --no-browser  # http://127.0.0.1:47800 (another free port if busy)
  ```
- After the run, verify on the site: the video exists, plays, has the right title/description/
  category, thumbnails (jpg/gif/webp) appear, every expected resolution/format is listed, and the
  status is no longer "encoding". Check `local-encoder logs` and the Streamer logs if something is
  off.
- When a fix also needs a change in AVideo (`D:\git\htdocs\AVideo\`), follow that repository's own
  `AGENTS.md`/`CLAUDE.md`/`.github/copilot-instructions.md` rules for the AVideo side, then re-run
  the end-to-end test here. Remember other AVideo installations will not have that change — the
  Local Encoder must still work (or fail with a clear message) against older versions.

## Packaged Executable

Changes to packaging (`local-encoder.spec`, `scripts/fetch_ffmpeg.py`, `scripts/make_dist.py`,
`local_encoder/_frozen.py`, release workflows) must be checked with a real local build (see
`docs/releasing.md`). Start `dist/LocalEncoder-<platform>/LocalEncoder serve --no-browser`, check that
the page, `/api/version` and the vendored JS load, and run one upload through it. The bundled
FFmpeg is recent (9.x): FFmpeg options must work on both old and new FFmpeg versions; for example
`-vsync` was removed in FFmpeg 9. Validate the workflows with `actionlint`.

## What to Report

State which checks ran and their result, what was tested end-to-end (site, format, resolutions),
and what was **not** verified. For encoding, HLS, upload or protocol changes without an end-to-end
run, say plainly that manual verification against a real AVideo site is still required.
