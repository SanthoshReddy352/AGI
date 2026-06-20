---
name: play-media
description: >
  Play and control video or music in Namma Agent's browser. Use when the user says
  "play X on YouTube", "put on some music", or asks to pause / resume / skip
  forward / go back / next / previous / fullscreen on what's playing.
platforms: [linux, macos, windows]
version: 1.0.0
category: media
metadata:
  hermes:
    tags: [media, youtube, playback]
---

# Play & Control Media

Namma Agent plays video in a real, controllable browser window — so after starting
playback you can actually pause, seek, and skip.

## When to Use

- "Play <song/video> on YouTube" → start playback.
- "Pause" / "resume" / "skip 50 seconds" / "go back 20" / "next" / "previous" /
  "fullscreen" / "louder" / "stop" → control what's already playing.

## Procedure

1. To start a video: call `play_youtube` with the user's query — it opens the first
   result in the controllable browser and autoplays it fullscreen.
   To start music: call `play_youtube_music` with the song/artist — it plays the
   first track on YouTube Music. (Both use the user's signed-in browser profile.)
2. To control playback (works for both YouTube and YouTube Music), call
   `media_control` with one `action`:
   - `pause` / `play` / `toggle`
   - `forward` with `seconds` (e.g. skip 50s → `{action: forward, seconds: 50}`)
   - `back` with `seconds` (e.g. back 20s → `{action: back, seconds: 20}`)
   - `next` / `previous`
   - `restart` / `stop`
   - `fullscreen`
   - `volume` with `seconds` as 0.0–1.0 (e.g. `{action: volume, seconds: 0.7}`)
3. Confirm briefly what you did (e.g. "Skipped ahead 50 seconds.").

## Verification

- `play_youtube` returned a video title (playback actually started), not just a
  search page.
- Each control request maps to exactly one `media_control` call with the right
  `action`/`seconds`.

## Notes

- If `media_control` reports the controlled browser isn't available, Playwright/
  Chromium isn't installed — tell the user to run `playwright install chromium`.
