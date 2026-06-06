import os
import random
import re

from core.dialog_state import DialogState
from core.logger import logger
from core.model_output import with_no_think_user_message
from core.plugin_manager import FridayPlugin
from .app_launcher import extract_app_names, find_app_candidates, launch_application
from .file_readers import read_file_preview, summarize_file_offline
from .file_search import (
    choose_candidate_from_text,
    extract_extension_from_text,
    format_folder_listing,
    format_search_results,
    list_folder_contents,
    open_file,
    open_folder,
    resolve_folder_path,
    search_files_raw,
    canonicalize_extension,
)
from .file_workspace import WorkspaceFileController
from .brightness import set_brightness
from .media_control import set_volume
from .screenshot import take_screenshot
from .sys_info import get_battery_status, get_cpu_ram_status, get_system_status


_TRIVIAL_KEYWORDS = frozenset({
    "time", "date", "battery", "volume", "weather", "status",
    "cpu", "ram", "memory usage", "temperature", "charging",
    "what time", "what date", "current time", "current date",
    "system status", "friday status", "how's the weather",
})

# Short farewell phrases that should never appear as the resume topic.
_SHUTDOWN_PHRASES = frozenset({
    "goodbye", "bye", "good bye", "goobye", "goodby", "exit", "quit",
    "exit program", "close assistant", "switch off", "see you", "see ya",
    "later", "farewell", "close", "shutdown", "shut down", "stop",
})


def _inject_session_into_context(assistant_context, summary: str, max_turns: int = 8) -> None:
    """Replay the last N turns of a session summary into the live assistant_context history."""
    if not assistant_context or not summary:
        return
    lines = [l.strip() for l in summary.split("\n") if l.strip()]
    # Keep only the most recent max_turns lines to avoid overflowing the context window.
    lines = lines[-max_turns:]
    for line in lines:
        if line.lower().startswith("user:"):
            assistant_context.record_message("user", line[5:].strip(), source="resumed_session")
        elif line.lower().startswith("assistant:"):
            assistant_context.record_message("assistant", line[10:].strip(), source="resumed_session")


def _strip_shutdown_tail(summary: str) -> str:
    """Remove trailing farewell turns so they never surface as the resume topic."""
    lines = [l for l in summary.split("\n") if l.strip()]

    def _is_farewell_user_line(line: str) -> bool:
        if not line.lower().startswith("user:"):
            return False
        user_text = line[5:].strip().lower()
        return user_text in _SHUTDOWN_PHRASES or (
            len(user_text.split()) <= 3
            and any(kw in user_text for kw in ("bye", "goodbye", "exit", "quit", "close", "later", "farewell"))
        )

    while lines:
        last = lines[-1].strip()
        if last.lower().startswith("assistant:") and len(lines) >= 2:
            # If the assistant line follows a user farewell, strip both.
            if _is_farewell_user_line(lines[-2].strip()):
                lines.pop()
                lines.pop()
                continue
        elif _is_farewell_user_line(last):
            lines.pop()
            continue
        break
    return "\n".join(lines)


def _is_trivial_session(context: str) -> bool:
    """Return True if every user turn was a quick status/info query."""
    user_turns = [
        l[5:].strip().lower()
        for l in context.split("\n")
        if l.lower().startswith("user:")
    ]
    if not user_turns:
        return True
    return all(
        len(turn) < 100 and any(kw in turn for kw in _TRIVIAL_KEYWORDS)
        for turn in user_turns
    )


