# First-upload walkthrough

[Watch the video](first-upload.mp4) · [Animated preview](first-upload-preview.webp) · [English captions](first-upload.en.vtt) · [User guide](../user-guide.md#connect-and-send)

[Listen to the OpenAI Cedar voice sample](first-upload-voice-sample.mp3).

The walkthrough demonstrates the real Local Encoder browser interface and a completed upload
to the local AVideo test site, followed by playback in AVideo's embedded player.

| Position | Task |
| --- | --- |
| 0:00 | Identify the connection form and the AVideo site address. |
| 0:18 | Check the connected site, choose Files and add a lesson. |
| 0:33 | Follow progress and wait for the site's confirmation. |
| 1:08 | Check playback on AVideo and review the result before sharing. |

## Capture and editing notes

- Captured on Windows in installed Google Chrome, 2026-11-12, with Local Encoder source `ce6376b` (interface v0.1.0). The demonstration runs from source with isolated application data; it does not test downloading, extracting or opening each platform package.
- The connection screen is recorded without credentials. Sign-in happens off camera; the next chapter starts with an authenticated session. An administrator is used only for this local test. Ordinary accounts with upload permission can use the app.
- The selection segment is slowed to 74% speed for readability. Processing and sending run at their recorded speed. Chapter changes mark the edits; the embedded-player chapter is a separate recording.
- The source lesson and its artwork are original demonstration material. It is a 12-second silent lesson; the English narration belongs to the tutorial, not the uploaded lesson. The AI voiceover uses **Cedar**, exported with the visible Play/Download controls in the official **OpenAI.fm** demo linked from [OpenAI's speech documentation](https://developers.openai.com/api/docs/guides/text-to-speech). Voice direction asks for a warm, confident software demonstration, conversational intonation and natural pauses. [Narration text, voice direction and placement](first-upload-narration.json) are saved for future edits.
- The complete application area is retained in the Local Encoder chapters. The playback chapter uses the real embedded player to exclude unrelated catalogue items, account information and chat.
- Visible captions are included in the MP4, with a separate WebVTT copy. Spoken captions are aligned to locally transcribed Whisper word timings and compared with the intended script; recognition variations such as AVideo/A Video, 99/ninety-nine and Sent/cent are reviewed as transcription differences. Automated transcription is not a substitute for listening. Narration volume is normalized across the film. The header identifies the AI voiceover. The MP4 uses H.264/AAC and fast-start metadata for browser playback; the WebP loops without sound.

## Verification

- Real upload **4938**, **Academy Demo - Publish Your First Lesson**, reached **Sent** and **The video is on your site.** Its title and description matched the inputs. The dedicated demonstration record was then kept **Unlisted**.
- The site stored HLS playlists/segments and JPG, GIF and WebP images. Chrome played the uploaded lesson (12.1 seconds, observed rendition 854 × 480) without a player error. Other platforms/packages, online-source imports and folder uploads were not rerun for this recording.
- The final tutorial played in Chrome, including seeking to the completion chapter. Its video and audio streams decoded without errors; all animated WebP frames decoded. Both were reviewed at a 900-pixel display width, and the README/user-guide relative paths and anchors were checked.
- MP4: **81.87 seconds**, **1000 × 974**, approximately **1.87 MB**. WebP preview: **13 seconds**, **1000 × 974**, approximately **263 KB**, below the 10 MB animation limit. The MP4, WebP and VTT total approximately **2.13 MB**; the optional 14-second MP3 voice sample adds **219 KB**.

The video documents this local test. Processing times, available qualities, upload permission
and viewing-access controls depend on the viewer's computer and AVideo site.
