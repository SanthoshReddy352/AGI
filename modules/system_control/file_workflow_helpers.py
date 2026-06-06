"""Track 5.2d-retire: pure-function home for the FileWorkflow turn
dispatcher.

The legacy ``core.workflow_orchestrator.FileWorkflow`` was a ~230-line
state machine whose continuation handler dispatched user replies based
on which slot the workflow was parked on (``pending_slots[0]``). The
class is now a 12-line shim that delegates here.

Two public surfaces:

  * :func:`detect_new_filename` — boundary predicate used by the
    workflow's ``can_continue`` AND backs the ``cancel_when:``
    predicate of ``file_create_with_content.yaml`` (Issue 10 mid-flow
    target switch).

  * :func:`handle_file_workflow_turn` — turn dispatcher; the full
    ``_handle`` body relocated. Reads the active workflow state via
    the supplied memory service, processes the user reply against
    whichever slot is pending, persists the next state (or clears it),
    and returns the assistant response. Returns ``None`` when the
    workflow should *release* (let normal routing reparse the turn).

No I/O outside the supplied memory service and the supplied file
controller — pure transformations on strings + dicts.
"""
from __future__ import annotations

import os
import re
from typing import Any

from core.logger import logger


WORKFLOW_NAME = "file_workflow"


def _llm_generate_about(app, topic: str, filename: str) -> str:
    """Call the chat LLM to generate a short document about `topic` (P1.2).

    Returns empty string if the LLM is unavailable; caller falls back to
    writing the topic string verbatim.
    """
    try:
        llm = app.router.get_llm()
        if llm is None or not hasattr(llm, "create_chat_completion"):
            return ""
        ext = filename.rsplit(".", 1)[-1] if "." in filename else "text"
        prompt = f"Write a short {ext} document about: {topic}. Be concise and informative."
        resp = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": "You are a helpful writing assistant. Write concise documents."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=512,
            temperature=0.7,
        )
        if isinstance(resp, dict):
            return (resp.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    except Exception as exc:
        logger.warning("[file_workflow] LLM generation failed: %s", exc)
    return ""

# Issue 10: detect an explicit *new* filename in the user's turn so we
# don't silently apply a "save that" instruction to whatever file the
# stale workflow target happened to point at. Matches "called X.ext",
# "to X.ext", or any bare token ending in a 1-4 char extension.
EXPLICIT_FILENAME_RE = re.compile(
    r"(?:(?:called|named|titled|to|into|in)\s+)?"
    r"\b([A-Za-z0-9_][A-Za-z0-9_\-]*\.[A-Za-z0-9]{1,5})\b"
)

# Issue 4: tiny yes/no parsers for the write-confirmation and dictate-
# or-generate slots. We intentionally accept short conversational
# variants without delegating to the IntentRecognizer — that would
# risk re-routing the answer to a different tool.
_AFFIRMATIVE_TOKENS = frozenset({
    "yes", "yeah", "yep", "yup", "sure", "okay", "ok", "please",
    "do that", "go ahead", "do it", "sounds good", "alright",
})
_NEGATIVE_TOKENS = frozenset({
    "no", "nope", "nah", "not now", "don't", "do not", "skip",
    "leave it", "leave it empty", "thats fine", "that's fine",
})
_BARE_AFFIRM_FOR_PROMPT = {
    "yes", "yeah", "yep", "sure", "okay", "ok", "do that",
    "save that", "write that",
}
_BARE_AFFIRM_FOR_CONTENT = {
    "yes", "yeah", "yep", "sure", "okay", "ok", "do that",
}


def _is_affirmative(text: str) -> bool:
    t = (text or "").strip().lower().rstrip(".!?")
    return t in _AFFIRMATIVE_TOKENS


def _is_negative(text: str) -> bool:
    t = (text or "").strip().lower().rstrip(".!?")
    return t in _NEGATIVE_TOKENS


def detect_new_filename_in_text(user_text: str, active_filename: str) -> str:
    """Return the first explicit filename found in *user_text* when it
    differs from *active_filename* (case-insensitive comparison);
    empty string otherwise.

    Powers two callers: (a) ``can_continue``'s Issue-10 short-circuit
    that releases the workflow on mid-flow target switch, and (b) the
    ``detect_new_filename`` capability registered by
    ``SystemControlPlugin`` for the YAML template's ``cancel_when:``.
    """
    normalized = (user_text or "").strip().lower()
    match = EXPLICIT_FILENAME_RE.search(normalized)
    if not match:
        return ""
    candidate = match.group(1)
    if active_filename and candidate.lower() == active_filename.lower():
        return ""
    return candidate


def can_continue_file_workflow(user_text: str, state: dict | None) -> bool:
    """Return True when the active file workflow should resume on this
    turn. Replicates the legacy ``FileWorkflow.can_continue`` rules:
    drop the workflow when the user names a NEW file; resume when a
    slot is pending or the user said one of the bare-affirm tokens.
    """
    if not state:
        return False
    normalized = (user_text or "").strip().lower()
    active_target = (state.get("target") or {})
    active_filename = (active_target.get("filename") or "")
    if detect_new_filename_in_text(normalized, active_filename):
        return False
    if state.get("pending_slots"):
        return True
    if normalized in _BARE_AFFIRM_FOR_PROMPT:
        return True
    return bool(re.search(
        r"\b(?:save|write|append|add)\s+(?:that|this|it)\b", normalized,
    ))


def _extract_filename(text: str) -> str:
    cleaned = re.sub(r"[^\w.\- ]+", " ", text or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return ""
    return cleaned.strip(" .")


def _start_dictation_into(app, target_path: str, filename: str) -> str | None:
    """Hand off the dictate-content branch (Issue 4) to DictationService."""
    if not target_path:
        return None
    dictation = getattr(app, "dictation_service", None)
    if dictation is None:
        return None
    try:
        label = (filename or "memo").rsplit(".", 1)[0]
        ok, message = dictation.start(label=label, target_path=target_path)
    except TypeError:
        ok, message = dictation.start(label=filename or "memo")
    except Exception as exc:
        logger.warning("[file_workflow] dictation start failed: %s", exc)
        return None
    return message if ok else None


def handle_file_workflow_turn(
    app: Any,
    user_text: str,
    session_id: str,
) -> dict:
    """Dispatch a single resume turn of the file workflow.

    Returns a dict with keys:
      * ``handled`` — bool; False means "release this workflow, let the
        router re-parse the turn"; True means the response is the
        workflow's answer.
      * ``response`` — str; assistant reply when handled.
      * ``state`` — dict; the freshly-persisted workflow state (or {}
        when cleared).
    """
    memory = (
        getattr(app, "memory_service", None) or app.context_store
    )
    workflow_state = (
        memory.get_active_workflow(session_id, workflow_name=WORKFLOW_NAME) or {}
    )
    controller = getattr(app, "file_controller", None)
    if controller is None:
        return {
            "handled": False,
            "response": "File workflow is not available yet.",
            "state": workflow_state,
        }

    pending_slots = list(workflow_state.get("pending_slots") or [])
    target = dict(workflow_state.get("target") or {})
    action = (
        workflow_state.get("action")
        or workflow_state.get("last_action")
        or "create"
    )
    normalized = (user_text or "").strip()
    lower_text = normalized.lower()

    if "filename" in pending_slots:
        filename = _extract_filename(normalized)
        if not filename:
            response = "What should I name the file?"
        else:
            response = controller.manage(
                user_text,
                {
                    "action": action,
                    "filename": filename,
                    "folder": target.get("folder", ""),
                    "extension": target.get("extension", ""),
                },
            )
        return {
            "handled": True, "response": response,
            "state": (
                memory.get_active_workflow(session_id, workflow_name=WORKFLOW_NAME)
                or {}
            ),
        }

    if "write_confirmation" in pending_slots:
        return _handle_write_confirmation(
            app, controller, memory, session_id,
            workflow_state, target, lower_text,
        )

    if "content_source" in pending_slots:
        return _handle_content_source(
            app, controller, memory, session_id,
            workflow_state, target, lower_text, user_text,
        )

    if "content_topic" in pending_slots:
        filename = target.get("filename") or os.path.basename(target.get("path", ""))
        # Generate content via the chat LLM before writing (P1.2 fix).
        generated_body = _llm_generate_about(app, normalized, filename)
        content_to_write = generated_body if generated_body else normalized
        response = controller.manage(
            user_text,
            {
                "action": "write",
                "filename": filename,
                "folder": target.get("folder", ""),
                "extension": target.get("extension", ""),
                "content": content_to_write,
            },
        )
        return {
            "handled": True, "response": response,
            "state": (
                memory.get_active_workflow(session_id, workflow_name=WORKFLOW_NAME)
                or {}
            ),
        }

    if "content" in pending_slots:
        return _handle_content_slot(
            controller, memory, session_id,
            workflow_state, target, action, normalized, lower_text, user_text,
        )

    if (
        re.search(r"\b(?:save|write|append|add)\s+(?:that|this|it)\b", lower_text)
        and target.get("filename")
    ):
        response = controller.manage(
            user_text,
            {
                "action": "append" if "append" in lower_text or "add" in lower_text else "write",
                "filename": target.get("filename"),
                "folder": target.get("folder", ""),
                "extension": target.get("extension", ""),
            },
        )
        return {
            "handled": True, "response": response,
            "state": (
                memory.get_active_workflow(session_id, workflow_name=WORKFLOW_NAME)
                or workflow_state
            ),
        }

    if lower_text in _BARE_AFFIRM_FOR_PROMPT:
        summary = (
            workflow_state.get("result_summary")
            or "I still have the file workflow open."
        )
        return {
            "handled": True, "response": summary, "state": workflow_state,
        }

    return {"handled": False, "response": "", "state": workflow_state}


def _handle_write_confirmation(
    app, controller, memory, session_id,
    workflow_state, target, lower_text,
):
    filename = (
        target.get("filename") or os.path.basename(target.get("path", ""))
    )
    if _is_affirmative(lower_text):
        memory.save_workflow_state(session_id, WORKFLOW_NAME, {
            **workflow_state,
            "pending_slots": ["content_source"],
            "result_summary": f"Awaiting dictate/generate choice for {filename}.",
        })
        return {
            "handled": True,
            "response": "Will you dictate the content, or should I generate it for you?",
            "state": (
                memory.get_active_workflow(session_id, workflow_name=WORKFLOW_NAME)
                or {}
            ),
        }
    if _is_negative(lower_text):
        memory.clear_workflow_state(session_id, WORKFLOW_NAME)
        return {
            "handled": True,
            "response": f"Okay — leaving {filename or 'the file'} empty.",
            "state": {},
        }
    return {"handled": False, "response": "", "state": workflow_state}


def _handle_content_source(
    app, controller, memory, session_id,
    workflow_state, target, lower_text, user_text,
):
    filename = (
        target.get("filename") or os.path.basename(target.get("path", ""))
    )
    target_path = target.get("path", "")
    if any(w in lower_text for w in (
        "dictate", "i'll dictate", "i will dictate", "dictation",
    )):
        response = _start_dictation_into(app, target_path, filename)
        if response is not None:
            memory.clear_workflow_state(session_id, WORKFLOW_NAME)
            return {"handled": True, "response": response, "state": {}}
        return {
            "handled": True,
            "response": "Dictation isn't available right now. Want me to generate instead?",
            "state": workflow_state,
        }
    if any(w in lower_text for w in (
        "generate", "you write", "you do it", "write it for me", "you generate",
    )):
        memory.save_workflow_state(session_id, WORKFLOW_NAME, {
            **workflow_state,
            "pending_slots": ["content_topic"],
            "result_summary": f"Awaiting topic for generated {filename}.",
        })
        return {
            "handled": True,
            "response": f"What topic should I write about for {filename or 'the file'}?",
            "state": (
                memory.get_active_workflow(session_id, workflow_name=WORKFLOW_NAME)
                or {}
            ),
        }
    return {"handled": False, "response": "", "state": workflow_state}


def _handle_content_slot(
    controller, memory, session_id,
    workflow_state, target, action, normalized, lower_text, user_text,
):
    filename = (
        target.get("filename") or os.path.basename(target.get("path", ""))
    )
    if lower_text in _BARE_AFFIRM_FOR_CONTENT:
        return {
            "handled": True,
            "response": f"What would you like me to write in {filename or 'the file'}?",
            "state": workflow_state,
        }
    args = {
        "action": action if action in {"write", "append"} else "write",
        "filename": filename,
        "folder": target.get("folder", ""),
        "extension": target.get("extension", ""),
    }
    if re.search(
        r"\b(?:save|write|append|add)\s+(?:that|this|it|the answer|the response)\b",
        lower_text,
    ):
        response = controller.manage(user_text, args)
    else:
        args["content"] = normalized
        response = controller.manage(user_text, args)
    return {
        "handled": True, "response": response,
        "state": (
            memory.get_active_workflow(session_id, workflow_name=WORKFLOW_NAME)
            or {}
        ),
    }
