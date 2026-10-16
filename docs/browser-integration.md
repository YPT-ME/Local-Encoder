# Opening Local Encoder from AVideo

Current packaged versions register `avideo-local-encoder://open` for the current OS user on
startup. Windows uses `HKCU\Software\Classes`, Linux uses an XDG desktop entry and `xdg-mime`,
and macOS uses a small per-user AppleScript application registered with Launch Services.
No administrator permission is required. Source checkouts do not change OS associations
automatically; developers can explicitly run `local-encoder register-browser`.

The association points to the current program location. Keep the extracted files together,
and open a moved or updated copy once to refresh it. Registration failures are logged and do
not stop normal encoding. On Linux, browser opening requires an XDG-compatible desktop with
`xdg-mime`; on macOS it requires the system `osacompile`, `codesign` and Launch Services tools.

## User flow

AVideo and Web Encoder buttons open the current Streamer's Local Encoder page. That page
offers **Open Local Encoder**, **Check again**, and downloads. When reached through an opening
button (`#open=1`), a confirmed running instance opens its control page automatically. When
the program is closed, the native opening button starts it through the OS association.
The browser may ask the user to allow opening the application.

The page probes only loopback ports 47800–47809 using a read-only iframe/message handshake.
Replies must match the exact frame, origin, protocol version and random correlation value.
Discovery exposes no accounts, credentials, saved sites, jobs or local file paths. API CORS and the
existing request-header and local-host protections remain unchanged. Chrome and other browsers
may block local requests or ask for local-network permission; detection is optional.

A timeout means **unconfirmed**, never **not installed**. A browser cannot reliably determine
that an application is installed but closed. The page retains manual opening and downloads
instead of downloading automatically or claiming an installation is absent. Phones and tablets
are directed to use a Windows, macOS or Linux computer.

## Handoff and startup

The native URI accepts only `site` (an HTTP(S) base URL) and optional `url` (an HTTP(S) media URL).
Credentials, local paths, other schemes, duplicate/unknown parameters and oversized links are
rejected. The control page receives these values in a URL fragment and removes the fragment from
its history entry. Without browser authorization it fills the normal site and video fields;
the user signs in there. With authorization it connects the account that authorized the launch.
There is no separate opening/confirmation card. It does not import or
upload automatically, and it never sends a saved account to a different site.

The control page is served without HTML caching, and its translation and handoff scripts use
content-based revision URLs. This prevents a browser from mixing UI code and translations from
different installed versions at the same loopback address.

## Automatic sign-in

Opening from an authenticated AVideo uploader session can sign in without retyping a password.
The Web Encoder uses its own launch page and current Streamer credentials, so this also works
when the browser has no session on the Streamer. Its page reuses the Streamer's launcher asset,
following the Encoder's existing asset-loading pattern. Both server components and the app must
be updated; missing support, expired authorization or blocked discovery falls back to manual login.

For each discovery correlation, the application derives a secret verifier in memory and exposes
only its SHA-256 challenge. The page requests a 120-second, single-use grant through same-origin
POST with the existing CSRF token. The Encoder forwards only its authenticated Streamer's
credentials to that Streamer through a non-redirecting POST; it never sends them to the browser.
AVideo requires either the browser CSRF token or credentials actually verified by its existing
login flow, plus upload permission and the enabled Show Local Encoder setting.

The grant is bound to that proof key, user and password version. AVideo keeps its hash, challenge,
user id and expiry in an installation-specific private temporary directory (no password or reusable
access token). Redemption locks and empties the record atomically, then returns the existing
revocable AVideo login token directly to the application's HTTP client. Password changes and
inactive accounts invalidate outstanding grants. Deployments with multiple PHP hosts need shared
temporary storage or session affinity for this short-lived exchange.

The website sends the grant only by `postMessage` to its exact discovery iframe. The bridge
requires its original parent, origin and correlation before accepting the authorization message,
then POSTs it to the local API with the normal custom header. It acknowledges success only;
it never returns the account, access token or local session id to the website. The control page
claims the result through its same-origin API within 60 seconds. Only the public correlation
travels in its fragment, which is removed immediately; the code, password, verifier and session
id never enter navigation/native URLs. Queued jobs keep their original accounts.

The proof-key construction follows [RFC 7636, S256](https://www.rfc-editor.org/rfc/rfc7636.html).
There is no new general CORS permission, generic bridge proxy, automatic download or automatic job.

A per-user OS file lock serializes process startup. The ready server records its loopback
address and random instance identity atomically in the application data directory; another
start verifies both before reusing it. This also works when the default port is occupied.
Stale records and a different service on a reused port do not count as a running instance.
The lock is released by the OS after a crash, and shutdown only removes its own instance record.

AVideo's `CustomizeAdvanced → Show Local Encoder` setting controls the guide and entry points.
Web Encoder continues to scope links and failed-import sources to the authenticated Streamer.
An older AVideo site without these buttons can still be used normally from the application.
AVideo still needs a working Web Encoder for server-side media services.

## Validation

Unit tests cover link validation, instance identity, stale records, startup locking, OS
registration commands, account isolation and read-only discovery. JavaScript tests cover
spoofed/late messages and the blocked/unavailable detection fallback. Native browser permission
dialogs and OS URL dispatch must also be checked on each target desktop before a release.
The release smoke test checks the packaged discovery assets and, on disposable CI runners,
executes `register-browser` with the real OS tools (Linux requires `xdg-mime`).

References: [Windows URI activation](https://learn.microsoft.com/en-us/windows/apps/develop/launch/handle-uri-activation),
[macOS URL schemes](https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundleurltypes),
[XDG execution rules](https://xdg.pages.freedesktop.org/xdg-specs/desktop-entry/latest/exec-variables.html),
[Chrome local-network access](https://developer.chrome.com/blog/local-network-access).
