"""Embedding-based tool router (cosine match on sentence-transformer embeddings).

Sits between the deterministic router (cheap regex / keyword match) and the
LLM-based tool model (~3-4s on a 4B). When the deterministic layer comes up
empty, this layer compares the utterance against every registered tool's
embedded description + canonical phrasings. If the top-1 cosine similarity
is above the dispatch threshold, we route directly without invoking the LLM,
catching paraphrases that the regex layer missed.

Latency on CPU with all-MiniLM-L6-v2: ~10-20 ms per route call after warmup.
First-call cost includes a one-time ~90 MB model download (cached afterward).

Design notes:
* Lazy initialization — the model only loads when the router is asked for a
  match, so cold start of FRIDAY isn't slowed by it.
* Embeddings are L2-normalized at index-build time, so similarity is a single
  matrix-vector dot product (no per-query normalization in the hot path).
* We index tools as a UNION of (name, description, context_terms) so a tool
  that registers `context_terms=["weather", "forecast", "rain"]` becomes
  reachable from "is it going to rain tomorrow" without needing the LLM.
* Args are NOT extracted by this layer. We dispatch with empty args and rely
  on each tool handler's own text-parsing logic (which Friday's handlers
  already use as a fallback). If a tool needs strict structured args, set its
  `embeddable=False` flag in capability_meta and the embedding router will
  skip it.
"""
from __future__ import annotations

import os
import threading
from typing import Iterable

import numpy as np

from core.logger import logger


# Lightweight sentence transformer — 22M params, ~90 MB on disk, 384-dim
# embeddings. Trades a few accuracy points vs. larger MPNet models for ~3x
# the throughput on CPU.
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Minimum cosine similarity to dispatch directly without consulting the LLM
# router. Tuned empirically — below ~0.55 we see too many false positives on
# short utterances ("yes", "stop", etc.).
DISPATCH_THRESHOLD = 0.62

# Adaptive Intent Recognition (Phase 5 — profile tie-breaker). When the top-2
# tools score within this cosine epsilon the match is effectively a tie, so an
# injected profile tie-breaker (usage frequency + time-of-day) may pick among
# them. Never applied when one tool is a clear winner.
TIE_EPSILON = 0.05

# Adaptive Intent Recognition (Phase 2 — confirmation loop). When the top-1
# cosine lands in the band [CONFIRM_LOW, DISPATCH_THRESHOLD) the match is too
# weak to auto-dispatch but too strong to silently drop to chat. Instead the
# planner asks "Did you mean to …?" and the yes/no answer becomes the learning
# signal. Below CONFIRM_LOW we don't even ask — the match is noise.
CONFIRM_LOW = 0.50

# Tools we never want to route to via embeddings, regardless of score —
# usually because they need structured args that only the LLM can produce.
_DEFAULT_BLOCKLIST = frozenset({
    "llm_chat",                # the chat fallback owns the no-tool case
    "create_calendar_event",   # consent + timestamp parsing
    "move_calendar_event",     # event identifier + new time
    "cancel_calendar_event",   # event identifier
    "set_reminder",            # time parsing
    "save_note",               # raw content capture
    "manage_file",             # multi-mode (create/write/append) — needs LLM
    "write_file",
    "set_voice_mode",          # mode arg required
    "set_volume",              # value arg required
    # Issue 6: dictation control verbs share semantic space with "save note"
    # ("save memo" vs. "save note") and used to cross-route via embedding
    # similarity, surfacing the bogus "I'm not in a dictation session right
    # now." reply. Force exact deterministic matching for these.
    "start_dictation",
    "end_dictation",
    "cancel_dictation",
    # The following accept structured args (app name, query, url …). When the
    # embedding router dispatches with empty args, their handlers either fail
    # or pick a poor default. Force them to go through the intent recognizer
    # or the LLM router which can produce the args.
    "launch_app",
    "open_browser_url",
    "play_youtube",
    "play_youtube_music",
    "search_google",
    "research_topic",
    "delete_memory",
    "select_file_candidate",
    "browser_media_control",
    "query_document",
})


