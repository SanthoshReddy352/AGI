"""Track 4.1b deeper extraction — shared routing-defaults module.

Single source of truth for the default aliases / patterns / context
terms attached to known tool names. Previously duplicated between
`CommandRouter._default_*_for` (the production-tested set) and
`RouteScorer._DEFAULT_*` (a never-read copy). Now both consult the
constants below.

CommandRouter's set was chosen as canonical because:

* It's the path live `register_tool` calls actually exercise.
* It carries deliberate tightening — e.g., the `get_battery` pattern
  was narrowed to a status-framed alias because bare ``\\bbattery\\b``
  was firing on "battery in my car".
* The drift on RouteScorer's side was a future-proofing copy that
  was never wired into production scoring.

If a future tool needs additional default routing artifacts, ADD
them here only — both readers pick them up automatically.
"""
from __future__ import annotations


# Plain string aliases; per-tool sets joined into a single sorted list
# of aliases by the build helpers. Tool name is added separately, so
# only NON-NAME aliases live here.
DEFAULT_ALIASES: dict[str, set[str]] = {
    "greet": {"hello", "hi", "hey", "hey friday", "good morning", "good evening"},
    "show_capabilities": {"what can you do", "show help", "show commands", "list capabilities"},
    "launch_app": {"open", "launch", "start"},
    "set_volume": {"volume up", "volume down", "mute", "increase volume", "decrease volume"},
    "take_screenshot": {"screen shot", "capture screen"},
    "search_file": {"find file", "search file", "locate file"},
    "open_file": {"open file"},
    "get_system_status": {"system status", "system health"},
    # Aliases used to include a bare "battery" → high score on any
    # mention. Now require a status framing in the alias too.
    "get_battery": {"battery status", "battery level", "battery percent"},
    "get_cpu_ram": {"cpu usage", "ram usage", "memory usage"},
    "set_reminder": {"remind me", "set reminder"},
    "save_note": {"save note", "note down", "remember this"},
    "read_notes": {"read notes", "show notes", "my notes"},
    "get_time": {"what time is it", "current time", "tell me the time"},
    "get_date": {"today's date", "what day is it", "current date", "tell me the date"},
    "manage_file": {
        "create file", "make file", "new file",
        "write it to", "save it to", "write that to", "save that to",
    },
    "enable_voice": {
        "enable voice", "start listening", "turn on mic", "turn on microphone",
    },
    "disable_voice": {
        "disable voice", "stop listening", "turn off mic", "turn off microphone",
    },
    "confirm_yes": {"yes", "yeah", "open it", "do it", "sure", "okay"},
    "confirm_no": {"no", "nope", "cancel", "stop that"},
    "select_file_candidate": {
        "first one", "second one", "this one", "that one",
        "option 1", "option 2",
    },
}


DEFAULT_CONTEXT_TERMS: dict[str, set[str]] = {
    "greet": {"greet", "greeting"},
    "show_capabilities": {"commands", "abilities", "capabilities"},
    "launch_app": {"application", "app", "browser", "firefox", "chrome", "calculator"},
    "set_volume": {"volume", "audio", "sound", "mute"},
    "take_screenshot": {"screenshot", "screen", "capture"},
    "search_file": {"find", "search", "file", "locate"},
    "open_file": {"open", "file", "document"},
    "get_system_status": {"system", "status", "health"},
    "get_battery": {"battery", "charge"},
    "get_cpu_ram": {"cpu", "ram", "memory"},
    "set_reminder": {"reminder", "remind"},
    "save_note": {"note", "remember", "save"},
    "read_notes": {"notes", "read", "show"},
    "get_time": {"time", "clock"},
    "get_date": {"date", "day", "today"},
    "manage_file": {"create", "file", "document", "write"},
    "enable_voice": {"voice", "microphone", "mic", "listen"},
    "disable_voice": {"voice", "microphone", "mic", "stop"},
    "confirm_yes": {"yes", "confirm"},
    "confirm_no": {"no", "cancel"},
}


