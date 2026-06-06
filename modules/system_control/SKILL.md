---
name: system_control
description: "File management, screenshots, system volume, and desktop control"
plugin_module: modules/system_control
capabilities:
  - name: open_file
    description: "Open a file with its default application"
    aliases:
      - "open the file"
      - "launch file"
  - name: read_file
    description: "Read and display the contents of a text file"
    aliases:
      - "read the file"
      - "show file contents"
      - "cat the file"
  - name: write_file
    description: "Write text content to a file"
    aliases:
      - "write to file"
      - "save to file"
      - "create file with content"
  - name: take_screenshot
    description: "Take a screenshot of the current screen"
    aliases:
      - "screenshot"
      - "capture screen"
      - "take a picture of the screen"
  - name: set_volume
    description: "Set the system audio volume to a percentage"
    aliases:
      - "change volume"
      - "adjust volume"
      - "volume up"
      - "volume down"
---

# System Control

Provides file I/O, screenshot capture, and system-level desktop control.

## Dependencies

Screenshot (Wayland): requires `python3-gi` + `xdg-desktop-portal-gnome` + `grim`.
```
sudo apt install python3-gi gir1.2-glib-2.0 xdg-desktop-portal-gnome grim
```

## Capabilities

### take_screenshot
**You say:** "Friday, take a screenshot"
**Expected:** File saved to `~/Pictures/FRIDAY_Screenshots/`
**Wrong behaviour:** "Screenshot requires python3-gi" — install the deps above.

### read_file / write_file / open_file
**You say:** "Friday, read ~/Documents/notes.txt"
**Expected:** File contents read aloud / displayed.
