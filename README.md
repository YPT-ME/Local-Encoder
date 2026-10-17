# Download statistics

Automatic observations of GitHub release asset counters.

| Latest observation (UTC) | All release assets | Program packages only |
| --- | --- | --- |
| 2026-10-17T00:35:17.938391Z | 17 | 17 |

- `latest.json`: the most recent observation.
- `snapshots/YYYY-MM-DD.jsonl`: one JSON observation per line, grouped by UTC day.
- Each observation contains release IDs/tags and asset IDs/names with cumulative counts.
- All published releases, including pre-releases, are included; drafts are excluded.
- Program packages are assets whose names start with `LocalEncoder-`.

The first observation is a baseline, including earlier downloads. Compare the same asset ID in successive observations to measure the increase over that interval. A newly seen asset's count may include downloads before collection began; a removed or replaced asset must not be treated as negative downloads.

Collection is scheduled hourly but may be delayed or skipped by GitHub Actions. These are observation timestamps, not the exact times of individual downloads. Repeat downloads and updates count again; no downloader identities are collected.

[Collector workflow](https://github.com/YPT-ME/Local-Encoder/actions/workflows/download-stats.yml)
