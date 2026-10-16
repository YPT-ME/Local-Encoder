LOCAL ENCODER {{VERSION}}
=========================

Local Encoder converts your videos on your own computer and sends them to your AVideo site.
Nothing else needs to be installed: everything it needs (including FFmpeg) is included.

HOW TO START
------------

Windows
  1. Double-click "LocalEncoder.exe".
  2. If Windows shows "Windows protected your PC", click "More info" and then "Run anyway".
     (The program is not digitally signed yet.)
  3. No window opens. Your web browser opens the Local Encoder page by itself, and
     Local Encoder stays in a small blue icon near the clock (bottom-right corner of the
     screen). If you do not see the icon, click the small "^" arrow next to the clock.
       - Click the icon to open the page again.
       - Right-click the icon and choose "Quit" to stop Local Encoder.
     Double-clicking "LocalEncoder.exe" again just opens the page again.
     Windows shows a message near the clock when a video is published or fails.

macOS
  1. Double-click "LocalEncoder". A Terminal window opens.
  2. The first time, macOS may say it cannot verify the developer. Open
     System Settings > Privacy & Security, scroll down and click "Open Anyway"
     next to the "LocalEncoder" message, then open it again.
     (The program is not notarized by Apple yet.)
  3. A blue Local Encoder icon also appears in the menu bar at the top of the screen.
     Use it to open the page again or to quit. Keep the Terminal window open while you use
     Local Encoder; closing it also stops Local Encoder.

Linux
  1. Open a terminal in this folder and run:   ./LocalEncoder
  2. On desktops that show tray icons, a blue Local Encoder icon appears near the clock;
     use it to open the page again or to quit. Keep the terminal open while you use
     Local Encoder; press Ctrl+C there or close it to stop Local Encoder.

Your web browser opens the Local Encoder page by itself. If it does not, click the
Local Encoder icon, or open http://127.0.0.1:47800 (on macOS and Linux the window shows the
exact address if it is different).

While videos are being processed, Local Encoder keeps the computer from going to sleep.
If you choose "Quit" while videos are still being processed, Local Encoder asks you to
choose "Quit" again to confirm.

OPEN FROM AVIDEO
----------------

Opening this package once enables the "Open Local Encoder" button on updated AVideo sites
and Web Encoders for your computer user. Accept the browser prompt if it appears. The
program shows the site and video for you to check; nothing is imported automatically.
Keep the package files together. If you move or update the program, open the new copy
once to refresh browser opening. If the browser cannot detect it, open the program
manually and use "Check again" on the AVideo page. The download option remains available.

USING IT
--------

  1. Type your AVideo site address, your user name and your password, then click "Connect".
  2. Paste a video link or choose a video file, then click import.
  3. When it finishes, the video link on your site is shown.

Updates: when a new version is available, the page shows a "New version available" link.
Download page: https://github.com/YPT-ME/Local-Encoder/releases/latest

FILES AND HELP
--------------

  Work files and logs:  <your user folder>/.local/share/local-encoder/
  Help and issues:      https://github.com/YPT-ME/Local-Encoder/issues

Licenses: Local Encoder is MIT licensed (LICENSE.txt). The included third-party software and
its licenses, including FFmpeg (GPL) and where to get its source code, are listed in
THIRD_PARTY_NOTICES.md and the "licenses" folder.
