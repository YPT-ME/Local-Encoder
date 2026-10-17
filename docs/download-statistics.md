# Download statistics

The [Download statistics workflow](../.github/workflows/download-stats.yml) collects GitHub
release asset counters hourly, at minute 23 UTC. It can also be started from **Actions → Download
statistics → Run workflow**. GitHub may delay or skip scheduled runs; observations record their
actual collection time.

## Storage

The workflow creates an independent, data-only [`download-stats` branch](https://github.com/YPT-ME/Local-Encoder/tree/download-stats)
in this repository on its first successful run. Each run commits:

- `latest.json`: the most recent observation, including totals and counts per release and asset.
- `snapshots/YYYY-MM-DD.jsonl`: an append-only daily history, with one observation per line.
- `README.md`: the report GitHub shows on the branch page. It has tables of program downloads per
  version and platform, per UTC day, and for the most recent collection intervals with downloads.

Observations contain UTC timestamps, release IDs/tags, asset IDs/names and cumulative download
counts. `total_downloads` includes all attached assets; `program_downloads` includes only assets
whose names start with `LocalEncoder-`. Published pre-releases are included; drafts are excluded.
No downloader identities, IP addresses or application usage data are collected.

These files are committed to Git rather than retained only as temporary Actions artifacts.
Earlier observations remain available if a release or asset is later deleted from GitHub.
The statistics branch does not contain the application code, and the collector never force-pushes.

## Reading the history

The branch's `README.md` already applies the rules below. Use the snapshots directly only for
other breakdowns.

The first observation is a **baseline**, including downloads that happened before collection
started. To measure subsequent downloads over an interval, subtract an asset's earlier
`download_count` from its later count, matching by asset ID. Group those differences by release
or program package for per-version or per-platform reports.

For example, 10 downloads at 13:23 UTC and 14 at 14:25 UTC means four additional downloads were
observed between those collections. It does not identify the exact download times. A missed run
produces a longer interval rather than a known hourly breakdown.

Do not treat a newly seen asset's initial count as downloads during the last interval: some may
have happened earlier. Do not treat deleted/replaced assets or lower counters as negative
downloads. The GitHub API cannot reconstruct earlier download timestamps, and repeat downloads
or updates are not unique users or installations.

## Enabling collection

Publish the workflow and collector script to the repository's default branch. The hourly
schedule starts there; use **Run workflow** to capture the initial baseline immediately.
The workflow uses the built-in `GITHUB_TOKEN` with `contents: write`; no extra secret or server
is needed. Repository rules must allow that token to create and update `download-stats`.

Concurrent collector runs are serialized. An API or Git failure stops the run instead of
overwriting the remote history. In public repositories, GitHub disables schedules after 60 days
without repository activity; check the Actions page if collection stops.

References: [GitHub release assets API](https://docs.github.com/en/rest/releases/assets),
[scheduled workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
