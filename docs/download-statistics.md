# Download statistics

**[Open the live report →](https://github.com/YPT-ME/Local-Encoder/tree/download-stats)**
Downloads by version, platform, UTC day and collection interval.

[![All release asset downloads](https://img.shields.io/github/downloads/YPT-ME/Local-Encoder/total?style=flat-square&label=total%20downloads)](https://github.com/YPT-ME/Local-Encoder/releases)
[![Latest release downloads](https://img.shields.io/github/downloads/YPT-ME/Local-Encoder/latest/total?style=flat-square&label=latest%20release)](https://github.com/YPT-ME/Local-Encoder/releases/latest)
[![Collector status](https://img.shields.io/github/actions/workflow/status/YPT-ME/Local-Encoder/download-stats.yml?branch=main&style=flat-square&label=collector)](https://github.com/YPT-ME/Local-Encoder/actions/workflows/download-stats.yml)

## Program downloads by platform

These badges count each named program package across releases.

| Platform | Downloads |
| --- | --- |
| Windows x64 | [![Windows downloads](https://img.shields.io/github/downloads/YPT-ME/Local-Encoder/LocalEncoder-windows-x64.zip.svg?style=flat-square&label=Windows&displayAssetName=false)](https://github.com/YPT-ME/Local-Encoder/releases) |
| macOS Apple Silicon | [![macOS ARM64 downloads](https://img.shields.io/github/downloads/YPT-ME/Local-Encoder/LocalEncoder-macos-arm64.zip?style=flat-square&label=macOS%20ARM64&displayAssetName=false)](https://github.com/YPT-ME/Local-Encoder/releases) |
| macOS Intel | [![macOS Intel downloads](https://img.shields.io/github/downloads/YPT-ME/Local-Encoder/LocalEncoder-macos-x64.zip?style=flat-square&label=macOS%20Intel&displayAssetName=false)](https://github.com/YPT-ME/Local-Encoder/releases) |
| Linux x64 | [![Linux x64 downloads](https://img.shields.io/github/downloads/YPT-ME/Local-Encoder/LocalEncoder-linux-x64.tar.gz?style=flat-square&label=Linux%20x64&displayAssetName=false)](https://github.com/YPT-ME/Local-Encoder/releases) |
| Linux ARM64 | [![Linux ARM64 downloads](https://img.shields.io/github/downloads/YPT-ME/Local-Encoder/LocalEncoder-linux-arm64.tar.gz.svg?style=flat-square&label=Linux%20ARM64)](https://github.com/YPT-ME/Local-Encoder/releases) |

## What the numbers mean

- **All assets** (also the README badge): program packages, checksums and attached source archives.
- **Program downloads:** only `LocalEncoder-*` packages.
- **Downloads are not users:** updates and repeat downloads count again.
- **Daily totals are observations:** increases are assigned to the UTC day of the later collection,
  not the exact time of each download. The first collection includes older downloads.
- **Badges and report may differ:** Shields caches API results; the report uses hourly snapshots.
  Deleted assets disappear from current API totals but remain in recorded history.
  GitHub also caches badge images, so a broken image on GitHub may differ from its source SVG.

Sources: [Shields download badges](https://shields.io/badges/git-hub-downloads-all-assets-all-releases)
and [GitHub release assets API](https://docs.github.com/en/rest/releases/assets).

## Collection and data

The [workflow](../.github/workflows/download-stats.yml) runs hourly at minute 23 UTC.
GitHub can delay or skip runs; every snapshot records its actual collection time.
Published pre-releases are included; drafts are excluded. No downloader identities, IP addresses
or app usage data are collected.

| File on the [`download-stats` branch](https://github.com/YPT-ME/Local-Encoder/tree/download-stats) | Contents |
| --- | --- |
| `README.md` | Generated report |
| `latest.json` | Latest totals, release/asset IDs, names and counters |
| `snapshots/YYYY-MM-DD.jsonl` | Append-only observations grouped by UTC day |

For custom analysis, compare counters for the **same asset ID**. A newly seen asset may include
older downloads; lower counters or removed/replaced assets are never negative downloads.
A missed run creates a longer measurement interval.

## Maintainer setup

Publish the workflow and collector to the default branch, then run
**Actions → Download statistics → Run workflow** for the baseline.
The built-in `GITHUB_TOKEN` needs `contents: write` and permission to create/update
`download-stats`; no extra secret or server is needed.

Runs are serialized; API or Git errors stop collection without overwriting remote history.
The collector never force-pushes.
If collection stops, check [Actions](https://github.com/YPT-ME/Local-Encoder/actions/workflows/download-stats.yml):
GitHub may disable public-repository schedules after 60 days without activity.
[Schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
