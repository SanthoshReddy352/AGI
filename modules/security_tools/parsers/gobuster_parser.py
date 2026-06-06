"""Deterministic gobuster output parser.

gobuster's ``--format json`` mode emits one JSON object per discovered
result, one per line. Each object looks like::

    {"url":"http://lab.local/admin","status":200,"size":1234}

We collect them into a structured Observation. Tolerant of: blank lines,
trailing whitespace, occasional log lines (skipped), and an empty output
(treated as a valid "no paths discovered" result).
"""
from __future__ import annotations

import json
from typing import Any


def parse_gobuster_json(raw: bytes | str) -> dict[str, Any]:
    if raw is None:
        return _empty("no gobuster output")

    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw or ""

    paths: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_urls: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line parse error: {exc}: {line[:80]!r}")
            continue
        url = str(obj.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        paths.append({
            "url": url,
            "status": int(obj.get("status") or 0),
            "size": int(obj.get("size") or 0),
        })

    status_summary: dict[int, int] = {}
    for p in paths:
        status_summary[p["status"]] = status_summary.get(p["status"], 0) + 1

    summary = (
        f"{len(paths)} path(s) discovered"
        + (f"; status counts: {status_summary}" if status_summary else "")
    )

    return {
        "status": "success",
        "summary": summary,
        "structured_data": {
            "paths": paths,
            "status_counts": status_summary,
        },
        "errors": errors,
    }


def _empty(reason: str) -> dict[str, Any]:
    return {
        "status": "failure",
        "summary": "no usable gobuster output",
        "structured_data": {"paths": [], "status_counts": {}},
        "errors": [reason],
    }
