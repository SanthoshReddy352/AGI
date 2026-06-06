"""Lexical (fuzzy) tool router — Adaptive Intent Recognition, Phase 3.

Sits between the deterministic regex/keyword layer and the embedding router.
It catches the cheap-to-fix near-misses the regex layer drops but that don't
need a 384-dim cosine to resolve: STT mishears ("lock the screem"), light
typos ("scrennshot"), and word-order shuffles ("screen lock the").

Mechanism: rapidfuzz `token_set_ratio` over the curated catalog phrases
(plus an optional set of learned phrasings) with a small synonym pre-expansion
("luminosity"→"brightness", "pic"→"screenshot"). It is deliberately
conservative — it only auto-dispatches when the best match clears a high
threshold *and* beats the runner-up by a margin, so it never poaches a turn
that the embedding/LLM layers should arbitrate.

rapidfuzz is the declared dependency (requirements.txt) and the fast path; a
pure-stdlib `difflib` fallback keeps the router functional if it's absent, so
importing this module never hard-fails.
"""
from __future__ import annotations

import difflib
import re
from typing import Iterable

from core.logger import logger

try:  # fast path — C-accelerated token_set_ratio
    from rapidfuzz import fuzz as _rf_fuzz  # noqa: PLC0415
    _HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover - exercised only on minimal installs
    _rf_fuzz = None
    _HAVE_RAPIDFUZZ = False


# token_set_ratio is 0..100. 88 is high enough that only genuine near-misses
# clear it (a typo or reordering), not loosely-related phrasings — those are
# the embedding router's job.
LEXICAL_THRESHOLD = 88.0

# The winner must beat the runner-up tool by at least this many points,
# otherwise the match is ambiguous and we defer to the embedding/LLM layers.
LEXICAL_MARGIN = 6.0

# Light, hand-curated synonym folding applied to the *query* before scoring.
# Keep this tiny and high-precision — it's a nudge for common STT/word choices,
# not a thesaurus. Maps spoken/alt word -> the token used in catalog phrases.
_SYNONYMS = {
    "luminosity": "brightness",
    "brightness": "brightness",
    "dimmer": "brightness",
    "sound": "volume",
    "audio": "volume",
    "loudness": "volume",
    "pic": "screenshot",
    "picture": "screenshot",
    "snap": "screenshot",
    "snapshot": "screenshot",
    "screengrab": "screenshot",
    "screem": "screen",     # frequent STT miss for "screen"
    "lock": "lock",
    "battery": "battery",
    "charge": "battery",
}

_WORD_RE = re.compile(r"[a-z0-9]+")

# Reuse the embedding router's structured-arg blocklist: a fuzzy match
# dispatches with empty args too, so the same tools must be excluded.
try:
    from core.embedding_router import _DEFAULT_BLOCKLIST as _EMBED_BLOCKLIST
except Exception:  # pragma: no cover
    _EMBED_BLOCKLIST = frozenset()


def _normalize(text: str) -> str:
    return " ".join(_WORD_RE.findall((text or "").lower()))


def _expand_synonyms(text: str) -> str:
    return " ".join(_SYNONYMS.get(tok, tok) for tok in text.split())


def _token_set_ratio(a: str, b: str) -> float:
    if _HAVE_RAPIDFUZZ:
        return float(_rf_fuzz.token_set_ratio(a, b))
    # Pure-stdlib approximation: compare sorted token sets so word order and
    # duplicate tokens don't penalise the score (the spirit of token_set_ratio).
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    sa, sb = " ".join(sorted(ta)), " ".join(sorted(tb))
    return difflib.SequenceMatcher(None, sa, sb).ratio() * 100.0


class LexicalRouter:
    """Conservative fuzzy router over catalog + learned phrasings."""

    def __init__(self, threshold: float = LEXICAL_THRESHOLD,
                 margin: float = LEXICAL_MARGIN,
                 blocklist: Iterable[str] = _EMBED_BLOCKLIST):
        self.threshold = threshold
        self.margin = margin
        self.blocklist = frozenset(blocklist)
        self._phrases: list[str] = []        # normalized + synonym-folded
        self._phrase_to_tool: list[str] = []
        self._signature = ""

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def build_index(self, tools_by_name: dict,
                    extra_phrases: Iterable[tuple[str, str]] | None = None) -> None:
        """(Re)build the phrase index from the catalog + any extra phrases.

        ``extra_phrases`` is an iterable of ``(phrase, tool)`` — Phase 4 feeds
        promoted learned phrasings here so they get fuzzy matching too.
        """
        extra = list(extra_phrases or [])
        sig = ",".join(sorted(tools_by_name.keys())) + "|" + str(len(extra))
        if sig == self._signature and self._phrases:
            return
        try:
            from core.tool_catalog import get_catalog  # noqa: PLC0415
            catalog = get_catalog()
        except Exception as exc:
            logger.debug("[lexical-router] catalog unavailable: %s", exc)
            catalog = None

        phrases: list[str] = []
        phrase_to_tool: list[str] = []

        def _add(raw: str, tool: str) -> None:
            folded = _expand_synonyms(_normalize(raw))
            if folded:
                phrases.append(folded)
                phrase_to_tool.append(tool)

        for name in tools_by_name:
            if name in self.blocklist:
                continue
            entry = catalog.entry_for(name) if catalog is not None else None
            if entry is not None and not entry.is_safe_for_preflight:
                continue
            _add(name.replace("_", " "), name)
            if entry is not None:
                for phrase in entry.example_phrases:
                    _add(phrase, name)
        for phrase, tool in extra:
            if tool not in self.blocklist:
                _add(phrase, tool)

        self._phrases = phrases
        self._phrase_to_tool = phrase_to_tool
        self._signature = sig
        logger.info("[lexical-router] Indexed %d phrases across %d tools.",
                    len(phrases), len(set(phrase_to_tool)))

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def route(self, text: str) -> dict | None:
        """Return {'tool', 'score', 'phrase'} for a confident fuzzy match.

        Fires only when the best tool clears ``threshold`` AND beats the next
        best *tool* by ``margin``. Returns None otherwise.
        """
        if not text or not text.strip() or not self._phrases:
            return None
        query = _expand_synonyms(_normalize(text))
        if not query:
            return None

        best_per_tool: dict[str, tuple[float, str]] = {}
        for phrase, tool in zip(self._phrases, self._phrase_to_tool):
            score = _token_set_ratio(query, phrase)
            cur = best_per_tool.get(tool)
            if cur is None or score > cur[0]:
                best_per_tool[tool] = (score, phrase)
        if not best_per_tool:
            return None

        ranked = sorted(best_per_tool.items(), key=lambda kv: kv[1][0], reverse=True)
        top_tool, (top_score, top_phrase) = ranked[0]
        if top_score < self.threshold:
            return None
        if len(ranked) > 1 and (top_score - ranked[1][1][0]) < self.margin:
            return None
        return {"tool": top_tool, "score": top_score, "phrase": top_phrase}

    def stats(self) -> dict:
        return {
            "indexed_phrases": len(self._phrases),
            "indexed_tools": len(set(self._phrase_to_tool)),
            "threshold": self.threshold,
            "margin": self.margin,
            "backend": "rapidfuzz" if _HAVE_RAPIDFUZZ else "difflib",
        }
