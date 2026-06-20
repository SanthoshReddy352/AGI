---
name: organize-files
description: >
  Tidy and organize a folder — sort files by type, find duplicates or clutter,
  rename/move files into a sensible structure. Use when the user says "organize",
  "clean up", "sort", or "tidy" a folder like Downloads or Desktop.
platforms: [linux, macos, windows]
version: 1.0.0
category: productivity
metadata:
  hermes:
    tags: [files, productivity, cleanup]
---

# Organize Files

Tidy a cluttered folder safely and transparently.

## When to Use

- The user asks to organize / clean up / sort / tidy a directory.
- A folder (Downloads, Desktop, a project dir) has accumulated loose files.

## Procedure

1. Confirm the target folder. If unspecified, ask or default to `~/Downloads`.
2. Call `list_dir` on it to see what's there before changing anything.
3. For a by-type tidy, call `organize_dir` — it sorts loose files into
   Images / Videos / Audio / Documents / Spreadsheets / Archives / Code / Other.
4. For targeted cleanup, use `find_files` with a glob (e.g. `*.zip`, `*.tmp`)
   then `move_path` / `delete_path` on the matches.
5. Report exactly what moved where (counts per bucket). Never delete without the
   user's go-ahead — deletes are approval-gated for a reason.

## Verification

- You listed the folder BEFORE acting.
- The summary states how many files went to each bucket.
- Nothing was deleted unless the user explicitly approved it.
