"""MemoryManagerPlugin — show_memories, forget_memory, wipe_memory, export_memory.

Track 2.3 (Consolidation Direction): backed by the canonical
`MemoryFacade` instead of the Mem0 client. The plugin now talks to one
store via `app.memory_broker.facts` — same surface every other consumer
goes through. The previous `delete_memory` capability (which did
similarity search in Mem0) is renamed to `forget_memory` and accepts
an explicit key, since the facade is key/value-shaped and similarity
deletion isn't well-defined without an external embedder.

P2.1 adds wipe_memory (two-step confirmation) and export_memory.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime

from core.logger import logger
from core.plugin_manager import FridayPlugin


class MemoryManagerPlugin(FridayPlugin):
    name = "memory_manager"

    def __init__(self, app):
        super().__init__(app)
        self.name = "memory_manager"
        self.on_load()

    def on_load(self) -> None:
        # Track 4.1b: migrated from `app.router.register_tool(...)` to
        # the canonical `app.register_capability(...)` entry point.
        # Functionally identical — `register_capability` calls through
        # to `router.register_tool` under the hood — but the API name
        # is the one the Direction prescribes for new plugin code.
        self.app.register_capability(
            {
                "name": "show_memories",
                "description": (
                    "Show what FRIDAY remembers about the user — preferences, "
                    "facts, and context learned from past conversations."
                ),
                "parameters": {
                    "limit": "integer — max number of memories to show (default: 20)",
                },
                "context_terms": [
                    "what do you remember", "show my memories",
                    "what do you know about me", "list memories",
                    "what have you learned", "my preferences",
                ],
            },
            self._handle_show_memories,
        )

        self.app.register_capability(
            {
                "name": "forget_memory",
                "description": (
                    "Forget a specific fact by key (e.g. 'location', 'name'). "
                    "Removes the fact from the canonical memory store and the "
                    "user_profile mirror."
                ),
                "parameters": {
                    "key": "string — fact key to forget (e.g. 'location')",
                },
                "context_terms": [
                    "forget that", "delete memory", "remove that memory",
                    "stop remembering", "forget what I said", "clear that memory",
                    "forget my",
                ],
            },
            self._handle_forget_memory,
        )

        self.app.register_capability(
            {
                "name": "wipe_memory_init",
                "description": (
                    "Begin the two-step memory-wipe flow. FRIDAY asks for confirmation "
                    "before erasing all stored facts, preferences, and memories."
                ),
                "context_terms": [
                    "forget everything", "wipe your memory", "wipe my memory",
                    "erase everything", "start fresh", "reset your memory",
                    "delete everything you know about me",
                ],
            },
            self._handle_wipe_memory_init,
        )
        self.app.register_capability(
            {
                "name": "confirm_memory_wipe",
                "description": "Execute the confirmed memory wipe.",
                "context_terms": [],
            },
            self._handle_confirm_memory_wipe,
        )
        self.app.register_capability(
            {
                "name": "cancel_memory_wipe",
                "description": "Cancel a pending memory wipe.",
                "context_terms": [],
            },
            self._handle_cancel_memory_wipe,
        )
        self.app.register_capability(
            {
                "name": "export_memory",
                "description": "Export all stored memories to a JSON file.",
                "context_terms": [
                    "export my memory", "backup my memory", "save my memories to file",
                    "export what you know about me",
                ],
            },
            self._handle_export_memory,
        )
        # P3.2 — FTS5 keyword search over past conversation turns.
        self.app.register_capability(
            {
                "name": "search_conversations",
                "description": (
                    "Keyword-search past conversation turns for words or phrases "
                    "the user mentioned earlier. Backed by SQLite FTS5."
                ),
                "parameters": {
                    "query": "string — words or phrase to search for",
                    "limit": "integer — max results (default 5)",
                },
                "context_terms": [
                    "search my conversations", "search our chats",
                    "what did we talk about", "find in conversation",
                    "search past turns", "search conversation history",
                ],
            },
            self._handle_search_conversations,
        )
        # Adaptive Intent Phase 5 — user control over routing learning. Clears
        # the learned phrasings + usage profile (NOT the user's facts), so the
        # assistant stops auto-dispatching phrasings it picked up. Local-first
        # / privacy: pairs with the `routing.learning_enabled` config switch.
        self.app.register_capability(
            {
                "name": "forget_learned_intents",
                "description": (
                    "Reset what FRIDAY has learned about how you phrase commands "
                    "— clears learned phrasings and usage habits, but keeps your "
                    "facts and preferences."
                ),
                "context_terms": [
                    "forget how I talk", "forget how I speak",
                    "reset what you learned", "unlearn my phrasings",
                    "stop learning how I talk", "forget how I word things",
                ],
            },
            self._handle_forget_learned_intents,
        )
        logger.info(
            "[memory_manager] Plugin loaded — "
            "show_memories, forget_memory, wipe_memory, export_memory, "
            "forget_learned_intents registered."
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _facade(self):
        broker = getattr(self.app, "memory_broker", None)
        return getattr(broker, "facts", None) if broker else None

    def _session_id(self) -> str:
        return getattr(self.app, "session_id", "") or ""

    def _handle_show_memories(self, raw_text: str, args: dict):
        """Return a conversational paragraph (not a bullet list) describing
        what we know about the user.

        2026-05-23 rewrite: the bullet-list form was robotic ('**About
        you:**\n  - name: Tricky\n  - role: Student'). The user explicitly
        asked for a 'lovely paragraph', so we now stitch profile and
        memory facts into one or two sentences. We still return a flat
        string so the response finalizer / TTS chain doesn't choke on
        markdown structure.
        """
        try:
            limit = int(args.get("limit") or 20)
        except (TypeError, ValueError):
            limit = 20

        profile: dict[str, str] = {}
        cs = getattr(self.app, "context_store", None)
        if cs:
            try:
                for f in cs.get_facts_by_namespace("user_profile"):
                    val = (f.get("value") or "").strip()
                    if not val:
                        continue
                    if val.startswith("CapabilityExecutionResult(") or val.startswith("CapabilityResult("):
                        continue
                    profile.setdefault(f["key"], val)
            except Exception:
                pass

        memories: list[tuple[str, str]] = []
        facade = self._facade()
        session_id = self._session_id()

        # 2026-05-24 stale-profile fix: the legacy `user_profile` namespace can
        # carry forward outdated values (e.g. an onboarding-era "name=Tricky"
        # row that wasn't replaced when a later session said "My name is
        # Santhosh"). The MemoryFacade is the canonical reader/writer — when
        # it has a value for a profile key, IT WINS over the legacy mirror.
        # Without this overlay, `show_memories` and `recall_personal_fact`
        # returned different names for the SAME user in the same conversation
        # (live session 2026-05-24 07:25).
        if facade and session_id:
            for key in list(profile.keys()) + [
                "name", "role", "location", "preferences", "comm_style",
                "loves", "likes", "hates", "prefers",
                "hometown", "city", "email", "phone", "birthday",
            ]:
                try:
                    fresh = facade.recall(session_id, key=key)
                except Exception:
                    fresh = []
                if fresh and fresh[0].value:
                    profile[key] = fresh[0].value

            try:
                facts = facade.list_all(session_id, limit=limit)
                seen: set[str] = set()
                for f in facts:
                    if f.key in seen or f.key in profile:
                        continue
                    seen.add(f.key)
                    memories.append((f.key, f.value))
            except Exception:
                pass

        if not profile and not memories:
            return "Honestly, I don't have much on file for you yet. Tell me anything you'd like me to remember."

        # "What else do you know about me?" must NOT return the exact
        # same curated paragraph — that bug surfaced on 2026-05-23
        # 21:36 → 21:37 (two identical replies in 30s). When the parser
        # tags `args["more"] = True`, render a full key/value breakdown
        # of everything we have, so the user sees the difference.
        if args.get("more"):
            return self._render_detailed_memories(profile, memories)

        return self._compose_memory_paragraph(profile, memories)

    def _render_detailed_memories(self, profile: dict, memories: list) -> str:
        """Render every fact in key: value form. Used when the user asked
        for 'more' / 'else' / 'everything' so the second-ask reply isn't a
        verbatim repeat of the first.
        """
        lines: list[str] = []
        if profile:
            lines.append("Here's everything in your profile:")
            for key in sorted(profile):
                lines.append(f"  - {key.replace('_', ' ')}: {profile[key]}")
        if memories:
            lines.append("")
            lines.append("And the things you've told me to remember:")
            for key, value in memories:
                lines.append(f"  - {key.replace('_', ' ')}: {value}")
        if not lines:
            return self._compose_memory_paragraph(profile, memories)
        return "\n".join(lines)

    def _compose_memory_paragraph(self, profile: dict, memories: list) -> str:
        """Render the gathered facts as a natural-sounding paragraph."""
        name = profile.get("name", "")
        role = profile.get("role", "")
        location = profile.get("location", "")
        comm_style = profile.get("comm_style", "")
        preferences = profile.get("preferences", "")

        clauses: list[str] = []
        opener_parts = []
        if name:
            opener_parts.append(f"you're {name}")
        if role and location:
            opener_parts.append(f"a {role.lower()} based in {location}")
        elif role:
            opener_parts.append(f"a {role.lower()}")
        elif location:
            opener_parts.append(f"based in {location}")
        if opener_parts:
            clauses.append("From what I have on file, " + ", ".join(opener_parts) + ".")

        if comm_style:
            clauses.append(f"You like me to keep things {comm_style.lower()}.")
        if preferences:
            clauses.append(f"You care about {preferences.lower()}.")

        # Remaining profile keys (e.g. timezone, age) that didn't fit the
        # opener — render as 'Your X is Y.'
        other_keys = [k for k in profile if k not in {"name", "role", "location", "comm_style", "preferences"}]
        for key in other_keys:
            clauses.append(f"Your {key.replace('_', ' ')} is {profile[key]}.")

        if memories:
            snippets = [f"{k.replace('_', ' ')} ({v})" for k, v in memories[:5]]
            clauses.append("You've also told me about " + ", ".join(snippets) + ".")

        return " ".join(clauses).strip()

    def _handle_forget_memory(self, raw_text: str, args: dict):
        facade = self._facade()
        if facade is None:
            return "Memory system is not active."
        session_id = self._session_id()
        if not session_id:
            return "I can't forget things right now."
        key = (args.get("key") or "").strip().lower()
        if not key:
            return "Which fact would you like me to forget? Tell me the key (e.g. 'location')."
        guard = getattr(self.app, "confirmation_guard", None)
        if guard is not None and guard.needs_confirmation(args):
            return guard.arm(
                action="forget_memory", args={"key": key},
                preview=f"I'll forget your {key}.",
            )
        removed = facade.forget(session_id, key)
        if removed:
            return f"Done — I've forgotten your {key}."
        return f"I didn't have a {key} stored to forget."

    # ------------------------------------------------------------------
    # P2.1 — Memory wipe (two-step) and export
    # ------------------------------------------------------------------

    def _handle_forget_learned_intents(self, raw_text: str, args: dict):
        store = getattr(self.app, "intent_learning_store", None)
        if store is None or not hasattr(store, "forget_all"):
            return "I don't have any learned phrasings to forget."
        try:
            removed = store.forget_all()
        except Exception:
            logger.warning("[memory_manager] forget_learned_intents failed", exc_info=True)
            return "I couldn't reset what I learned just now — try again in a moment."
        # Drop the in-memory personal phrases from the live embedding index too.
        router = getattr(self.app, "router", None)
        embed = getattr(router, "embedding_router", None) if router else None
        if embed is not None and hasattr(embed, "_personal"):
            try:
                embed._personal.clear()
                embed._index_signature = ""  # force a clean rebuild next route
            except Exception:
                pass
        audit = getattr(self.app, "audit_store", None)
        if audit:
            try:
                audit.log_audit_event(
                    "LEARNED_INTENTS_FORGOTTEN", True,
                    f"user reset routing learning ({removed} phrasings)",
                    session_id=self._session_id(),
                )
            except Exception:
                pass
        if removed:
            return (
                f"Done — I've forgotten the {removed} phrasing(s) I'd picked up "
                "and reset your usage habits. I'll relearn from scratch as we talk."
            )
        return "There was nothing learned yet, so we're already starting fresh."

    def _handle_wipe_memory_init(self, raw_text: str, args: dict):
        cs = getattr(self.app, "context_store", None)
        session_id = self._session_id()
        if cs and session_id:
            try:
                state = cs.get_session_state(session_id) or {}
                state["pending_memory_wipe"] = True
                cs.save_session_state(session_id, state)
            except Exception:
                pass
        # Phase 3: show a preview of what will be lost so the user confirms
        # against concrete counts, not a vague "everything".
        preview = self._wipe_preview(cs, session_id)
        return (
            f"This will erase everything I know about you{preview}. "
            "Say 'yes, wipe everything' to confirm, or anything else to cancel."
        )

    def _wipe_preview(self, cs, session_id: str) -> str:
        """Return a short ' — N facts, M memories, and K goals' summary, or ''.

        Best-effort: any counting failure falls back to a generic phrasing so
        the wipe flow never breaks on a preview hiccup.
        """
        parts: list[str] = []
        try:
            profile = cs.get_facts_by_namespace("user_profile") if cs else []
            n_facts = len([f for f in profile if (f.get("value") or "").strip()])
            if n_facts:
                parts.append(f"{n_facts} profile fact{'s' if n_facts != 1 else ''}")
        except Exception:
            pass
        try:
            facade = self._facade()
            if facade and session_id:
                n_mem = len(facade.list_all(session_id, limit=1000) or [])
                if n_mem:
                    parts.append(f"{n_mem} memorie{'s' if n_mem != 1 else ''}")
        except Exception:
            pass
        try:
            ms = getattr(self.app, "memory_service", None) or cs
            goals = ms.list_goals() if ms and hasattr(ms, "list_goals") else []
            n_goals = len(goals or [])
            if n_goals:
                parts.append(f"{n_goals} goal{'s' if n_goals != 1 else ''}")
        except Exception:
            pass
        if not parts:
            return " — your name, preferences, and all stored memories"
        if len(parts) == 1:
            return f" — including {parts[0]}"
        return f" — including {', '.join(parts[:-1])} and {parts[-1]}"

    def _handle_confirm_memory_wipe(self, raw_text: str, args: dict):
        cs = getattr(self.app, "context_store", None)
        ms = getattr(self.app, "memory_store", None)
        audit = getattr(self.app, "audit_store", None)
        session_id = self._session_id()
        if audit:
            audit.log_audit_event(
                "MEMORY_WIPE_EXECUTED", True,
                "user confirmed via 'yes wipe everything'",
                session_id=session_id,
            )
        if cs:
            self._wipe_sql_tables(cs.db_path)
        if ms:
            self._wipe_vector_store(ms)
        logger.warning("[memory_manager] Memory wiped by user request.")
        return (
            "Done — everything is gone. I no longer know your name, preferences, "
            "or anything you've told me. You can reintroduce yourself any time."
        )

    def _wipe_sql_tables(self, db_path: str) -> None:
        wipe_tables = [
            "facts", "memory_items",
            "entity_relationships", "entity_facts", "entities",
            "goal_progress", "goals",
        ]
        try:
            with sqlite3.connect(db_path) as conn:
                for table in wipe_tables:
                    try:
                        conn.execute(f"DELETE FROM {table}")
                    except sqlite3.OperationalError:
                        pass
                conn.commit()
        except Exception as exc:
            logger.error("[memory_manager] SQL wipe error: %s", exc)

    def _wipe_vector_store(self, ms) -> None:
        if not getattr(ms, "_vector_available", False):
            return
        try:
            import chromadb  # type: ignore
            client = chromadb.PersistentClient(path=ms.vector_path)
            client.delete_collection("friday_memory")
            client.create_collection("friday_memory")
            ms._vector_collection = None
            ms._vector_available = False
        except Exception as exc:
            logger.warning("[memory_manager] Chroma wipe error: %s", exc)

    def _handle_cancel_memory_wipe(self, raw_text: str, args: dict):
        audit = getattr(self.app, "audit_store", None)
        if audit:
            audit.log_audit_event(
                "MEMORY_WIPE_CANCELLED", True,
                "user did not confirm wipe",
                session_id=self._session_id(),
            )
        return "Wipe cancelled — I'll keep everything I know about you."

    def _handle_search_conversations(self, raw_text: str, args: dict):
        query = (args.get("query") or "").strip()
        if not query:
            # Extract the search term from natural-language input.
            query = self._extract_search_query(raw_text)
        if not query:
            return "What word or phrase should I search for?"
        try:
            limit = int(args.get("limit") or 5)
        except (TypeError, ValueError):
            limit = 5
        ms = getattr(self.app, "memory_store", None)
        if ms is None or not hasattr(ms, "fts_search"):
            return "Conversation search isn't available right now."
        try:
            hits = ms.fts_search(query, limit=limit)
        except Exception as exc:
            logger.warning("[memory_manager] fts_search error: %s", exc)
            return "Search failed — check logs."
        if not hits:
            return f"I didn't find anything about '{query}' in our past chats."
        lines = [f"Found {len(hits)} mention(s) of '{query}':"]
        for h in hits:
            snippet = (h.get("text") or "").strip().replace("\n", " ")
            if len(snippet) > 200:
                snippet = snippet[:200] + "…"
            lines.append(f"  - [{h.get('role')}] {snippet}")
        return "\n".join(lines)

    _SEARCH_PREFIXES = (
        "search my conversations for ",
        "search our chats for ",
        "search past turns for ",
        "find in conversation ",
        "what did we talk about regarding ",
        "what did we talk about about ",
        "what did we talk about ",
        "search conversation history for ",
        "search conversations for ",
    )

    def _extract_search_query(self, raw_text: str) -> str:
        t = (raw_text or "").strip().rstrip("?.").lower()
        for prefix in self._SEARCH_PREFIXES:
            if t.startswith(prefix):
                return t[len(prefix):].strip()
        return ""

    def _handle_export_memory(self, raw_text: str, args: dict):
        cs = getattr(self.app, "context_store", None)
        ms = getattr(self.app, "memory_store", None)
        if not cs:
            return "Memory system not available."
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.expanduser(f"~/friday_memory_{timestamp}.json")
        try:
            from scripts.memory_admin import export_memory  # type: ignore
            size = export_memory(cs.db_path, ms.vector_path if ms else "", output_path)
            return f"Memory exported to {output_path} ({size // 1024} KB)."
        except Exception:
            return self._export_inline(cs.db_path, output_path)

    def _export_inline(self, db_path: str, output_path: str) -> str:
        exportable = ["facts", "memory_items", "entities", "entity_facts", "entity_relationships", "goals"]
        dump: dict = {"exported_at": datetime.utcnow().isoformat(), "tables": {}}
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                for table in exportable:
                    try:
                        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                        dump["tables"][table] = [dict(r) for r in rows]
                    except sqlite3.OperationalError:
                        dump["tables"][table] = []
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(dump, fh, indent=2, ensure_ascii=False, default=str)
            size = os.path.getsize(output_path) // 1024
            return f"Memory exported to {output_path} ({size} KB)."
        except Exception as exc:
            logger.error("[memory_manager] Export error: %s", exc)
            return "Export failed — check logs."
