from core.logger import logger
from core.plugin_manager import FridayPlugin

from .media_helpers import (
    dispatch_media_intent,
    is_likely_media_command,
    parse_media_intent,
)
from .service import BrowserMediaService


class _BrowserShutdown:
    """Tiny adapter so LifecycleManager (which expects .stop()) can drive
    BrowserMediaService.shutdown() during graceful teardown."""

    def __init__(self, service):
        self._service = service

    def stop(self):
        self._service.shutdown()


class BrowserAutomationPlugin(FridayPlugin):
    def __init__(self, app):
        super().__init__(app)
        self.name = "BrowserAutomation"
        self.service = BrowserMediaService(app)
        self.app.browser_media_service = self.service
        lifecycle = getattr(app, "lifecycle", None)
        if lifecycle and hasattr(lifecycle, "register"):
            try:
                lifecycle.register(_BrowserShutdown(self.service), name="browser-media")
            except Exception:
                pass
        self.on_load()

    def on_load(self):
        self.app.register_capability({
            "name": "open_browser_url",
            "description": "Open a website in a controlled browser session.",
            "parameters": {
                "url": "string - website URL to open",
                "browser_name": "string - preferred browser, usually chrome",
            },
            "context_terms": ["browser", "chrome", "youtube", "youtube music"],
        }, self.handle_open_browser_url, metadata={
            "connectivity": "online",
            "latency_class": "interactive",
            "permission_mode": "ask_first",
            "side_effect_level": "write",
        })

        self.app.register_capability({
            "name": "play_youtube",
            "description": "Search for a video on YouTube and start playback in a controlled browser session.",
            "parameters": {
                "query": "string - video title or search terms",
                "browser_name": "string - preferred browser, usually chrome",
            },
            "context_terms": ["play youtube", "video", "music video", "youtube"],
        }, self.handle_play_youtube, metadata={
            "connectivity": "online",
            "latency_class": "interactive",
            "permission_mode": "ask_first",
            "side_effect_level": "write",
        })

        self.app.register_capability({
            "name": "play_youtube_music",
            "description": "Search for a song on YouTube Music and start playback in a controlled browser session.",
            "parameters": {
                "query": "string - song title or search terms",
                "browser_name": "string - preferred browser, usually chrome",
            },
            "context_terms": ["youtube music", "song", "album", "playlist"],
        }, self.handle_play_youtube_music, metadata={
            "connectivity": "online",
            "latency_class": "interactive",
            "permission_mode": "ask_first",
            "side_effect_level": "write",
        })

        self.app.register_capability({
            "name": "browser_media_control",
            "description": "Control active browser playback such as pause, resume, or next.",
            "parameters": {
                "control": "string - one of pause, resume, next, play",
            },
            "context_terms": ["pause", "resume", "next", "skip", "browser media"],
        }, self.handle_browser_media_control, metadata={
            "connectivity": "online",
            "latency_class": "interactive",
            "permission_mode": "always_ok",
            "side_effect_level": "write",
        })

        self.app.register_capability({
            "name": "search_google",
            "description": "Search Google for the given query and open the results in a new browser tab.",
            "parameters": {
                "query": "string - what to search for",
                "browser_name": "string - preferred browser, usually chrome",
            },
            "context_terms": ["search google", "google search", "look up", "google for"],
        }, self.handle_search_google, metadata={
            "connectivity": "online",
            "latency_class": "interactive",
            "permission_mode": "always_ok",
            "side_effect_level": "write",
        })

        # Track 5.2d-retire: predicate + dispatcher capabilities for the
        # browser_media YAML template. `detect_media_command` backs the
        # `when:`/`cancel_when:` predicates that gate when the workflow
        # captures a turn (Issue 9 boundary check); `browser_media_dispatch`
        # is the single capability that replaces the deleted
        # `BrowserMediaWorkflow._handle` intent → service-method body.
        self.app.register_capability({
            "name": "detect_media_command",
            "description": (
                "Predicate: True when the user's utterance looks like a "
                "browser-media control intent (pause / next / play X / "
                "seek) rather than conversational text. Used as the "
                "`when:` predicate that lets the browser_media workflow "
                "passively capture subsequent control turns while a "
                "YouTube tab is open."
            ),
            "parameters": {
                "text": "string – the user's current utterance",
            },
            "side_effect_level": "read",
            "context_terms": [],
        }, self.handle_detect_media_command)

        self.app.register_capability({
            "name": "browser_media_dispatch",
            "description": (
                "Parse the user's utterance into a media intent and "
                "dispatch it via BrowserMediaService. Returns the "
                "service's human-readable response. Used by the "
                "browser_media workflow template as its sole "
                "capability step."
            ),
            "parameters": {
                "text": "string – the user's utterance",
                "workflow_state": "object – the active workflow state (provides platform/query continuity)",
            },
            "side_effect_level": "write",
            "context_terms": [],
        }, self.handle_browser_media_dispatch)

        logger.info("BrowserAutomationPlugin loaded.")

    def handle_detect_media_command(self, text, args):
        return is_likely_media_command((text or "").lower())

    def handle_browser_media_dispatch(self, text, args):
        args = args or {}
        workflow_state = dict(args.get("workflow_state") or {})
        context = dict(args.get("context") or {})
        intent = parse_media_intent(text, workflow_state, context)
        if intent is None:
            return ""
        response = dispatch_media_intent(self.service, intent)
        # Persist the new platform/query so subsequent control turns
        # reuse the same context. Mirrors the legacy workflow's state
        # write inside `_handle`.
        memory = (
            getattr(self.app, "memory_service", None)
            or getattr(self.app, "context_store", None)
        )
        session_id = getattr(self.app, "session_id", None)
        if memory is not None and session_id and hasattr(memory, "save_workflow_state"):
            try:
                memory.save_workflow_state(session_id, "browser_media", {
                    "workflow_name": "browser_media",
                    "status": "active",
                    "pending_slots": [],
                    "last_action": intent.get("action", ""),
                    "target": {
                        "browser_name": intent.get("browser_name", "chrome"),
                        "platform": intent.get("platform", "youtube"),
                        "query": intent.get("query", ""),
                    },
                    "result_summary": response,
                    "browser_name": intent.get("browser_name", "chrome"),
                    "platform": intent.get("platform", "youtube"),
                    "query": intent.get("query", ""),
                })
            except Exception as exc:
                logger.debug("[browser_media] state persist skipped: %s", exc)
        return response

    def handle_open_browser_url(self, text, args):
        disabled_reason = self._disabled_reason()
        if disabled_reason:
            return disabled_reason
        url = args.get("url") or "https://www.youtube.com"
        browser_name = args.get("browser_name") or "chrome"
        orchestrator = getattr(self.app, "workflow_orchestrator", None)
        if orchestrator:
            result = orchestrator.run(
                "browser_media",
                text,
                self.app.session_id,
                {"action": "open_browser_url", "url": url, "browser_name": browser_name},
            )
            if result.handled:
                return result.response
        return self.service.open_browser_url(url, browser_name=browser_name)

    def handle_play_youtube(self, text, args):
        disabled_reason = self._disabled_reason()
        if disabled_reason:
            return disabled_reason
        query = args.get("query", "").strip()
        browser_name = args.get("browser_name") or "chrome"
        orchestrator = getattr(self.app, "workflow_orchestrator", None)
        if orchestrator:
            result = orchestrator.run(
                "browser_media",
                text,
                self.app.session_id,
                {"action": "play_youtube", "query": query, "browser_name": browser_name},
            )
            if result.handled:
                return result.response
        return self.service.play_youtube(query, browser_name=browser_name)

    def handle_play_youtube_music(self, text, args):
        disabled_reason = self._disabled_reason()
        if disabled_reason:
            return disabled_reason
        query = args.get("query", "").strip()
        browser_name = args.get("browser_name") or "chrome"
        orchestrator = getattr(self.app, "workflow_orchestrator", None)
        if orchestrator:
            result = orchestrator.run(
                "browser_media",
                text,
                self.app.session_id,
                {"action": "play_youtube_music", "query": query, "browser_name": browser_name},
            )
            if result.handled:
                return result.response
        return self.service.play_youtube_music(query, browser_name=browser_name)

    def handle_search_google(self, text, args):
        disabled_reason = self._disabled_reason()
        if disabled_reason:
            return disabled_reason
        query = (args.get("query") or "").strip()
        if not query:
            # Pull the search subject out of the raw transcript.
            lowered = (text or "").lower()
            for prefix in ("search google for", "google search for", "google for", "look up", "search for", "search google"):
                if prefix in lowered:
                    query = lowered.split(prefix, 1)[-1].strip(" ?.!")
                    break
        if not query:
            return "What should I search for, sir?"
        browser_name = args.get("browser_name") or "chrome"
        return self.service.search_google(query, browser_name=browser_name)

    def handle_browser_media_control(self, text, args):
        disabled_reason = self._disabled_reason()
        if disabled_reason:
            return disabled_reason
        control = args.get("control") or ""
        orchestrator = getattr(self.app, "workflow_orchestrator", None)
        if orchestrator:
            result = orchestrator.run(
                "browser_media",
                text,
                self.app.session_id,
                {"action": "browser_media_control", "control": control},
            )
            if result.handled:
                return result.response
        return self.service.browser_media_control(control)

    def _disabled_reason(self):
        config = getattr(self.app, "config", None)
        if not config:
            return ""
        if not config.get("browser_automation.enabled", True):
            return "Browser automation is disabled in the FRIDAY configuration."
        if not config.get("browser_automation.allow_online", True):
            return "Browser automation is currently disabled because online features are turned off."
        return ""


def setup(app):
    return BrowserAutomationPlugin(app)
