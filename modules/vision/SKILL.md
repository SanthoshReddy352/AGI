---
name: vision
description: "Vision capabilities: screen analysis, OCR, image description, UI element finding, and more."
plugin_module: modules/vision
capabilities:
  - name: analyze_screen
    description: "Take a screenshot and describe what's on the screen."
    aliases:
      - "what's on my screen"
      - "analyze my screen"
      - "what do you see"
  - name: describe_image
    description: "Describe an image by file path or public URL."
    aliases:
      - "describe this image"
      - "what is in this image"
      - "analyze this photo"
      - "describe the image at"
  - name: read_text_from_image
    description: "OCR — extract text from a screenshot or image."
    aliases:
      - "read the screen"
      - "extract text from screen"
      - "what does this say"
  - name: summarize_screen
    description: "Give a high-level summary of what's currently on screen."
    aliases:
      - "summarize my screen"
      - "what am I looking at"
  - name: analyze_clipboard_image
    description: "Analyze an image copied to the clipboard."
    aliases:
      - "analyze clipboard"
      - "explain this image"
  - name: find_ui_element
    description: "Find a UI element on screen by description (button, menu, input field)."
    aliases:
      - "where is the button"
      - "find the settings menu"
      - "locate the button"
---

# Vision Module

Uses a local vision-language model (SmolVLM2 / LLaVA) to understand images and your screen.

## Setup

```yaml
# config.yaml — vision section
vision:
  model_path: "models/smolvlm2.gguf"
  mmproj_path: "models/smolvlm2-mmproj.gguf"
```

Or install `llava-1.6` via llama.cpp for the fallback.

## Examples

```
Friday, what's on my screen?
Friday, read the text on my screen
Friday, describe the image at /home/user/diagram.png
Friday, analyze the clipboard image
Friday, where is the save button?
```

## Notes

- All capabilities are latency class `slow` (VLM inference takes 4–15s on CPU).
- `describe_image` downloads public URLs to a temp file before processing.
- `analyze_screen` requires screenshot capability (see `modules/system_control/SKILL.md`).