class SystemControlPlugin(FridayPlugin):
    def __init__(self, app):
        super().__init__(app)
        self.name = "SystemControl"
        self.dialog_state = getattr(app, "dialog_state", DialogState())
        self.pending_file_to_open = None
        self.file_controller = WorkspaceFileController(app, self.dialog_state)
        self.app.file_controller = self.file_controller
        self.on_load()

    def on_load(self):
        self.app.register_capability({
            "name": "get_system_status",
            "description": "Report overall system health: CPU usage, RAM usage, and battery level.",
            "parameters": {},
            "context_terms": ["system info", "system information", "system details", "system status"],
        }, lambda t, a: get_system_status())

        self.app.register_capability({
            "name": "get_friday_status",
            "description": "Report FRIDAY runtime status, including model readiness and disabled optional skills.",
            "parameters": {},
            "context_terms": ["friday status", "assistant status", "runtime status", "model status"],
        }, self.handle_friday_status)

        self.app.register_capability({
            "name": "get_battery",
            "description": "Check the current battery percentage and whether it is charging.",
            "parameters": {},
            "context_terms": ["battery", "charge", "power"],
        }, lambda t, a: get_battery_status())

        self.app.register_capability({
            "name": "get_cpu_ram",
            "description": "Show current CPU and RAM usage statistics.",
            "parameters": {},
            "context_terms": ["cpu usage", "ram usage", "memory usage", "performance", "resource usage"],
        }, lambda t, a: get_cpu_ram_status())

        self.app.register_capability({
            "name": "launch_app",
            "description": "Open or launch a desktop application by name (e.g. firefox, chrome, calculator, nautilus).",
            "parameters": {
                "app_name": "string – name of the application to open",
                "app_names": "array[string] – one or more application names to open in order"
            },
            "context_terms": ["browser", "calculator", "chrome", "firefox", "files", "nautilus"],
        }, self.handle_launch_app)

        self.app.register_capability({
            "name": "refresh_app_index",
            "description": "Re-scan installed applications and persist them to the AppIndexStore.",
            "parameters": {},
            "side_effect_level": "write",
            "context_terms": ["rescan apps", "refresh applications", "reindex my apps", "rescan applications"],
        }, self.handle_refresh_app_index)

        # "lock the screen" / "lock my laptop" → real OS session lock
        # (see modules/system_control/os_lock.py). While locked, the
        # capability gate refuses screen-dependent tools (BLOCKED_WHEN_LOCKED);
        # chat/email/research/etc. keep working.
        self.app.register_capability({
            "name": "lock_screen",
            "description": "Lock the computer screen (the real OS/desktop session lock).",
            "parameters": {},
            "side_effect_level": "write",
            "context_terms": ["lock screen", "lock the screen", "lock friday", "lock assistant"],
        }, self.handle_lock_screen)

        self.app.register_capability({
            "name": "unlock_screen",
            "description": "Explain how to unlock the screen (uses your system password).",
            "parameters": {},
            "side_effect_level": "read",
            "context_terms": ["unlock screen", "unlock the screen", "unlock friday", "unlock assistant"],
        }, self.handle_unlock_screen)

        self.app.register_capability({
            "name": "refresh_file_index",
            "description": "Re-scan the user's directories and update the persistent file index.",
            "parameters": {},
            "side_effect_level": "write",
            "context_terms": ["reindex files", "rescan filesystem", "rebuild file index", "refresh file index"],
        }, self.handle_refresh_file_index)

        self.app.register_capability({
            "name": "search_indexed_files",
            "description": "Search the persistent file index by filename. Use for 'where is the file called X'.",
            "parameters": {
                "query": "string – filename or partial name to search",
                "ext": "string – optional extension filter (e.g. pdf, md)",
                "limit": "integer – max results to return (default 20)",
            },
            "context_terms": ["where is", "find the file", "find file", "locate file", "indexed files"],
        }, self.handle_search_indexed_files)

        self.app.register_capability({
            "name": "set_volume",
            "description": "Control system audio volume.",
            "parameters": {
                "direction": "string – one of: 'up', 'down', 'mute', 'unmute'",
                "steps": "integer – number of volume steps to change",
                "percent": "integer – absolute target volume percentage from 0 to 100",
            },
            "context_terms": ["volume", "audio", "sound", "mute", "unmute", "louder", "quieter"],
        }, self.handle_set_volume)

        self.app.register_capability({
            "name": "take_screenshot",
            "description": "Capture the current screen and save it as an image file.",
            "parameters": {},
            "side_effect_level": "write",
        }, self.handle_take_screenshot)

        # 2026-05-23: real brightness handler so LLMChat can't fabricate
        # "Brightness set to 60." with no actual side effect.
        self.app.register_capability({
            "name": "set_brightness",
            "description": "Set the display brightness to a target percentage (0-100).",
            "parameters": {
                "percent": "integer – target brightness from 0 to 100",
            },
            "side_effect_level": "write",
            "context_terms": ["brightness", "set brightness", "dim", "brighter", "dimmer", "darker"],
        }, self.handle_set_brightness)

        self.app.register_capability({
            "name": "search_file",
            "description": "Search for a file by name on the filesystem.",
            "parameters": {
                "filename": "string – the filename or partial name to search for",
                "folder": "string – optional folder name to limit the search",
                "extension": "string – optional extension such as .pdf or .md",
            }
        }, self.handle_search_file)

        self.app.register_capability({
            "name": "manage_file",
            "description": "Create, write, append, or read a text file. You can also save the last assistant answer into a file.",
            "parameters": {
                "action": "string - one of: create, write, append, read",
                "filename": "string - the target filename",
                "folder": "string - optional folder name to place or find the file",
                "content": "string - optional text content to write",
                "extension": "string - optional extension such as .txt or .md",
            }
        }, self.handle_manage_file)

        self.app.register_capability({
            "name": "open_file",
            "description": "Open a specific file using the default application.",
            "parameters": {
                "filename": "string – the filename or partial name to find and open",
                "folder": "string – optional folder name to limit the search",
                "extension": "string – optional extension such as .pdf or .md",
            }
        }, self.handle_open_file)

        self.app.register_capability({
            "name": "read_file",
            "description": "Read or preview the contents of a file.",
            "parameters": {
                "filename": "string – the filename or partial name to read",
                "folder": "string – optional folder name to limit the search",
                "extension": "string – optional extension such as .pdf or .md",
            }
        }, self.handle_read_file)

        self.app.register_capability({
            "name": "summarize_file",
            "description": "Summarize the contents of a file offline.",
            "parameters": {
                "filename": "string – the filename or partial name to summarize",
                "folder": "string – optional folder name to limit the search",
                "extension": "string – optional extension such as .pdf or .md",
            }
        }, self.handle_summarize_file)

        self.app.register_capability({
            "name": "list_folder_contents",
            "description": "List the visible files inside a folder.",
            "parameters": {
                "folder": "string – the folder to inspect"
            }
        }, self.handle_list_folder_contents)

        self.app.register_capability({
            "name": "open_folder",
            "description": "Open a folder in the system file manager.",
            "parameters": {
                "folder": "string – the folder to open"
            }
        }, self.handle_open_folder)

        self.app.register_capability({
            "name": "select_file_candidate",
            "description": "Choose one file from a pending list of candidates.",
            "parameters": {}
        }, self.handle_select_file_candidate)

        self.app.register_capability({
            "name": "confirm_yes",
            "description": "User confirms a pending action (yes, sure, ok, open it).",
            "parameters": {}
        }, self.handle_yes)

        self.app.register_capability({
            "name": "confirm_no",
            "description": "User declines or cancels a pending action (no, nope, cancel).",
            "parameters": {}
        }, self.handle_no)
        
        self.app.register_capability({
            "name": "shutdown_assistant",
            "description": "Close the application and say goodbye.",
            "parameters": {},
            "aliases": ["bye", "goodbye", "good bye", "exit program", "close assistant", "switch off"]
        }, self.handle_shutdown)

        self.app.register_capability({
            "name": "cancel_active_task",
            "description": "Cancel whatever the assistant is currently doing (research, file operation, etc.).",
            "parameters": {},
            "aliases": ["cancel", "stop", "stop that", "never mind", "forget it", "abort", "stop what you are doing"],
        }, self.handle_cancel_active_task)

        # Track 2.1 (Consolidation Direction): deterministic personal-fact
        # store + recall. The intent recognizer routes "my X is Y" /
        # "where do i live" etc. here so facts flow through the
        # MemoryFacade canonical writer/reader without depending on the
        # LLM. The handlers are intentionally short — the facade does
        # the normalization + reconciliation work.
        self.app.register_capability({
            "name": "record_personal_fact",
            "description": "Store a fact about the user (name, location, role, etc.).",
            "parameters": {
                "key": "string – fact key (e.g. 'location', 'name')",
                "value": "string – fact value",
            },
            "side_effect_level": "write",
        }, self.handle_record_personal_fact)

        self.app.register_capability({
            "name": "recall_personal_fact",
            "description": "Recall a stored fact about the user.",
            "parameters": {
                "key": "string – fact key to recall (e.g. 'location')",
            },
        }, self.handle_recall_personal_fact)

        # Port #1: adapter-based cross-OS tools with preflight gating.
        # The preflight checks run once at load time; only available tools
        # are registered so the LLM never picks a tool that won't run.
        self._load_adapter_tools()

        logger.info("SystemControlPlugin loaded.")

    def _load_adapter_tools(self):
        from .preflight import run_all
        from .adapters import get_adapter
        avail = run_all()
        self._platform_adapter = get_adapter()

        if avail["clipboard"].available:
            self.app.register_capability({
                "name": "get_clipboard",
                "description": "Read the current clipboard text content.",
                "parameters": {},
                "context_terms": ["clipboard", "what's in my clipboard", "paste content"],
            }, lambda t, a: self._platform_adapter.clipboard_read())
            self.app.register_capability({
                "name": "set_clipboard",
                "description": "Write text to the system clipboard.",
                "parameters": {"text": "string – text to copy to clipboard"},
                "side_effect_level": "write",
            }, lambda t, a: (self._platform_adapter.clipboard_write(a.get("text", t)) or "Copied to clipboard."))
        else:
            logger.warning("[SystemControl] clipboard unavailable: %s", avail["clipboard"].reason)

        if avail["active_window"].available:
            self.app.register_capability({
                "name": "get_active_window",
                "description": "Return the name and title of the currently focused application window.",
                "parameters": {},
                "context_terms": ["active window", "current window", "what app is open", "focused window"],
            }, lambda t, a: "{} — {}".format(*self._platform_adapter.get_active_window()))
        else:
            logger.warning("[SystemControl] active_window unavailable: %s", avail["active_window"].reason)

        if avail["open_url"].available:
            self.app.register_capability({
                "name": "open_url",
                "description": "Open a URL in the default web browser.",
                "parameters": {"url": "string – the URL to open"},
                "connectivity": "online",
                "side_effect_level": "external",
            }, lambda t, a: (self._platform_adapter.open_url(a.get("url", "")) or "URL opened."))

        self._availability = avail

        # Track 5.2d: capability-backed predicate for the file workflow's
        # `cancel_when:`. Returns truthy when the user's utterance names a
        # different filename than the one the parked workflow is targeting
        # (Issue 10: "save that to reverse.py" while the workflow target
        # is ideas.md must release the workflow rather than silently writing
        # to ideas.md). Wraps the same regex `FileWorkflow._detect_new_filename`
        # uses so YAML templates can reuse the boundary check without
        # depending on the legacy class.
        self.app.register_capability({
            "name": "detect_new_filename",
            "description": (
                "Predicate: True when the user's text names a NEW file "
                "(with extension) that differs from the active workflow's "
                "target filename. Used by file workflow templates' "
                "`cancel_when:` to release on mid-flow target switch."
            ),
            "parameters": {
                "text": "string – the user's current utterance",
                "slots": "object – the workflow's collected slots; honors `slots.filename` if present",
            },
            "side_effect_level": "read",
            "context_terms": [],
        }, self.handle_detect_new_filename)

    _NEW_FILENAME_RE = re.compile(
        r"(?:(?:called|named|titled|to|into|in)\s+)?"
        r"\b([A-Za-z0-9_][A-Za-z0-9_\-]*\.[A-Za-z0-9]{1,5})\b"
    )

    def handle_detect_new_filename(self, text, args):
        """Return True when *text* names a file that differs from the
        active workflow's stored filename (case-insensitive).

        Accepts the standard predicate signature: positional ``text`` plus
        an ``args`` mapping that the compiler passes as
        ``{"text": ..., "slots": {...}}``. When ``slots.filename`` is
        absent we still flag *any* explicit filename in the utterance —
        a freshly-named file mid-flow is still a target switch.
        """
        utterance = (text or "").strip().lower()
        slots = dict((args or {}).get("slots") or {})
        active_filename = (slots.get("filename") or "").strip().lower()
        match = self._NEW_FILENAME_RE.search(utterance)
        if not match:
            return False
        candidate = match.group(1).lower()
        if not active_filename:
            return bool(candidate)
        return candidate != active_filename

    def handle_take_screenshot(self, text, args):
        result = take_screenshot()
        match = re.search(r"at:\s*(.+\.png)", result or "")
        if match:
            self.dialog_state.remember_file(match.group(1).strip())
            return "Screenshot taken."
        return result  # pass error messages through unchanged

    def handle_launch_app(self, text, args):
        app_names = args.get("app_names", [])
        if isinstance(app_names, str):
            app_names = [app_names]

        app_name = args.get("app_name", "")
        # The LLM sometimes returns app_name as a list instead of a string
        if isinstance(app_name, list):
            app_names.extend(app_name)
        elif isinstance(app_name, str) and app_name.strip():
            app_names.append(app_name.strip())

        normalized_names = [name.strip() for name in app_names if isinstance(name, str) and name.strip()]
        if not normalized_names:
            normalized_names = extract_app_names(text)

        if not normalized_names:
            match = re.search(r'(?:open|launch|start|bring up)\s+([a-zA-Z0-9\-\s,]+)', text.lower())
            if match:
                normalized_names = [match.group(1).strip()]
            else:
                return "Which application would you like me to open?"

        # Phase 3 (checkpoint 4): if the spoken name is ambiguous (e.g. "chrom"
        # → Chrome / Chromium), ask which one before launching. Detection runs
        # on the RAW token from the utterance because `extract_app_names`
        # already collapses to a single canonical via fuzzy match. Skipped once
        # the guard re-dispatches with `_picked=True`.
        guard = getattr(self.app, "disambiguation_guard", None)
        if guard is not None and not args.get("_picked"):
            raw_token = self._raw_app_token(text)
            candidates = find_app_candidates(raw_token) if raw_token else []
            if guard.needs_disambiguation(args, candidates):
                return guard.arm(
                    action="launch_app",
                    arg_name="app_names",
                    candidates=[{"label": c, "value": c} for c in candidates],
                    intro=f"There's more than one app like '{raw_token}'. Which one?",
                )

        return launch_application(normalized_names)

    @staticmethod
    def _raw_app_token(text):
        """Extract the bare app name the user spoke after the launch verb."""
        match = re.search(r"\b(?:open|launch|start|bring\s+up)\s+(.+)", (text or "").lower())
        if not match:
            return ""
        tail = re.split(r"\b(?:then|also|after that|please|for me)\b", match.group(1))[0]
        tail = re.sub(r"\b(?:the|my|a|an|app|application)\b", " ", tail)
        return " ".join(tail.split()).strip(" .,!?")

    def handle_refresh_app_index(self, text, args):
        """Track 6.1 — re-probe installed applications and persist them.

        Runs `SystemCapabilities.probe()` so newly-installed apps appear
        in the in-memory registry, then writes the result to
        `AppIndexStore`. The launch_app registry is rebuilt from the
        refreshed capabilities so the next "open <app>" sees them.
        """
        capabilities = getattr(self.app, "capabilities", None)
        if capabilities is None:
            return "App discovery is unavailable on this system."
        capabilities.probe()
        try:
            from modules.system_control.app_launcher import configure_app_registry  # noqa: PLC0415
            configure_app_registry(capabilities)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[SystemControl] app registry refresh failed: %s", exc)
        persist = getattr(self.app, "_persist_app_index", None)
        if callable(persist):
            persist()
        count = len(getattr(capabilities, "desktop_apps", {}) or {})
        return f"Reindexed {count} installed applications."

    def handle_lock_screen(self, text, args):
        """Lock the real OS session (the laptop/desktop screen).

        This is what "lock the screen" / "lock my laptop" means to a user —
        the actual computer locks, requiring the system password to get back
        in. (The separate FRIDAY PIN gate in core/screen_lock.py is a
        tool-gating feature, not the screen lock.)

        Phase 3: guarded by the shared confirmation guard — the first
        "lock the screen" arms a confirmation; the follow-up "yes" runs
        this handler again with ``_confirmed=True`` and locks for real.
        """
        guard = getattr(self.app, "confirmation_guard", None)
        if guard is not None and guard.needs_confirmation(args):
            return guard.arm(action="lock_screen", preview="I'll lock the screen.")
        from modules.system_control.os_lock import lock_os_session  # noqa: PLC0415
        ok, msg = lock_os_session()
        if ok:
            monitor = getattr(self.app, "lock_monitor", None)
            if monitor is not None:
                monitor.note_locked()  # gate + Telegram notice immediately
        return msg

    def handle_unlock_screen(self, text, args):
        # The OS lock screen is unlocked with the user's own system password —
        # there is no safe programmatic unlock. Be honest about that.
        return (
            "I can lock the screen, but unlocking has to be done with your "
            "system password at the lock screen — I can't unlock it for you."
        )

    def handle_refresh_file_index(self, text, args):
        """Track 6.2 — re-walk the user's directories and update the file index."""
        indexer = getattr(self.app, "file_indexer", None)
        if indexer is None:
            return "File indexer is not available on this system."
        count = indexer.scan_once()
        return f"Reindexed {count} files."

    def handle_search_indexed_files(self, text, args):
        """Track 6.2 — look up filenames in the persistent file index."""
        store = getattr(self.app, "file_index_store", None)
        if store is None:
            return "File index is not available on this system."
        query = (args.get("query") or "").strip()
        if not query:
            # Best-effort: pull the noun after "where is / find file"
            match = re.search(
                r"(?:where(?:'s| is)? (?:the )?file(?: called)?|find (?:the )?file(?: called)?|locate (?:the )?file(?: called)?)\s+([\w\-\.\s]+)",
                (text or "").lower(),
            )
            if match:
                query = match.group(1).strip()
        if not query:
            return "What filename should I search for?"
        ext = (args.get("ext") or "").strip()
        try:
            limit = int(args.get("limit") or 10)
        except (TypeError, ValueError):
            limit = 10
        results = store.search(query, limit=limit, ext=ext)
        if not results:
            return f"No indexed files matched '{query}'."

        # Phase 3 (checkpoint 4): more than one match → offer a numbered pick
        # so the follow-up ("the second one", "open report.pdf") opens the
        # chosen file via `open_file`. A single match is just reported.
        guard = getattr(self.app, "disambiguation_guard", None)
        if guard is not None and guard.needs_disambiguation(args, results):
            candidates = [
                {"label": f"{row['name']} — {row['parent_dir']}", "value": row["path"]}
                for row in results
            ]
            return guard.arm(
                action="open_file",
                arg_name="filename",
                candidates=candidates,
                intro=f"I found {len(results)} files matching '{query}'. Which one should I open?",
            )

        lines = [f"Top {len(results)} match{'es' if len(results) != 1 else ''} for '{query}':"]
        for row in results:
            lines.append(f"- {row['name']}  ({row['parent_dir']})")
        return "\n".join(lines)

    def handle_set_brightness(self, text, args):
        """Set display brightness via brightnessctl / light / sysfs."""
        percent = args.get("percent")
        if percent in (None, ""):
            # Best-effort: pull the first percentage-looking number from
            # the user's utterance ("set brightness to 60", "60%").
            import re as _re  # noqa: PLC0415
            match = _re.search(r"(\d{1,3})\s*%?", text or "")
            percent = match.group(1) if match else None
        return set_brightness(percent)

    def handle_set_volume(self, text, args):
        direction = args.get("direction", "").strip().lower()
        steps = args.get("steps", 1)
        percent = args.get("percent")
        try:
            steps = max(1, int(steps))
        except Exception:
            steps = 1
        try:
            percent = None if percent is None else max(0, min(100, int(percent)))
        except Exception:
            percent = None

        text_lower = text.lower()
        if percent is None:
            percent = self._extract_absolute_volume_percent(text_lower)
        if percent is not None:
            return set_volume("absolute", percent=percent)

        if direction not in ("up", "down", "mute", "unmute"):
            step_match = re.search(r'(\d+)\s+(?:times?|steps?|levels?)', text_lower)
            if step_match:
                steps = max(1, int(step_match.group(1)))

            if "unmute" in text_lower:
                direction = "unmute"
            elif "up" in text_lower or "increase" in text_lower or "louder" in text_lower or "raise" in text_lower:
                direction = "up"
            elif "down" in text_lower or "decrease" in text_lower or "quieter" in text_lower or "lower" in text_lower:
                direction = "down"
            elif "mute" in text_lower:
                direction = "mute"
            else:
                return "What volume percentage would you like, or should I turn it up, down, mute, or unmute it?"
        return set_volume(direction, steps=steps)

    def _extract_absolute_volume_percent(self, text_lower):
        patterns = (
            r"\b(?:set|change|make|turn)\s+(?:the\s+)?volume\s+(?:to|at)\s+(\d{1,3})(?:\s*(?:percent|%))?\b",
            r"\bvolume\s+(?:to|at)\s+(\d{1,3})(?:\s*(?:percent|%))?\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                return max(0, min(100, int(match.group(1))))
        return None

    def handle_search_file(self, text, args):
        return self.file_controller.search(text, args)

    def handle_manage_file(self, text, args):
        return self.file_controller.manage(text, args)

    def handle_open_file(self, text, args):
        return self.file_controller.open(text, args)

    def handle_read_file(self, text, args):
        return self.file_controller.read(text, args)

    def handle_summarize_file(self, text, args):
        # When a document is already loaded in session RAG and no explicit file was
        # named, summarize directly from the in-memory chunks instead of asking
        # "Which file would you like me to summarize?" (which ignores the loaded doc).
        session_rag = getattr(self.app, 'session_rag', None)
        if session_rag and session_rag.is_active and not args.get("filename"):
            from .file_readers import _summarize_with_llm, _heuristic_summary
            chunks = session_rag.retrieve(
                "summary key points overview main topics", top_k=8
            )
            combined = "\n\n".join(chunks)
            if combined:
                llm = self.app.router.get_llm() if hasattr(self.app.router, "get_llm") else None
                result = _summarize_with_llm(session_rag.source_name, combined, llm)
                return result or _heuristic_summary(session_rag.source_name, combined)
        return self.file_controller.summarize(text, args)

    def handle_list_folder_contents(self, text, args):
        return self.file_controller.list_folder(text, args)

    def handle_open_folder(self, text, args):
        return self.file_controller.open_folder(text, args)

    def handle_select_file_candidate(self, text, args):
        return self.file_controller.select_candidate(text, args)

    def handle_yes(self, text, args):
        # If FRIDAY asked about resuming a previous session at startup, handle it here.
        # (The intent recognizer routes bare "yes/yeah/sure" to confirm_yes before the
        # LLM can ever match the resume_session capability description.)
        if hasattr(self.app, "context_store"):
            try:
                facts = {f["key"]: f["value"]
                         for f in self.app.context_store.get_facts_by_namespace("system")}
                if facts.get("has_pending_session") == "true":
                    summary = facts.get("last_session_summary", "")
                    self.app.context_store.store_fact("has_pending_session", "", namespace="system")
                    self.app.context_store.store_fact("last_session_summary", "", namespace="system")
                    if summary:
                        # Store the resumed context as a fact so build_chat_messages
                        # can inject it into every subsequent query without touching
                        # the live history (which would break message alternation).
                        self.app.context_store.store_fact(
                            "resumed_session_context", summary, namespace="system"
                        )
                        lines = [l.strip() for l in summary.split("\n") if l.strip()]
                        for line in reversed(lines):
                            if line.lower().startswith("user:"):
                                topic = line[5:].strip()
                                if topic.lower() in _SHUTDOWN_PHRASES:
                                    continue
                                topic = (topic[:70] + "…") if len(topic) > 70 else topic
                                return f"Picking up where we left off, sir. You were asking: \"{topic}\". Go ahead."
                    return "Back on track, sir. What would you like to do?"
            except Exception as e:
                logger.error(f"[handle_yes] Session resume check failed: {e}")
        return self.file_controller.confirm_yes(text, args)

    def handle_no(self, text, args):
        # Parallel check: if FRIDAY asked about resuming a session, "no" means fresh start.
        if hasattr(self.app, "context_store"):
            try:
                facts = {f["key"]: f["value"]
                         for f in self.app.context_store.get_facts_by_namespace("system")}
                if facts.get("has_pending_session") == "true":
                    self.app.context_store.store_fact("has_pending_session", "", namespace="system")
                    self.app.context_store.store_fact("last_session_summary", "", namespace="system")
                    self.app.context_store.store_fact("resumed_session_context", "", namespace="system")
                    return random.choice([
                        "Of course, sir. Fresh start — how can I help you today?",
                        "Sure thing, sir. New session. What can I do for you?",
                        "Right, sir. Clean slate. Go ahead.",
                    ])
            except Exception as e:
                logger.error(f"[handle_no] Session dismiss check failed: {e}")
        return self.file_controller.confirm_no(text, args)

    def handle_cancel_active_task(self, text, args):
        # Signal the interrupt bus first so research, workflows, and dialog-
        # state all reset before we cancel the task-runner thread.
        try:
            from core.interrupt_bus import get_interrupt_bus  # noqa: PLC0415
            get_interrupt_bus().signal("user_cancel", scope="all")
        except Exception:
            pass

        cancelled = self.app.cancel_current_task(announce=True)
        return "Cancelled." if cancelled else "Nothing to cancel, sir."

    def handle_record_personal_fact(self, text, args):
        """Track 2.1: store a personal fact via the canonical
        MemoryFacade. Returns a short confirmation so the user knows the
        fact landed; the facade handles normalization + reconciliation."""
        key = (args.get("key") or "").strip().lower()
        value = (args.get("value") or "").strip()
        if not key or not value:
            return "I didn't catch what to remember."
        facade = self._memory_facade()
        if facade is None:
            return "I can't remember things right now."
        session_id = getattr(self.app, "session_id", "")
        if not session_id:
            return "I can't remember things right now."
        fact = facade.remember(session_id, key, value, source="user")
        if not fact.value:
            return "I didn't catch what to remember."
        # Use the canonical value the facade returned (may differ from the
        # input when the alias map kicks in or a prior spelling won).
        return f"Got it — {key} is {fact.value}."

    def handle_recall_personal_fact(self, text, args):
        """Track 2.1: recall a personal fact via the canonical
        MemoryFacade. Falls back to the facts table when the facade
        hasn't indexed the fact (e.g. onboarding-store facts that
        haven't been mirrored to memory_items yet)."""
        key = (args.get("key") or "").strip().lower()
        if not key:
            return "What would you like me to recall?"
        facade = self._memory_facade()
        if facade is None:
            return "I can't recall things right now."
        session_id = getattr(self.app, "session_id", "")
        if not session_id:
            return "I can't recall things right now."
        facts = facade.recall(session_id, key=key)
        if facts:
            return f"Your {key} is {facts[0].value}."
        # Fallback to facts table: onboarding writes via store_fact(),
        # which populates the facts table but not memory_items.
        ctx = getattr(self.app, "context_store", None)
        if ctx is not None:
            try:
                stored = ctx.get_facts_by_namespace("user_profile") or []
                for f in stored:
                    if f.get("key") == key and f.get("value"):
                        val = f["value"]
                        # Skip raw CapabilityExecutionResult repr strings
                        # (legacy onboarding data from before template fix).
                        if val.startswith("CapabilityExecutionResult(") or val.startswith("CapabilityResult("):
                            continue
                        return f"Your {key} is {val}."
            except Exception:
                pass
        return f"I don't know your {key} yet — tell me and I'll remember."

    def _memory_facade(self):
        """Return the canonical MemoryFacade if the app has a memory_broker
        wired (production) — None for the minimal test apps that bypass it."""
        broker = getattr(self.app, "memory_broker", None)
        return getattr(broker, "facts", None) if broker else None

    def handle_shutdown(self, text, args):
        """Signal the system to perform a clean shutdown — fast, no LLM call on exit.

        Phase 3: guarded by the confirmation guard — shutting down ends the
        session, so the first "shut down"/"goodbye" asks for confirmation and
        the follow-up "yes" runs this for real.
        """
        guard = getattr(self.app, "confirmation_guard", None)
        if guard is not None and guard.needs_confirmation(args):
            return guard.arm(action="shutdown_assistant", preview="I'll shut down.")
        import threading
        import time

        session_id = getattr(self.app.router, "session_id", None)

        farewell_phrases = [
            "Goodbye sir.",
            "Powering down, sir.",
            "Shutting down, sir.",
            "See you next time, sir.",
            "Bye sir.",
        ]
        farewell = random.choice(farewell_phrases)

        # Save session state for the next startup greeting — no LLM, just store the facts.
        if session_id and hasattr(self.app, "context_store"):
            try:
                summary = self.app.context_store.summarize_session(session_id, limit=20)
                summary = _strip_shutdown_tail(summary or "")
                turn_lines = [l for l in summary.split("\n")
                              if l.lower().startswith(("user:", "assistant:"))]
                if len(turn_lines) >= 4 and not _is_trivial_session(summary):
                    self.app.context_store.store_fact("last_session_summary", summary, namespace="system")
                    self.app.context_store.store_fact("has_pending_session", "true", namespace="system")
                    self.app.context_store.store_fact(
                        "next_startup_greeting",
                        "{time_greeting}, sir. Want to pick up where we left off?",
                        namespace="system",
                    )
            except Exception as e:
                logger.error(f"[handle_shutdown] Session save failed: {e}")

        # Allow just enough time for TTS to finish saying the short farewell.
        sleep_time = max(1.2, len(farewell.split()) / 2.5 + 0.6)

        def _trigger_shutdown():
            time.sleep(sleep_time)
            self.app.event_bus.publish("system_shutdown", {})

        threading.Thread(target=_trigger_shutdown, daemon=True).start()
        return farewell

    def handle_friday_status(self, text, args):
        capabilities = getattr(self.app, "capabilities", None)
        router = getattr(self.app, "router", None)
        lines = ["FRIDAY status:"]
        if capabilities:
            lines.extend(f"- {line}" for line in capabilities.summary_lines())
            disabled = capabilities.disabled_skills()
            if disabled:
                for skill_name, reason in sorted(disabled.items()):
                    lines.append(f"- {skill_name}: {reason}")
        if router and hasattr(router, "model_manager"):
            for role in ("chat", "tool"):
                status = router.model_manager.status(role)
                state = "loaded" if status["loaded"] else "available" if status["exists"] else "missing"
                lines.append(f"- {role} model: {os.path.basename(status['path'])} ({state})")
        metrics = getattr(self.app, "runtime_metrics", None)
        if metrics and hasattr(metrics, "summary_lines"):
            lines.extend(f"- {line}" for line in metrics.summary_lines())
        return "\n".join(lines)

    def _handle_file_action(self, text, args, fallback_actions):
        if self.dialog_state.has_pending_file_request():
            pending = self.dialog_state.pending_file_request
            request = self._parse_file_request(text, args, default_actions=fallback_actions)
            if request["filename"] or request["extension"] or request["use_selected_file"]:
                selected_path, error = choose_candidate_from_text(text, pending.candidates)
                if selected_path:
                    actions = pending.requested_actions or fallback_actions
                    return self._finalize_pending_file(selected_path, actions)
                if error and not request["filename"]:
                    return error

        request = self._parse_file_request(text, args, default_actions=fallback_actions)

        if request["use_selected_file"] and self.dialog_state.selected_file:
            return self._execute_file_actions(self.dialog_state.selected_file, request["requested_actions"])

        if not request["filename"]:
            pending = self.dialog_state.pending_file_request
            if pending and len(pending.candidates) == 1:
                actions = pending.requested_actions or request["requested_actions"] or fallback_actions
                return self._finalize_pending_file(pending.candidates[0], actions)
            if self.dialog_state.selected_file and request["requested_actions"] != ["open"]:
                return self._execute_file_actions(self.dialog_state.selected_file, request["requested_actions"])
            return f"Which file would you like me to {fallback_actions[0]}?"

        folder_path, matches, error = self._resolve_file_matches(request)
        if error:
            return error

        if folder_path:
            self.dialog_state.remember_folder(folder_path)

        if not matches:
            return self._format_missing_file_response(request, folder_path)

        if len(matches) > 1:
            self.dialog_state.set_pending_file_request(
                candidates=matches,
                requested_actions=request["requested_actions"] or fallback_actions,
                folder_path=folder_path,
                filename_query=request["filename"],
                extension=request["extension"],
            )
            return self._format_candidate_prompt(matches)

        return self._execute_file_actions(matches[0], request["requested_actions"] or fallback_actions)

    def _parse_file_request(self, text, args=None, default_actions=None):
        args = dict(args or {})
        text_lower = text.lower()
        folder = (args.get("folder") or "").strip() or self._extract_folder_name(text_lower)
        extension = canonicalize_extension((args.get("extension") or "").strip()) or extract_extension_from_text(text_lower)
        filename = (args.get("filename") or args.get("query") or "").strip() or self._extract_filename_query(text_lower)
        filename = self._clean_entity(filename)
        folder = self._clean_entity(folder)

        return {
            "filename": filename,
            "folder": folder,
            "extension": extension,
            "requested_actions": self._detect_requested_actions(text_lower, default_actions),
            "use_selected_file": bool(re.search(r"\b(?:it|that file|this file|selected file)\b", text_lower)),
            "use_current_folder": bool(re.search(r"\b(?:that|this)\s+folder\b", text_lower)),
            "text_lower": text_lower,
        }

    def _resolve_file_matches(self, request):
        folder_path = None
        if request["folder"]:
            folder_path = resolve_folder_path(request["folder"])
            if not folder_path:
                return None, [], f"I couldn't find a folder named '{request['folder']}'."
        elif request["use_current_folder"]:
            folder_path = self.dialog_state.current_folder
        elif self.dialog_state.current_folder and request["text_lower"].count("folder") <= 1:
            folder_path = self.dialog_state.current_folder

        matches = search_files_raw(
            request["filename"],
            folder_path=folder_path,
            extension=request["extension"],
            limit=8,
        )
        return folder_path, matches, None

    def _extract_folder_name(self, text_lower):
        patterns = (
            r"\b(?:in|inside|from|within)\s+(?:the\s+)?([a-z0-9][a-z0-9 _\-.]+?)\s+folder\b",
            r"\bopen\s+(?:the\s+)?([a-z0-9][a-z0-9 _\-.]+?)\s+folder\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                folder_name = self._clean_entity(match.group(1))
                if folder_name in {"that", "this"}:
                    return ""
                return folder_name
        return ""

    def _extract_filename_query(self, text_lower):
        patterns = (
            r"\bfile\s+([a-z0-9][a-z0-9 _\-.]*?)(?=\s+(?:open|read|summarize|preview|inside|in|from|within|and)\b|$)",
            r"\b(?:named|called)\s+([a-z0-9][a-z0-9 _\-.]*?)(?=\s+(?:open|read|summarize|preview|inside|in|from|within|and)\b|$)",
            r"\b(?:open|read|summarize|preview|find|search|locate)\s+(?:the\s+)?(?:file\s+)?([a-z0-9][a-z0-9 _\-.]*?)(?=\s+(?:inside|in|from|within|folder|and)\b|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                candidate = self._clean_entity(match.group(1))
                if candidate not in {"it", "them", "that", "this"}:
                    return candidate
        return ""

    def _clean_entity(self, value):
        value = (value or "").strip(" .,!?:;\"'")
        value = re.sub(r"\s+", " ", value)
        return value

    def _detect_requested_actions(self, text_lower, default_actions):
        actions = []
        if re.search(r"\bopen\b", text_lower):
            actions.append("open")
        if re.search(r"\b(?:read|preview|show contents)\b", text_lower):
            actions.append("read")
        if re.search(r"\b(?:summarize|summary of|sum up)\b", text_lower):
            actions.append("summarize")

        if not actions:
            actions = list(default_actions or [])

        ordered = []
        for action in ("open", "read", "summarize"):
            if action in actions and action not in ordered:
                ordered.append(action)
        return ordered

    def _format_missing_file_response(self, request, folder_path):
        if folder_path:
            folder_name = os.path.basename(folder_path)
            message = f"FAILURE: I couldn't find a file named '{request['filename']}' in the {folder_name} folder."
            self.dialog_state.remember_folder(folder_path)
        else:
            message = f"FAILURE: I couldn't find any file named '{request['filename']}'."

        self.dialog_state.remember_error(message)
        if folder_path:
            return message + " You can ask me what other files are in that folder."
        return message

    def _format_candidate_prompt(self, matches):
        lines = ["I found multiple matching files. Which one should I use?"]
        for index, match in enumerate(matches[:8], 1):
            lines.append(f"{index}. {os.path.basename(match)}")
        lines.append("Reply with the number, the exact filename, or something like 'the pdf one'.")
        return "\n".join(lines)

    def _finalize_pending_file(self, filepath, actions):
        self.dialog_state.clear_pending_file_request()
        self.pending_file_to_open = None
        return self._execute_file_actions(filepath, actions)

    def _execute_file_actions(self, filepath, actions):
        actions = list(actions or ["open"])
        responses = []

        self.dialog_state.remember_file(filepath)
        self.dialog_state.remember_error(None)

        for action in actions:
            if action == "open":
                responses.append(open_file(filepath))
            elif action == "read":
                responses.append(read_file_preview(filepath))
            elif action == "summarize":
                llm = self.app.router.get_llm()
                responses.append(summarize_file_offline(filepath, llm=llm))

        deduped = []
        seen = set()
        for response in responses:
            key = response.strip()
            if key and key not in seen:
                deduped.append(key)
                seen.add(key)
        return "\n".join(deduped)


def setup(app):
    return SystemControlPlugin(app)
