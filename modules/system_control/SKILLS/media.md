---
name: media
description: "ffmpeg / imagemagick recipes for local audio, video, and image manipulation."
source: "hermes-agent skills/media (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - evaluate_code
  - approval
---

# media

## When to use

The user wants to convert, trim, resize, or extract from a local media file. Triggers: "convert this MP4 to MP3", "trim the first 30 seconds off X", "resize the screenshot to 1024×1024", "extract the audio from this video".

All operations run via `evaluate_code(language='bash')`. Long jobs (>30 s) go through the long-running-task primitive (P3.16) so the user can say "stop".

## How to use

Resolve the input path first (DialogState.selected_file or what the user named) then pick the recipe.

### Audio
```bash
# Convert to MP3
ffmpeg -y -i "<in>" -codec:a libmp3lame -qscale:a 2 "<out>.mp3"
# Trim
ffmpeg -y -ss <start> -to <end> -i "<in>" -c copy "<out>"
# Extract from video
ffmpeg -y -i "<in.mp4>" -vn -acodec copy "<out>.aac"
# Normalise loudness
ffmpeg -y -i "<in>" -af loudnorm "<out>"
```

### Video
```bash
# Re-encode to H.264 / AAC
ffmpeg -y -i "<in>" -c:v libx264 -preset medium -crf 22 -c:a aac -b:a 128k "<out>.mp4"
# Resize to width 720, keep aspect
ffmpeg -y -i "<in>" -vf "scale=720:-2" "<out>"
# Make a GIF from a clip
ffmpeg -y -ss <start> -t <dur> -i "<in>" -vf "fps=15,scale=480:-1:flags=lanczos" "<out>.gif"
```

### Images
```bash
# Resize via imagemagick
convert "<in>" -resize 1024x1024 "<out>"
# Convert format
convert "<in>" "<out>.webp"
# Compress JPEG
convert "<in>" -quality 80 "<out>"
```

## Destructive overwrites

If `<out>` would overwrite an existing file, request approval first via `core.approval.request_approval()`. Never silently clobber.

## Examples

- "Friday, convert today's voice memo to MP3."
- "Friday, trim the first 30 seconds off recording.wav."
- "Friday, resize screenshot.png to 1024×1024 and save as avatar.png."

## Common failures and recovery

- **`ffmpeg` not installed** → "Install with `sudo apt install ffmpeg` and try again." Do not silently skip.
- **Input file has no audio stream** → tell the user; do not produce a 0-byte output.
- **Output extension mismatches codec** (e.g. `.mp4` with raw PCM) → fall back to `-c copy` and warn.