class EmbeddingRouter:
    """Cosine-similarity router over registered tool descriptors."""

    def __init__(self, model_name: str = DEFAULT_MODEL,
                 dispatch_threshold: float = DISPATCH_THRESHOLD,
                 confirm_low: float = CONFIRM_LOW,
                 blocklist: Iterable[str] = _DEFAULT_BLOCKLIST):
        self.model_name = model_name
        self.dispatch_threshold = dispatch_threshold
        self.confirm_low = confirm_low
        self.blocklist = frozenset(blocklist)
        self._model = None
        self._model_lock = threading.Lock()
        self._index_lock = threading.Lock()
        self._tool_names: list[str] = []
        self._tool_phrases: list[str] = []     # parallel to embedding rows
        self._phrase_to_tool: list[int] = []   # row index -> tool index
        self._embeddings: np.ndarray | None = None
        self._index_signature = ""             # hash of names; rebuild on change
        # Adaptive Intent Phase 4: personal learned phrasings, kept separate
        # from the curated catalog so a rebuild never clobbers them. Folded
        # into the index on every build + appended incrementally by add_phrase.
        self._personal: list[tuple[str, str]] = []  # (phrase, tool)
        # Adaptive Intent Phase 5: optional profile tie-breaker. Given the list
        # of near-tied (tool, score) candidates it returns the preferred tool
        # name (or None to keep the cosine winner). Injected by FridayApp.
        self._tie_breaker = None
        self.tie_epsilon = TIE_EPSILON

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def build_index(self, tools_by_name: dict) -> None:
        """Rebuild the embedding index from the current tool registry.

        ``tools_by_name`` is the router's ``_tools_by_name`` mapping
        ({name: route_dict}). Each route_dict has a 'spec' with name +
        description + (optional) context_terms.

        2026-05-24 — `data/tool_catalog.yaml` is now the preferred source
        of phrases. When a catalog entry exists for a tool, its curated
        ``example_phrases`` REPLACE the auto-generated noun-cloud from
        plugin `aliases` / `context_terms` (which produced low-quality
        embeddings — e.g. `context_terms=["search online", "web"]` and
        `description="Search the web for current information"` were the
        only signal for `web_search`, so cosine barely beat noise).
        Tools without a catalog entry keep the legacy path so this isn't
        a breaking change while the catalog is incomplete.
        """
        sig = ",".join(sorted(tools_by_name.keys()))
        if sig == self._index_signature and self._embeddings is not None:
            return

        # Lazy-import to avoid a hard dependency cycle at module load time.
        try:
            from core.tool_catalog import get_catalog  # noqa: PLC0415
            catalog = get_catalog()
        except Exception as exc:
            logger.debug("[embed-router] catalog unavailable: %s", exc)
            catalog = None

        with self._index_lock:
            if sig == self._index_signature and self._embeddings is not None:
                return

            tool_names: list[str] = []
            phrases: list[str] = []
            phrase_to_tool: list[int] = []

            for name, route in tools_by_name.items():
                if name in self.blocklist:
                    continue
                spec = route.get("spec", {}) if isinstance(route, dict) else {}
                meta = route.get("capability_meta") or {}
                if meta.get("embeddable") is False:
                    continue

                tool_idx = len(tool_names)
                tool_names.append(name)

                catalog_entry = catalog.entry_for(name) if catalog is not None else None

                if catalog_entry and catalog_entry.example_phrases:
                    # Curated path — name + summary + every example phrase.
                    phrases.append(name.replace("_", " "))
                    phrase_to_tool.append(tool_idx)
                    if catalog_entry.summary:
                        phrases.append(catalog_entry.summary[:280])
                        phrase_to_tool.append(tool_idx)
                    for phrase in catalog_entry.example_phrases:
                        if phrase:
                            phrases.append(phrase[:200])
                            phrase_to_tool.append(tool_idx)
                    continue

                # Legacy fallback for tools missing from the catalog.
                description = (spec.get("description") or "").strip()
                if description:
                    phrases.append(description[:280])
                    phrase_to_tool.append(tool_idx)

                # Tool name itself, lightly humanised
                phrases.append(name.replace("_", " "))
                phrase_to_tool.append(tool_idx)

                for term in (spec.get("context_terms") or []):
                    term = (term or "").strip()
                    if not term:
                        continue
                    phrases.append(term)
                    phrase_to_tool.append(tool_idx)

            # Phase 4: fold in personal learned phrasings. They map onto the
            # tool's existing index when registered; a learned phrase for a
            # not-yet-indexed tool appends a new tool entry.
            for phrase, tool in self._personal:
                phrase = (phrase or "").strip()
                if not phrase or tool in self.blocklist:
                    continue
                if tool in tool_names:
                    tool_idx = tool_names.index(tool)
                else:
                    tool_idx = len(tool_names)
                    tool_names.append(tool)
                phrases.append(phrase[:200])
                phrase_to_tool.append(tool_idx)

            if not phrases:
                self._tool_names = []
                self._tool_phrases = []
                self._phrase_to_tool = []
                self._embeddings = None
                self._index_signature = sig
                return

            model = self._get_model()
            if model is None:
                logger.warning("[embed-router] Sentence-transformer unavailable; "
                               "router disabled.")
                return

            try:
                embeddings = model.encode(
                    phrases,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
            except Exception as exc:
                logger.error("[embed-router] Failed to embed tool phrases: %s", exc)
                self._embeddings = None
                return

            self._tool_names = tool_names
            self._tool_phrases = phrases
            self._phrase_to_tool = phrase_to_tool
            self._embeddings = embeddings.astype(np.float32, copy=False)
            self._index_signature = sig
            logger.info("[embed-router] Indexed %d phrases across %d tools.",
                        len(phrases), len(tool_names))

    def add_phrase(self, phrase: str, tool: str) -> bool:
        """Register a personal learned phrasing for ``tool`` (Phase 4).

        Called by `skill_loader` and by the boot-time learned-phrase load.
        The phrase joins `_personal` (so it survives index rebuilds) and is
        embedded + appended to the live index immediately when the model is
        already resident. Structured-arg tools are skipped — an empty-args
        embedding dispatch would dead-end on them.
        """
        phrase = (phrase or "").strip()
        if not phrase or not tool or tool in self.blocklist:
            return False
        if (phrase, tool) in self._personal:
            return False
        self._personal.append((phrase, tool))
        # Incrementally fold into the live index so the new phrase is matchable
        # without waiting for a tool-set change to trigger a full rebuild.
        if self._embeddings is not None:
            self._append_to_index(phrase, tool)
        return True

    def _append_to_index(self, phrase: str, tool: str) -> None:
        model = self._get_model()
        if model is None:
            return
        try:
            emb = model.encode([phrase[:200]], normalize_embeddings=True,
                               convert_to_numpy=True, show_progress_bar=False)
        except Exception as exc:
            logger.debug("[embed-router] add_phrase encode failed: %s", exc)
            return
        with self._index_lock:
            if tool in self._tool_names:
                tool_idx = self._tool_names.index(tool)
            else:
                tool_idx = len(self._tool_names)
                self._tool_names.append(tool)
            self._tool_phrases.append(phrase[:200])
            self._phrase_to_tool.append(tool_idx)
            self._embeddings = np.vstack([self._embeddings,
                                          emb.astype(np.float32, copy=False)])

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def best_match(self, text: str) -> dict | None:
        """Return {'tool': str, 'score': float} for the top-1 tool, no threshold.

        This is the raw cosine result before any dispatch/confirm gating.
        `route` and `confirm_candidate` are thin threshold filters over it.
        Returns None only when there's no index, no model, or encoding fails.
        """
        if not text or not text.strip():
            return None
        if self._embeddings is None:
            return None

        model = self._get_model()
        if model is None:
            return None

        try:
            query_emb = model.encode(
                [text.strip()],
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )[0]
        except Exception as exc:
            logger.warning("[embed-router] Encode failed for %r: %s", text, exc)
            return None

        # Cosine similarity = dot product when both sides L2-normalized.
        scores = self._embeddings @ query_emb.astype(np.float32, copy=False)
        # Aggregate per-tool: max over the tool's phrases (best of N).
        per_tool: dict[int, float] = {}
        for i, score in enumerate(scores):
            tool_idx = self._phrase_to_tool[i]
            cur = per_tool.get(tool_idx, -1.0)
            if score > cur:
                per_tool[tool_idx] = float(score)

        if not per_tool:
            return None
        ranked = sorted(per_tool.items(), key=lambda kv: kv[1], reverse=True)
        best_tool_idx, best_score = ranked[0]
        best_tool = self._tool_names[best_tool_idx]

        # Phase 5: among near-tied candidates, let the profile tie-breaker pick.
        if self._tie_breaker is not None and len(ranked) > 1:
            close = [(self._tool_names[i], s) for i, s in ranked
                     if best_score - s <= self.tie_epsilon]
            if len(close) > 1:
                try:
                    chosen = self._tie_breaker(close)
                except Exception:
                    chosen = None
                if chosen and chosen in dict(close):
                    return {"tool": chosen, "score": dict(close)[chosen]}
        return {"tool": best_tool, "score": best_score}

    def set_tie_breaker(self, fn) -> None:
        """Inject a profile tie-breaker: ``fn(list[(tool, score)]) -> tool|None``."""
        self._tie_breaker = fn

    def route(self, text: str) -> dict | None:
        """Return {'tool': str, 'score': float} if a confident match exists."""
        match = self.best_match(text)
        if match is None or match["score"] < self.dispatch_threshold:
            return None
        return match

    def confirm_candidate(self, text: str) -> dict | None:
        """Return the mid-band match worth a "did you mean …?" confirmation.

        Fires only when the top-1 cosine lands in [confirm_low,
        dispatch_threshold) — too weak to auto-dispatch, too strong to drop.
        Skips tools that aren't safe for an empty-args dispatch (catalog
        `blocked_from_chat_preflight`), since confirming a tool we can't
        actually run with the args we have would just dead-end.
        """
        match = self.best_match(text)
        if match is None:
            return None
        score = match["score"]
        if not (self.confirm_low <= score < self.dispatch_threshold):
            return None
        try:
            from core.tool_catalog import get_catalog  # noqa: PLC0415
            catalog = get_catalog()
            entry = catalog.entry_for(match["tool"]) if catalog else None
            if entry is not None and not entry.is_safe_for_preflight:
                return None
        except Exception:
            pass
        return match

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_model(self):
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            # Reuse the shared singleton so all-MiniLM-L6-v2 is resident once
            # for both routing and memory recall (RAG overhaul 2026-05-25).
            try:
                from core.memory.embeddings import (  # noqa: PLC0415
                    get_shared_embedder, SentenceTransformerEmbedder,
                )
                shared = get_shared_embedder(self.model_name)
                if isinstance(shared, SentenceTransformerEmbedder):
                    self._model = shared.model
                    logger.info("[embed-router] Reusing shared embedder %s.", self.model_name)
                    return self._model
            except Exception as exc:
                logger.debug("[embed-router] shared embedder unavailable: %s", exc)
            try:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            except ImportError:
                logger.warning("[embed-router] sentence-transformers not installed.")
                return None

            cache_dir = os.environ.get("FRIDAY_ST_CACHE") or os.path.join(
                os.path.expanduser("~"), ".cache", "huggingface"
            )
            try:
                self._model = SentenceTransformer(
                    self.model_name,
                    cache_folder=cache_dir,
                    device="cpu",  # tiny model — GPU launch overhead > inference
                )
                logger.info("[embed-router] Loaded %s.", self.model_name)
            except Exception as exc:
                logger.error("[embed-router] Could not load %s: %s",
                             self.model_name, exc)
                self._model = None
        return self._model

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        return {
            "indexed_tools": len(self._tool_names),
            "indexed_phrases": len(self._tool_phrases),
            "model": self.model_name,
            "loaded": self._model is not None,
            "threshold": self.dispatch_threshold,
        }

    # ------------------------------------------------------------------
    # Chat-side pre-flight reroute (2026-05-24)
    # ------------------------------------------------------------------

    def preflight_route(self, text: str, threshold: float | None = None) -> dict | None:
        """Variant of :meth:`route` used by the chat plugin before generation.

        Differs from `route` in two ways:
          1. Honours the catalog's `blocked_from_chat_preflight` flag —
             tools that need structured args (volume %, reminder time)
             are skipped so an empty-args dispatch doesn't surprise the
             user.
          2. Accepts an explicit threshold override for callers that want
             a stricter bar than the default.
        """
        try:
            from core.tool_catalog import get_catalog  # noqa: PLC0415
            catalog = get_catalog()
        except Exception:
            catalog = None

        result = self.route(text)
        if result is None:
            return None
        if threshold is not None and result["score"] < threshold:
            return None
        if catalog is not None:
            entry = catalog.entry_for(result["tool"])
            if entry and not entry.is_safe_for_preflight:
                return None
        return result
