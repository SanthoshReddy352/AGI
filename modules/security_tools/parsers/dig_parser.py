"""Deterministic dig text parser.

The :class:`DigWrapper` runs one ``dig +short`` per requested record
type and concatenates the outputs, inserting a header line of the form
``;; <TYPE> records`` before each block. The parser splits on those
headers and bucketizes each non-blank value under its record type.
"""
from __future__ import annotations

import re
from typing import Any


_HEADER_RE = re.compile(r"^\s*;;\s*([A-Z]+)\s+records\s*$", re.MULTILINE)


def parse_dig_output(raw: bytes | str) -> dict[str, Any]:
    if raw is None:
        return _empty("no dig output")

    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw or ""

    # Find every header position; values for a section run from end-of-header
    # to start-of-next-header (or end of text).
    headers = list(_HEADER_RE.finditer(text))
    if not headers:
        return _empty("no record-type sections found")

    records: dict[str, list[str]] = {}
    for idx, m in enumerate(headers):
        rtype = m.group(1)
        start = m.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
        block = text[start:end]
        values = [v.strip() for v in block.splitlines() if v.strip() and not v.lstrip().startswith(";")]
        records.setdefault(rtype, []).extend(values)

    total = sum(len(v) for v in records.values())
    summary = (
        f"{total} record(s) across "
        f"{sum(1 for v in records.values() if v)} type(s): "
        + ", ".join(f"{k}={len(v)}" for k, v in records.items() if v)
    )

    return {
        "status": "success" if total else "partial",
        "summary": summary,
        "structured_data": {"records_by_type": records},
        "errors": [],
    }


def _empty(reason: str) -> dict[str, Any]:
    return {
        "status": "failure",
        "summary": "no usable dig output",
        "structured_data": {"records_by_type": {}},
        "errors": [reason],
    }
