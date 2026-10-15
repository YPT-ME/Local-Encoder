# Third-Party Notices — Local Encoder

Local Encoder is released under the MIT License (see `LICENSE.txt`). The download also
contains the third-party software listed below. Each part stays under its own license.

## FFmpeg (ffmpeg and ffprobe)

This download includes **unmodified** static builds of the FFmpeg command-line tools
`ffmpeg` and `ffprobe`. On Windows and Linux they sit next to the Local Encoder program; on
macOS they are stored inside it. Local Encoder runs them as separate programs. It does not link
to them.

FFmpeg is free software. This build is licensed under the **GNU General Public License**,
because it was configured with `--enable-gpl`. With `--enable-version3` it is GPL version 3
or later. The full license texts are in `licenses/GPL-3.0.txt` and `licenses/GPL-2.0.txt`.
The license file from the build itself, when the build ships one, is in
`licenses/FFmpeg-LICENSE.txt`. FFmpeg is a trademark of Fabrice Bellard, originator of the
FFmpeg project. See https://ffmpeg.org/legal.html.

{{FFMPEG_BUILD_DETAILS}}

### Source code (GPL)

- **FFmpeg source**: the exact FFmpeg source code is in two places:
  - attached to the same GitHub release as this download, as `ffmpeg-source-*`;
  - at the source URL listed above.
- **Build scripts**: the GPL libraries compiled into this build include x264, x265, LAME,
  libvpx, dav1d and others. The scripts that list and fetch the exact versions of those
  libraries are published by the build provider, at the URL listed above.
- **Written offer**: if any of these links stops working, open an issue at
  https://github.com/YPT-ME/Local-Encoder/issues. For at least three years after we
  distributed this version, we will provide the complete corresponding source code at no
  charge other than the cost of delivering it.

## deno (JavaScript runtime)

yt-dlp uses deno to solve the JavaScript challenges of some sites, such as YouTube. On Windows
and Linux the unmodified official deno binary sits next to the Local Encoder program; on macOS
it is stored inside it. deno is MIT licensed, Copyright the Deno authors; see
`licenses/deno-LICENSE.md` and https://github.com/denoland/deno.

{{DENO_BUILD_DETAILS}}

## Python and Python packages

The executable contains a Python runtime (Python Software Foundation License,
https://docs.python.org/3/license.html) and these Python packages:

{{PYTHON_PACKAGES}}

The full license texts of the Python packages are in `licenses/python-packages.txt`.
pystray (the tray icon) is licensed under the GNU LGPL-3.0, which adds permissions to the GPL-3.0
text: see `licenses/LGPL-3.0.txt` and `licenses/GPL-3.0.txt`. Its unmodified source is available at
https://pypi.org/project/pystray/ and https://github.com/moses-palmer/pystray.

The executable is built with PyInstaller. PyInstaller is GPL-2.0 with a special exception
that allows distributing the bundled program under any license
(https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt).

## JavaScript libraries (web interface)

| Library | License | Project |
| --- | --- | --- |
| React, React DOM | MIT — Copyright (c) Meta Platforms, Inc. and affiliates | https://github.com/facebook/react |
| Babel Standalone | MIT — Copyright (c) 2014-present Sebastian McKenzie and other contributors | https://github.com/babel/babel |
| Tailwind CSS | MIT — Copyright (c) Tailwind Labs, Inc. | https://github.com/tailwindlabs/tailwindcss |

The MIT license text is in `licenses/MIT-javascript-libraries.txt`.
