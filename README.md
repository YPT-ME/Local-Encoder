# Local Encoder

**Prepare videos on your computer. Publish them to your AVideo site.**

[![Latest release](https://img.shields.io/github/v/release/YPT-ME/Local-Encoder?style=flat-square&label=release)](https://github.com/YPT-ME/Local-Encoder/releases/latest)
[![Latest release downloads](https://img.shields.io/github/downloads/YPT-ME/Local-Encoder/latest/total?style=flat-square&label=latest%20release%20downloads)](https://github.com/YPT-ME/Local-Encoder/releases/latest)
[![Total downloads](https://img.shields.io/github/downloads/YPT-ME/Local-Encoder/total?style=flat-square&label=total%20downloads)](docs/download-statistics.md)

[![CI](https://img.shields.io/github/actions/workflow/status/YPT-ME/Local-Encoder/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/YPT-ME/Local-Encoder/actions/workflows/ci.yml)
[![Release build](https://img.shields.io/github/actions/workflow/status/YPT-ME/Local-Encoder/release.yml?style=flat-square&label=build)](https://github.com/YPT-ME/Local-Encoder/actions/workflows/release.yml)
[![Last code commit](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.github.com%2Frepos%2FYPT-ME%2FLocal-Encoder%2Fcommits%3Fsha%3Dmain%26per_page%3D1&query=%24%5B0%5D.commit.committer.date&style=flat-square&label=last%20commit&color=blue)](https://github.com/YPT-ME/Local-Encoder/commits/main/)
[![License](https://img.shields.io/github/license/YPT-ME/Local-Encoder.svg?style=flat-square)](LICENSE)

Local Encoder is a free, open-source desktop app for [AVideo](https://github.com/WWBN/AVideo),
the platform for running your own video-sharing website. It brings video preparation and
uploading into one place, whether you publish your own videos or manage a site's video library.

Choose a video from your computer or paste a supported video link. Local Encoder prepares it
for playback on your site, creates preview images and uploads the results.
The video processing happens on **your computer**, reducing conversion work on your server.
You follow each step through a page in your browser.

**No programming knowledge is needed.** The download includes the tools required to process videos.

[Download](#download) · [Getting started](#getting-started) · [User guide](docs/user-guide.md) · [For developers](#for-developers)

<img alt="Local Encoder connected to an AVideo site, showing video progress and queue controls" src="https://github.com/user-attachments/assets/ad9b7e29-2e23-4f40-b3ad-1681af772221" />

## What you can do

- **Publish from files, folders or video links.** Select videos on your computer or import from supported sites such as YouTube and Vimeo.
- **Let the app handle video settings.** It checks what your AVideo site accepts and chooses compatible formats and quality levels.
- **Use your computer's processing power.** Hardware acceleration uses your graphics card when available, with processor fallback.
- **Follow progress and recover from upload errors.** See each video move through the queue; **Try again** can reuse converted files after a failed upload.
- **Work in your preferred language.** The interface is available in English, Portuguese and Spanish, and remembers your sites and preferences.

> **For site administrators:** Local Encoder complements the [AVideo Web Encoder](https://github.com/WWBN/AVideo-Encoder).
> Keep your site's **Encoder URL** connected to a working Web Encoder for live previews, recordings
> and other server-side services. [See which services need it](docs/encoder-parity.md#avideo-services-that-still-require-the-web-encoder).

## Download

Choose the version for your computer below. These links download the latest release directly;
you do not need a GitHub account or a separate Python installation.

| Your computer | Download |
| --- | --- |
| Windows 10/11 (64-bit) | **[Windows (.zip)](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-windows-x64.zip)** |
| Mac with Apple chip (M-series) | **[Mac — Apple Silicon (.zip)](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-macos-arm64.zip)** |
| Mac with Intel processor | **[Mac — Intel (.zip)](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-macos-x64.zip)** |
| Linux (Intel/AMD) | **[Linux — x64 (.tar.gz)](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-linux-x64.tar.gz)** |
| Linux (ARM) | **[Linux — ARM64 (.tar.gz)](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-linux-arm64.tar.gz)** |

On a Mac, **Apple menu → About This Mac** shows whether you have an Apple chip or an Intel
processor. [More help choosing and opening the app](docs/user-guide.md#download-and-open).

Use the program downloads above; GitHub's **Code** button and **Source code** archives are for developers.
[All releases and checksums](https://github.com/YPT-ME/Local-Encoder/releases).

## Getting started

Have your **AVideo site address**, an **account with upload permission** and a video ready.
You can use the same user name and password you normally use on your site.

1. **Open Local Encoder.** Extract the whole download and keep its files together.
   On Windows, open **LocalEncoder.exe**; on macOS, open **LocalEncoder**;
   on Linux, run `./LocalEncoder` from the extracted folder.
   Your browser opens the page that controls the app running on your computer.
2. **Connect to your site.** Enter your AVideo address (for example, `https://videos.example.com`),
   user name and password, then click **Connect**. The app checks your account and reads your
   site's video settings.
3. **Add your videos.** Paste a video link, choose files, drag them onto the page or select a folder.
   You can add a title, category and description. Leave advanced options at their defaults to let
   the app choose compatible settings, then click **Add to queue**.

Keep your computer on while the queue runs. You can follow download, conversion and upload progress,
then click **Open video** when your site confirms completion.

**On your first launch**, Windows or macOS may ask you to allow the app because it is not yet
digitally signed. Follow the [opening instructions](docs/user-guide.md#first-start-warning)
if it is blocked.

## Help and documentation

If something goes wrong, the app explains the problem and offers a next step. For upload failures,
**Try again** reuses converted files when the site's format and quality settings still match.
Keep the original site and account connected.

| Looking for… | Start here |
| --- | --- |
| Everyday use, updates or troubleshooting | [User guide](docs/user-guide.md) |
| Help with an error or an idea for improvement | [GitHub issues](https://github.com/YPT-ME/Local-Encoder/issues) — use **Report a problem** in the app to collect logs |
| Opening the app from an AVideo page | [Browser integration](docs/browser-integration.md) |
| Downloads by version, platform and day | [Download statistics](docs/download-statistics.md) |

## For developers

Local Encoder combines a Python media pipeline with a browser interface and a Typer CLI.
FastAPI serves the React/Tailwind UI and streams progress through Server-Sent Events;
yt-dlp handles online sources, FFmpeg processes media, and httpx connects to AVideo.

- **Media:** multi-resolution H.264, AES-128 HLS, MP3 and JPG/GIF/WebP previews, with hardware detection and software fallback.
- **Integration:** site capability detection, chunked uploads, explicit completion checks and browser-to-desktop launch.
- **Quality:** pytest on Linux, Windows and macOS, Ruff, strict mypy and a real FFmpeg self-test in CI.
- **Delivery:** five platform packages with bundled tools, plus automated releases when yt-dlp updates.

Start with [source setup and architecture](docs/development.md).
The [AVideo protocol](docs/avideo-encoder-protocol.md), [feature parity and known limitations](docs/encoder-parity.md)
and [release guide](docs/releasing.md) explain the integration and packaging.
[Contributions are welcome](CONTRIBUTING.md).

## License

Local Encoder is available under the [MIT License](LICENSE). Bundled tools retain their own
licenses, including **FFmpeg (GPL)**. Each download includes third-party notices, and each release
provides the matching FFmpeg source.