# Raw regex source strings; the build helpers compile them with
# `re.IGNORECASE`. Anchored patterns (`^…$`) are intentional — they
# avoid loose matches on phrases like "I have a date tonight"
# triggering `get_date`.
DEFAULT_PATTERNS: dict[str, list[str]] = {
    "greet": [r"\b(hi|hello|hey|good morning|good afternoon|good evening)\b"],
    "show_capabilities": [
        r"what can you do",
        r"show (?:me )?(?:your\s+)?(?:commands|capabilities|abilities)",
        r"list (?:your\s+)?(?:commands|capabilities)",
    ],
    # Generic "open X" used to fast-path to launch_app even when X was not an
    # app name (e.g. "open the discussion"). We keep the loose pattern here
    # but score it lower; the IntentRecognizer's registry-aware extractor
    # remains the authoritative path. Without an `app_names` resolution it
    # should not auto-execute.
    "launch_app": [
        r"\b(?:open|launch|start|bring up)\s+(?!file\b|folder\b|the\s+folder\b)"
        r"[a-z0-9][\w\-\s,]*(?:\band\b\s*[a-z0-9][\w\-\s]*)*"
    ],
    "set_volume": [r"\b(?:volume|mute|unmute)\b", r"\b(?:increase|decrease|turn)\s+volume\b"],
    # Both forms require an explicit capture verb. Previously the second
    # alternative was bare `\bscreenshot\b` which fired on "I deleted my
    # screenshot folder" — pure mention.
    "take_screenshot": [
        r"\b(?:take|capture|grab|snap|get|make)\s+(?:a\s+|another\s+|the\s+)?"
        r"(?:screenshot|screen\s*shot|screen\s+capture)\b",
        r"^(?:please\s+)?screen\s*shot(?:\s+please)?[.!?]?$",
    ],
    "search_file": [r"\b(?:find|search|locate)\s+(?:for\s+)?(?:file\s+)?\S+"],
    "open_file": [r"\bopen\s+(?:the\s+)?file\b"],
    "get_system_status": [r"\b(?:system status|system health)\b"],
    # `\bbattery\b` alone overmatches ("the battery in my car"); require an
    # explicit status verb or possessive context.
    "get_battery": [
        r"\b(?:battery\s+(?:status|level|percent(?:age)?|charge|life|remaining)|"
        r"(?:what(?:'s| is)\s+(?:my\s+|the\s+)?battery)|"
        r"how('s|\s+is)\s+(?:my\s+|the\s+)?battery)\b",
    ],
    # `memory` alone overmatches; require explicit usage/load language.
    "get_cpu_ram": [
        r"\b(?:cpu\s+(?:usage|load|status)|ram\s+(?:usage|status|free)|"
        r"memory\s+(?:usage|load|status|free))\b",
        r"\bsystem\s+(?:usage|load|performance)\b",
    ],
    "set_reminder": [r"\bremind me\b", r"\bset (?:a )?reminder\b"],
    "save_note": [r"\b(?:save note|note down|remember this|remember that)\b"],
    "read_notes": [r"\b(?:read|show|list)\s+(?:my\s+)?notes\b"],
    # Anchored time/date patterns only — bare `\btime\b` / `\bdate\b` overmatch on
    # phrases like "set my time zone", "I have a date tonight", "time to leave".
    "get_time": [
        r"\b(?:what(?:'s| is)? the time|what time is it|current time|"
        r"tell me(?: the)? time)\b"
    ],
    "get_date": [
        r"\b(?:today(?:'s)? date|what day is it|current date|"
        r"tell me(?: the)? date)\b"
    ],
    "manage_file": [
        r"\b(?:create|make)\s+(?:a\s+)?file\b",
        r"\b(?:write|save|append|add)\s+(?:it|that|this|the answer|the response)"
        r"\s+(?:to|into|in)\s+\S+",
    ],
    "enable_voice": [r"\b(?:enable|start|turn on)\s+(?:the\s+)?(?:mic|microphone|voice)\b"],
    "disable_voice": [r"\b(?:disable|stop|turn off)\s+(?:the\s+)?(?:mic|microphone|voice)\b"],
    "confirm_yes": [r"^(?:yes|yeah|yep|sure|okay|ok|open it|do it)$"],
    "confirm_no": [r"^(?:no|nope|cancel|stop)$"],
    "select_file_candidate": [
        r"^(?:the\s+)?(?:first|second|third|fourth|fifth|last)\s+(?:one|file)$",
        r"^(?:the\s+)?(?:this|that)\s+(?:one|file)$",
        r"^(?:option\s+)?\d+$",
        r"^(?:the\s+)?(?:pdf|txt|md|json|csv|py|docx)\s+one$",
    ],
}
