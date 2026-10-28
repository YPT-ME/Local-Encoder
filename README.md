# Download statistics

Automatic observations of GitHub release asset counters, collected about hourly.

| Latest observation (UTC) | All release assets | Program packages only |
| --- | --- | --- |
| 2026-10-28T21:44:26.537581Z | 33 | 31 |

## Program downloads per version and platform

Cumulative totals, including downloads before collection began.

| Version | windows-x64 | macos-arm64 | macos-x64 | linux-x64 | linux-arm64 | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| v2.1.2 | 1 | 2 | 0 | 0 | 0 | 3 |
| v2.1.1 | 2 | 0 | 0 | 1 | 0 | 3 |
| v2.1.0 | 6 | 2 | 1 | 3 | 1 | 13 |
| v2.0.0 | 4 | 0 | 0 | 0 | 0 | 4 |
| v1.0.2 | 1 | 0 | 0 | 0 | 0 | 1 |
| v1.0.1 | 1 | 1 | 1 | 0 | 0 | 3 |
| v1.0.0 | 2 | 0 | 0 | 0 | 0 | 2 |
| v0.1.0 | 2 | 0 | 0 | 0 | 0 | 2 |
| **Total** | 19 | 5 | 2 | 4 | 1 | 31 |

## Program downloads per UTC day

Increases between collections, assigned to the day of the later collection.

| Day (UTC) | Downloads | Version and platform |
| --- | ---: | --- |
| Before 2026-10-16 18:51 (time unknown) | 14 | v0.1.0 windows-x64: 2, v1.0.0 windows-x64: 2, v1.0.1 macos-x64: 1, v1.0.1 windows-x64: 1, v1.0.1 macos-arm64: 1, v1.0.2 windows-x64: 1, v2.0.0 windows-x64: 4, v2.1.0 windows-x64: 2 |
| 2026-10-28 | 3 | v2.1.2 macos-arm64: 2, v2.1.2 windows-x64: 1 |
| 2026-10-26 | 1 | v2.1.1 windows-x64: 1 |
| 2026-10-24 | 1 | v2.1.1 windows-x64: 1 |
| 2026-10-23 | 1 | v2.1.1 linux-x64: 1 |
| 2026-10-21 | 2 | v2.1.0 windows-x64: 1, v2.1.0 linux-x64: 1 |
| 2026-10-18 | 5 | v2.1.0 linux-arm64: 1, v2.1.0 windows-x64: 1, v2.1.0 macos-x64: 1, v2.1.0 macos-arm64: 1, v2.1.0 linux-x64: 1 |
| 2026-10-17 | 1 | v2.1.0 linux-x64: 1 |
| 2026-10-16 | 3 | v2.1.0 windows-x64: 2, v2.1.0 macos-arm64: 1 |

## Recent collection intervals with downloads (last 48)

Downloads happened at some moment between the two collection times.

| From (UTC) | To (UTC) | Downloads | Version and platform |
| --- | --- | ---: | --- |
| 2026-10-28 09:50 | 2026-10-28 16:42 | 1 | v2.1.2 macos-arm64: 1 |
| 2026-10-28 02:23 | 2026-10-28 09:50 | 2 | v2.1.2 macos-arm64: 1, v2.1.2 windows-x64: 1 |
| 2026-10-26 06:26 | 2026-10-26 14:23 | 1 | v2.1.1 windows-x64: 1 |
| 2026-10-24 07:24 | 2026-10-24 12:46 | 1 | v2.1.1 windows-x64: 1 |
| 2026-10-22 23:27 | 2026-10-23 05:02 | 1 | v2.1.1 linux-x64: 1 |
| 2026-10-20 23:57 | 2026-10-21 05:00 | 2 | v2.1.0 windows-x64: 1, v2.1.0 linux-x64: 1 |
| 2026-10-18 14:41 | 2026-10-18 18:12 | 5 | v2.1.0 linux-arm64: 1, v2.1.0 windows-x64: 1, v2.1.0 macos-x64: 1, v2.1.0 macos-arm64: 1, v2.1.0 linux-x64: 1 |
| 2026-10-17 14:16 | 2026-10-17 17:18 | 1 | v2.1.0 linux-x64: 1 |
| 2026-10-16 18:51 | 2026-10-16 22:08 | 3 | v2.1.0 windows-x64: 2, v2.1.0 macos-arm64: 1 |

## About the data

- `latest.json`: the most recent observation.
- `snapshots/YYYY-MM-DD.jsonl`: one JSON observation per line, grouped by UTC day.
- Each observation contains release IDs/tags and asset IDs/names with cumulative counts.
- All published releases, including pre-releases, are included; drafts are excluded.
- Program packages are assets whose names start with `LocalEncoder-`.

The first observation is a baseline, including earlier downloads. Compare the same asset ID in successive observations to measure the increase over that interval. A newly seen asset's count may include downloads before collection began; a removed or replaced asset must not be treated as negative downloads.

Collection is scheduled hourly but may be delayed or skipped by GitHub Actions. These are observation timestamps, not the exact times of individual downloads. Repeat downloads and updates count again; no downloader identities are collected.

[Collector workflow](https://github.com/YPT-ME/Local-Encoder/actions/workflows/download-stats.yml)
