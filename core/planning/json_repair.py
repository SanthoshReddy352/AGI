"""Best-effort JSON repair for small-model output.

Qwen3.5-4B with ``response_format={"type":"json_object"}`` is reliable but
not perfect. Common failure modes we can repair without a heavyweight
dependency:

- Surrounding chatter (markdown code fences, prose before/after the
  object).
- Trailing commas.
- Single quotes around keys or string values.
- Python-style ``True``/``False``/``None`` literals.
- ``<think>...</think>`` blocks emitted by reasoning variants.

This module deliberately stays small (no recursive descent parser). When a
specific repair doesn't apply, we leave the input alone — the Pydantic
validator catches structural failures and triggers a retry with error
feedback to the model.
"""
from __future__ import annotations

import json
import re


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_PY_LITERALS = (
    (re.compile(r"(?<!\w)True(?!\w)"), "true"),
    (re.compile(r"(?<!\w)False(?!\w)"), "false"),
    (re.compile(r"(?<!\w)None(?!\w)"), "null"),
)


def repair_and_parse(raw: str) -> dict | list:
    """Return the parsed JSON object, repairing common defects.

    Raises ``ValueError`` if no JSON object/array can be recovered.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty model output")

    # 1. Strip reasoning <think> blocks (Qwen Instruct variants leak these).
    text = _THINK_BLOCK_RE.sub("", text).strip()

    # 2. Prefer the contents of a ```json ... ``` fence if present.
    fence_match = _CODE_FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    # 3. Take the substring from the first opening brace/bracket to the
    #    matching closer at the last position — keeps us robust against
    #    leading prose ("Sure! Here's the JSON:") and trailing fluff.
    text = _slice_to_outermost(text)

    # 4. Fast path: try strict json.loads first.
    for candidate in _candidate_repairs(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise ValueError(f"could not parse JSON after repair: {text[:200]!r}")


def _slice_to_outermost(text: str) -> str:
    """Return the substring from the first '{' or '[' to its matching
    closer at the *outermost* level. If brackets are unbalanced the
    original text is returned (downstream repair may still recover it)."""
    start = -1
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start < 0:
        return text
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def _candidate_repairs(text: str) -> list[str]:
    """Yield repair candidates in increasing order of aggressiveness."""
    out = [text]

    # Trailing commas before } or ]
    no_trailing = _TRAILING_COMMA_RE.sub(r"\1", text)
    if no_trailing != text:
        out.append(no_trailing)

    # Python literals -> JSON literals
    pyfix = no_trailing
    for pat, repl in _PY_LITERALS:
        pyfix = pat.sub(repl, pyfix)
    if pyfix != no_trailing:
        out.append(pyfix)

    # Single quotes -> double quotes (only when no double quotes present —
    # this is the dangerous repair, do it last).
    if '"' not in pyfix and "'" in pyfix:
        out.append(pyfix.replace("'", '"'))

    return out
