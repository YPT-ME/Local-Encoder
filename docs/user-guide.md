# User guide

[Download Local Encoder](../README.md#download) · [Report a problem](https://github.com/YPT-ME/Local-Encoder/issues)

## Download and open

Choose a download from the README, extract the **whole archive** and keep its files together.

| Computer | Choose | Open |
| --- | --- | --- |
| Windows 10/11 | Windows | Double-click **LocalEncoder.exe** |
| Mac with an Apple M-series chip | Apple Silicon | Double-click **LocalEncoder** |
| Mac with an Intel processor | Intel | Double-click **LocalEncoder** |
| Linux | x64 for Intel/AMD; ARM64 for ARM | Run `./LocalEncoder` in the extracted folder |

On a Mac, **Apple menu → About This Mac** shows the chip or processor.
GitHub's **Code** button and **Source code** archives are for developers.

The browser opens the control page. If it does not, try `http://127.0.0.1:47800`
or open the program again.

### First start warning

The app is not digitally signed yet:

- **Windows:** “Windows protected your PC” → **More info → Run anyway**.
- **macOS:** try opening it, then **System Settings → Privacy & Security → Open Anyway**.

## Connect and send

1. Enter your AVideo **site address**, **user name** and **password**. Click **Connect**.
   Use an account with upload permission.
2. Paste a video link, choose files, drag files onto the page, or select videos from a folder.
   Folder imports mark videos already sent to the current site and read files in place.
3. Optionally set the title, category and description. Leave advanced options at their defaults:
   the app chooses compatible quality and uses your graphics card when available.
4. Click **Add to queue**. After sending, choose **Open video**, **Edit on site** or **Copy link**.

Choose English, Portuguese or Spanish at the top. The app remembers your sites and preferences
on this computer, **never your password**.

## While videos are processing

Keep the computer on. The app prevents sleep while working.
Closing the browser page keeps active jobs running; quitting the app stops them.
The queue survives page reloads, **not an app restart**.

Reopen the page from the icon near the Windows clock, the macOS menu bar, or by opening the
program again. To quit, use **Stop Local Encoder** or the icon's **Quit** menu.
Closing the last page when idle also stops the app.

## Troubleshooting

| Problem | Next step |
| --- | --- |
| Download, conversion or upload failed | Use **Try again**. Keep the original site and account connected; converted files are reused if the site's format and quality settings still match. |
| Need the converted files | Click **Open folder** on the job. |
| Some files could not be added | They stay selected so you can try again. |
| Need support | Click **Report a problem** and attach the generated log file to a [GitHub issue](https://github.com/YPT-ME/Local-Encoder/issues). Passwords are excluded. |

A job completes only after the site confirms it. Failed uploads keep their converted files.

## Open from your AVideo site

Open the downloaded app once. On updated AVideo/Web Encoder sites, **Open Local Encoder**
can then launch it and connect your signed-in account. Review the site, account and video;
click **Add to queue** yourself.

A blocked browser check does not mean the app is missing. Use **Open Local Encoder** or
**Check again**, or open the program directly and sign in. After moving or updating it,
open the new copy once. [Technical details](browser-integration.md).

## Update

When **New version available** appears, download the new package. Let current jobs finish,
quit the old app, extract the new download and open it. Releases track yt-dlp updates.

## AVideo server requirement

Keep the site's **Encoder URL** pointing to a working Web Encoder. Local Encoder prepares
uploads; live previews, recordings and other server-side services still need it.
[Service list](encoder-parity.md#avideo-services-that-still-require-the-web-encoder).
