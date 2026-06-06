"""Track 5.1c — MemoryStore.

Extracted from `core.context_store.ContextStore`. Owns two SQL tables
(`facts`, `memory_items`) plus the Chroma vector index used for
semantic_recall. The `HashEmbeddingFunction` that Chroma uses is
defined here because it's a MemoryStore-internal detail.

Every method here is ≤30 lines (Direction §5.1 rule). The 47-line
`store_memory_item` was split into `upsert_memory_item` (SQL write) +
`upsert_vector` (vector index write) + the public wrapper. The 44-line
`_fallback_semantic_recall` was split into the candidate-collection +
scoring helpers.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from collections import Counter
from datetime import datetime, timezone

from core.logger import logger
from core.memory.embeddings import HashEmbedder, get_shared_embedder


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text):
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in str(text or ""))
    return [token for token in cleaned.split() if len(token) > 1]


def _to_fts_match(query) -> str:
    """Turn arbitrary user text into a safe FTS5 MATCH expression.

    Raw user input ("Computer Science, AI & ML, ...") goes straight into
    ``MATCH`` and FTS5 parses ``,`` ``.`` ``@`` ``&`` as query operators —
    raising ``fts5: syntax error near ","``. We tokenize to bare alphanumeric
    words, wrap each in double quotes (so even reserved words are literals),
    and OR them together for broad recall. Returns "" when nothing is left to
    match on, so callers can short-circuit instead of running an empty query.
    """
    tokens = _tokenize(query)
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens)


def _migrations_path() -> str:
    return os.path.join(os.path.dirname(__file__), "migrations", "memory.sql")


class HashEmbeddingFunction:
    """Deterministic embedding function for local semantic recall.

    Keeps Chroma usable without downloading a heavy embedding model.
    Implements the ChromaDB 1.x EmbeddingFunction protocol (`name()` /
    `get_config()` / `build_from_config()`) so the collection can be
    persisted and re-opened across runs.
    """

    _NAME = "friday-hash-v1"

    def __init__(self, dimensions=64):
        self.dimensions = max(16, int(dimensions))

    def __call__(self, input):
        if isinstance(input, str):
            input = [input]
        embeddings = []
        for text in input:
            vector = [0.0] * self.dimensions
            for token in _tokenize(text):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vector[index] += sign
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            embeddings.append([v / norm for v in vector])
        return embeddings

    def embed_query(self, input):
        return self.__call__(input)

    def embed_documents(self, input):
        return self.__call__(input)

    @staticmethod
    def name() -> str:
        return HashEmbeddingFunction._NAME

    def get_config(self) -> dict:
        return {"dimensions": int(self.dimensions)}

    @staticmethod
    def build_from_config(config: dict) -> "HashEmbeddingFunction":
        return HashEmbeddingFunction(dimensions=int((config or {}).get("dimensions", 64)))

    def default_space(self) -> str:
        return "cosine"

    @staticmethod
    def supported_spaces():
        return ["cosine", "l2", "ip"]

    def is_legacy(self) -> bool:
        return False

    def signature(self) -> str:
        return f"{self._NAME}:{self.dimensions}"


class SemanticEmbeddingFunction:
    """Chroma EmbeddingFunction backed by the shared sentence-transformer.

    MemoryStore only installs this when the shared embedder is a real
    model; the hash function above remains the offline fallback. Implements
    the ChromaDB 1.x EmbeddingFunction protocol so the collection persists
    and re-opens across runs.
    """

    _NAME = "friday-st-v1"

    def __init__(self, embedder=None, model_name: str | None = None):
        self._embedder = embedder or get_shared_embedder(model_name)
        self._model_name = getattr(self._embedder, "model_name", "hash")
        self._dim = int(getattr(self._embedder, "dimensions", 384))

    def __call__(self, input):
        if isinstance(input, str):
            input = [input]
        return [[float(x) for x in vec] for vec in self._embedder.embed(list(input))]

    def embed_query(self, input):
        return self.__call__(input)

    def embed_documents(self, input):
        return self.__call__(input)

    @staticmethod
    def name() -> str:
        return SemanticEmbeddingFunction._NAME

    def get_config(self) -> dict:
        return {"model_name": self._model_name, "dimensions": self._dim}

    @staticmethod
    def build_from_config(config: dict) -> "SemanticEmbeddingFunction":
        return SemanticEmbeddingFunction(model_name=(config or {}).get("model_name"))

    def default_space(self) -> str:
        return "cosine"

    @staticmethod
    def supported_spaces():
        return ["cosine", "l2", "ip"]

    def is_legacy(self) -> bool:
        return False

    def signature(self) -> str:
        return f"{self._NAME}:{self._model_name}:{self._dim}"


class MemoryStore:
    """Fact + memory-item persistence with vector-backed semantic recall.

    Owns `facts` and `memory_items` SQL tables plus a Chroma vector
    collection. Cross-store reads (e.g. semantic_recall reading from
    `turns`) go through raw SQL — same DB file, read-anywhere is fine;
    write-ownership is the rule.
    """

    # Resilience tuning (Track 2). After this many consecutive vector
    # failures the store pauses Chroma for a cooldown window rather than
    # disabling it permanently for the process lifetime.
    _VECTOR_FAIL_THRESHOLD = 3
    _VECTOR_COOLDOWN_SEC = 60.0

    def __init__(self, db_path: str, vector_path: str):
        self.db_path = db_path
        self.vector_path = vector_path
        self._vector_collection = None
        self._vector_client = None
        self._vector_available = False
        self._embedder_signature = ""
        self._vector_fail_count = 0
        self._vector_cooldown_until = 0.0
        self._ensure_storage()
        self._init_vector_store()

    # ------------------------------------------------------------------
    # Schema + vector init
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_storage(self) -> None:
        _db_dir = os.path.dirname(self.db_path)
        if _db_dir:
            os.makedirs(_db_dir, exist_ok=True)
        os.makedirs(self.vector_path, exist_ok=True)
        with open(_migrations_path(), "r", encoding="utf-8") as fh:
            schema_sql = fh.read()
        with self._connect() as conn:
            conn.executescript(schema_sql)
            conn.commit()

    def _embedding_function(self):
        """Pick the Chroma embedding function and its signature.

        Real model → semantic embeddings. Offline (hash) fallback keeps the
        system usable at keyword grade. The signature pins the collection to
        a model+dim so a model change triggers a lazy rebuild (Track 3).
        """
        embedder = get_shared_embedder()
        if isinstance(embedder, HashEmbedder) or not hasattr(embedder, "model_name"):
            ef = HashEmbeddingFunction()
            return ef, ef.signature()
        ef = SemanticEmbeddingFunction(embedder=embedder)
        return ef, ef.signature()

    def _init_vector_store(self) -> None:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=self.vector_path)
            ef, sig = self._embedding_function()
            self._maybe_rebuild_collection(client, sig)
            self._vector_collection = client.get_or_create_collection(
                name="friday_memory",
                embedding_function=ef,
                metadata={"embedder_sig": sig, "hnsw:space": "cosine"},
            )
            self._vector_client = client
            self._embedder_signature = sig
            self._vector_available = True
            self._vector_fail_count = 0
            self._vector_cooldown_until = 0.0
        except Exception as e:
            logger.info("[memory_store] Vector store unavailable: %s", e)
            self._vector_collection = None
            self._vector_available = False

    @staticmethod
    def _maybe_rebuild_collection(client, sig: str) -> None:
        """Track 3 — drop `friday_memory` if it was built with a different
        embedder (e.g. the legacy 64-dim hash). Vectors then repopulate
        lazily as new memories are written; call `reindex_memory()` for an
        immediate backfill from SQL.
        """
        try:
            existing = {c.name: c for c in client.list_collections()}
        except Exception:
            return
        col = existing.get("friday_memory")
        if col is None:
            return
        old_sig = (getattr(col, "metadata", None) or {}).get("embedder_sig")
        if old_sig != sig:
            logger.warning(
                "[memory_store] Embedder changed (%s -> %s); rebuilding vector index "
                "(memories re-embed lazily; run reindex_memory() to backfill now).",
                old_sig, sig,
            )
            try:
                client.delete_collection("friday_memory")
            except Exception as exc:
                logger.warning("[memory_store] Could not drop stale collection: %s", exc)

    # ------------------------------------------------------------------
    # Vector resilience (Track 2) — cooldown instead of permanent disable
    # ------------------------------------------------------------------

    def _vector_ready(self) -> bool:
        """True if the vector collection is usable right now. Attempts a
        re-init once a prior failure cooldown has elapsed."""
        if self._vector_available and self._vector_collection is not None:
            return True
        if time.time() < self._vector_cooldown_until:
            return False
        self._init_vector_store()
        return self._vector_available and self._vector_collection is not None

    def _note_vector_failure(self, exc: Exception) -> None:
        self._vector_fail_count += 1
        logger.warning("[memory_store] vector op failed (%d/%d): %s",
                       self._vector_fail_count, self._VECTOR_FAIL_THRESHOLD, exc)
        if self._vector_fail_count >= self._VECTOR_FAIL_THRESHOLD:
            self._vector_available = False
            self._vector_collection = None
            self._vector_cooldown_until = time.time() + self._VECTOR_COOLDOWN_SEC
            self._vector_fail_count = 0
            logger.warning("[memory_store] vector store paused %.0fs after repeated failures.",
                           self._VECTOR_COOLDOWN_SEC)

    # ------------------------------------------------------------------
    # Vector index (used by other domains' cross-domain writes too)
    # ------------------------------------------------------------------

    def upsert_vector(self, item_id: str, text: str, metadata: dict) -> None:
        """Index a text snippet in the vector store under a stable id.

        Called by other domains (workflow summaries, persona examples)
        for cross-domain memory writes. Failure is non-fatal — the
        vector store is best-effort.
        """
        if not text:
            return
        if not self._vector_ready():
            return
        try:
            self._vector_collection.upsert(
                ids=[item_id],
                documents=[text],
                metadatas=[metadata],
            )
            self._vector_fail_count = 0
        except Exception as exc:
            self._note_vector_failure(exc)

    # ------------------------------------------------------------------
    # facts
    # ------------------------------------------------------------------

    def store_fact(self, key: str, value, session_id: str = "",
                   namespace: str = "general") -> None:
        if not key:
            return
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO facts (session_id, namespace, key, value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, namespace, key)
                DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (session_id or "", namespace, key, value, now),
            )
            conn.commit()
        self.upsert_vector(
            item_id=f"fact:{session_id or 'global'}:{namespace}:{key}",
            text=f"{key}: {value}",
            metadata={
                "session_id": session_id or "",
                "kind": "fact",
                "namespace": namespace,
                "key": key,
            },
        )

    def get_facts_by_namespace(self, namespace: str = "general") -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM facts WHERE namespace = ? ORDER BY updated_at DESC",
                (namespace,),
            ).fetchall()
        return [{"key": k, "value": v} for k, v in rows]

    # ------------------------------------------------------------------
    # memory_items
    # ------------------------------------------------------------------

    def store_memory_item(self, session_id, content, memory_type="episodic",
                          persona_id="", sensitivity="safe_auto", metadata=None):
        if not content:
            return
        payload = dict(metadata or {})
        item_id = str(payload.get("item_id") or uuid.uuid4())
        content_text = str(content).strip()
        self._upsert_memory_item_row(
            item_id, session_id, persona_id, memory_type,
            sensitivity, content_text, payload,
        )
        self.upsert_vector(
            item_id=f"memory:{item_id}",
            text=content_text,
            metadata={
                "session_id": session_id or "",
                "persona_id": persona_id or "",
                "kind": memory_type or "episodic",
                "sensitivity": sensitivity or "safe_auto",
                "created_at": _utc_now(),
            },
        )

    def _upsert_memory_item_row(self, item_id, session_id, persona_id,
                                memory_type, sensitivity, content_text, payload):
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_items (
                    item_id, session_id, persona_id, memory_type, sensitivity,
                    content, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id)
                DO UPDATE SET
                    session_id = excluded.session_id,
                    persona_id = excluded.persona_id,
                    memory_type = excluded.memory_type,
                    sensitivity = excluded.sensitivity,
                    content = excluded.content,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    item_id, session_id or "", persona_id or "",
                    memory_type or "episodic", sensitivity or "safe_auto",
                    content_text, json.dumps(payload, ensure_ascii=True), now, now,
                ),
            )
            conn.commit()

    def recent_memory_items(self, session_id, limit=6, persona_id=None) -> list:
        params: list = [session_id or ""]
        query = (
            "SELECT item_id, session_id, persona_id, memory_type, sensitivity, "
            "content, metadata_json, created_at, updated_at "
            "FROM memory_items WHERE session_id = ?"
        )
        if persona_id:
            query += " AND (persona_id = ? OR persona_id = '')"
            params.append(persona_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_memory_item(r) for r in rows]

    @staticmethod
    def _row_to_memory_item(row) -> dict:
        (item_id, sid, pid, memory_type, sensitivity,
         content, metadata_json, created_at, updated_at) = row
        return {
            "item_id": item_id,
            "session_id": sid,
            "persona_id": pid,
            "memory_type": memory_type,
            "sensitivity": sensitivity,
            "content": content,
            "metadata": json.loads(metadata_json or "{}"),
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def delete_memory_item(self, item_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_items WHERE item_id = ?", (item_id,))
            conn.commit()

    def prune_low_confidence_memories(self, session_id: str,
                                      min_confidence: float = 0.5) -> int:
        items = self.recent_memory_items(session_id, limit=500) or []
        removed = 0
        for item in items:
            if item.get("memory_type") != "semantic":
                continue
            meta = item.get("metadata") or {}
            if float(meta.get("confidence", 1.0)) < min_confidence:
                self.delete_memory_item(item["item_id"])
                removed += 1
        return removed

    # ------------------------------------------------------------------
    # FTS5 keyword search over turns (P3.2)
    # ------------------------------------------------------------------

    def fts_search(self, query: str, limit: int = 10,
                   session_id: str | None = None) -> list:
        """Keyword search across past turns via the SessionStore-owned
        `turns_fts` virtual table. Cross-store READ is OK; the table is
        owned by SessionStore but lives in the same SQLite file.
        Returns newest-first dicts with id/session_id/role/text/created_at.
        Optionally constrained to a single session.
        """
        if not query or not query.strip():
            return []
        match_expr = _to_fts_match(query)
        if not match_expr:
            # Query was all punctuation/stopword noise — nothing to match on.
            return []
        sql = (
            "SELECT t.id, t.session_id, t.role, t.text, t.created_at "
            "FROM turns t JOIN turns_fts f ON t.id = f.rowid "
            "WHERE turns_fts MATCH ?"
        )
        params: list = [match_expr]
        if session_id:
            sql += " AND t.session_id = ?"
            params.append(session_id)
        sql += " ORDER BY rank LIMIT ?"
        params.append(max(1, int(limit)))
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning("[memory_store] FTS query failed: %s", exc)
            return []
        return [
            {"id": r[0], "session_id": r[1], "role": r[2],
             "text": r[3], "created_at": r[4]}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # semantic recall — hybrid (dense + sparse) → fuse → filter → rerank
    # ------------------------------------------------------------------

    # Type weighting for ranking (Track 6). Durable knowledge outranks
    # raw episodic chatter when scores are otherwise close.
    _TYPE_WEIGHT = {"semantic": 1.15, "procedural": 1.10, "fact": 1.10,
                    "episodic": 1.0}
    _RECENCY_HALF_LIFE_DAYS = float(os.environ.get("FRIDAY_RECALL_HALFLIFE_DAYS", "30"))

    def semantic_recall(self, query: str, session_id: str, limit: int = 3,
                        persona_id: str | None = None) -> list:
        """Hybrid recall: Reciprocal-Rank-Fuse dense (vector) + sparse (FTS5)
        candidates, apply recency/persona/type weighting, then MMR-select for
        relevance + diversity. Degrades to token-overlap recall when no
        candidates surface (e.g. offline hash embedder, empty index)."""
        if not query:
            return []
        pool = max(int(limit) * 4, 12)
        dense = self._dense_candidates(query, session_id, pool)
        sparse = self._sparse_candidates(query, session_id, pool)
        fused = self._rrf_fuse(dense, sparse)
        if not fused:
            return self._fallback_semantic_recall(query, session_id, limit=limit)
        scored = self._apply_recall_filters(fused, persona_id)
        ranked = self._mmr_select(query, scored, limit)
        ranked = self._maybe_cross_encode(query, ranked, limit)
        return [c["text"] for c in ranked[:max(1, int(limit))]]

    def _dense_candidates(self, query: str, session_id: str, n: int) -> list:
        if not self._vector_ready():
            return []
        try:
            resp = self._vector_collection.query(
                query_texts=[query], n_results=n,
                where={"session_id": session_id},
            )
            self._vector_fail_count = 0
        except Exception as exc:
            self._note_vector_failure(exc)
            return []
        docs = (resp.get("documents") or [[]])[0]
        metas = (resp.get("metadatas") or [[]])[0]
        out = []
        for rank, doc in enumerate(docs):
            if not doc:
                continue
            meta = metas[rank] if rank < len(metas) else {}
            out.append({"text": doc, "rank": rank, "source": "dense",
                        "kind": (meta or {}).get("kind", ""),
                        "persona_id": (meta or {}).get("persona_id", ""),
                        "created_at": (meta or {}).get("created_at", "")})
        return out

    def _sparse_candidates(self, query: str, session_id: str, n: int) -> list:
        rows = self.fts_search(query, limit=n, session_id=session_id)
        return [{"text": r["text"], "rank": rank, "source": "sparse",
                 "kind": "episodic", "persona_id": "",
                 "created_at": r.get("created_at", "")}
                for rank, r in enumerate(rows) if r.get("text")]

    @staticmethod
    def _rrf_fuse(dense: list, sparse: list, k: int = 60) -> list:
        """Reciprocal Rank Fusion: score = Σ 1/(k+rank) across lists, keyed
        by text so the same memory found by both retrievers reinforces."""
        merged: dict = {}
        for lst in (dense, sparse):
            for item in lst:
                key = item["text"]
                entry = merged.get(key)
                if entry is None:
                    entry = dict(item)
                    entry["score"] = 0.0
                    merged[key] = entry
                entry["score"] += 1.0 / (k + item["rank"] + 1)
                # Prefer richer metadata (dense carries kind/persona/created_at)
                if item["source"] == "dense":
                    entry.update({"kind": item["kind"],
                                  "persona_id": item["persona_id"],
                                  "created_at": item["created_at"]})
        return sorted(merged.values(), key=lambda e: e["score"], reverse=True)

    def _apply_recall_filters(self, items: list, persona_id: str | None) -> list:
        """Track 6 — multiply fused scores by recency decay, persona match,
        and memory-type weight."""
        for it in items:
            factor = self._TYPE_WEIGHT.get(it.get("kind") or "episodic", 1.0)
            factor *= self._recency_factor(it.get("created_at"))
            if persona_id and it.get("persona_id") == persona_id:
                factor *= 1.2
            it["score"] *= factor
        return sorted(items, key=lambda e: e["score"], reverse=True)

    def _recency_factor(self, created_at) -> float:
        if not created_at:
            return 1.0
        try:
            ts = datetime.fromisoformat(str(created_at))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
        except Exception:
            return 1.0
        # Exponential half-life decay, floored so old memories still surface.
        return max(0.5, 0.5 ** (age_days / self._RECENCY_HALF_LIFE_DAYS))

    def _mmr_select(self, query: str, items: list, limit: int,
                    lambda_: float = 0.7) -> list:
        """Maximal Marginal Relevance: balance relevance to the query against
        novelty vs. already-selected items, so recall isn't 3 paraphrases of
        one memory. Reuses the shared embedder (cached)."""
        if len(items) <= 1:
            return items
        try:
            embedder = get_shared_embedder()
            texts = [it["text"] for it in items]
            vecs = embedder.embed([query] + texts)
        except Exception:
            return items[:limit]
        qv, doc_vecs = vecs[0], vecs[1:]
        rel = [self._cos(qv, dv) for dv in doc_vecs]
        selected: list[int] = []
        remaining = list(range(len(items)))
        while remaining and len(selected) < limit:
            best_i, best_val = remaining[0], -1e9
            for i in remaining:
                novelty = max((self._cos(doc_vecs[i], doc_vecs[j]) for j in selected),
                              default=0.0)
                val = lambda_ * rel[i] - (1 - lambda_) * novelty
                if val > best_val:
                    best_i, best_val = i, val
            selected.append(best_i)
            remaining.remove(best_i)
        return [items[i] for i in selected]

    @staticmethod
    def _cos(a, b) -> float:
        num = sum(x * y for x, y in zip(a, b))
        da = math.sqrt(sum(x * x for x in a)) or 1.0
        db = math.sqrt(sum(y * y for y in b)) or 1.0
        return num / (da * db)

    def _maybe_cross_encode(self, query: str, items: list, limit: int) -> list:
        """Optional cross-encoder rerank (Track 5), off unless FRIDAY_RERANK_MODEL
        is set. A cross-encoder scores (query, doc) jointly — more accurate than
        bi-encoder cosine but heavier, so it's opt-in and lazy-loaded."""
        model_name = os.environ.get("FRIDAY_RERANK_MODEL")
        if not model_name or len(items) <= 1:
            return items
        try:
            ce = self._get_cross_encoder(model_name)
            if ce is None:
                return items
            scores = ce.predict([(query, it["text"]) for it in items])
            for it, s in zip(items, scores):
                it["score"] = float(s)
            return sorted(items, key=lambda e: e["score"], reverse=True)
        except Exception as exc:
            logger.warning("[memory_store] cross-encoder rerank failed: %s", exc)
            return items

    def _get_cross_encoder(self, model_name: str):
        ce = getattr(self, "_cross_encoder", None)
        if ce is not None:
            return ce
        try:
            from sentence_transformers import CrossEncoder  # noqa: PLC0415
            self._cross_encoder = CrossEncoder(model_name, device="cpu")
        except Exception as exc:
            logger.warning("[memory_store] cross-encoder unavailable: %s", exc)
            self._cross_encoder = None
        return self._cross_encoder

    def reindex_memory(self, batch: int = 256) -> int:
        """Backfill the vector index from SQL (facts + memory_items). Use
        after an embedder change when you want old memories searchable
        immediately rather than waiting for them to be re-written."""
        if not self._vector_ready():
            return 0
        count = 0
        with self._connect() as conn:
            facts = conn.execute(
                "SELECT session_id, namespace, key, value FROM facts").fetchall()
            items = conn.execute(
                "SELECT item_id, session_id, persona_id, memory_type, sensitivity, "
                "content, updated_at FROM memory_items").fetchall()
        for sid, ns, key, value in facts:
            self.upsert_vector(
                f"fact:{sid or 'global'}:{ns}:{key}", f"{key}: {value}",
                {"session_id": sid or "", "kind": "fact", "namespace": ns, "key": key})
            count += 1
        for iid, sid, pid, mtype, sens, content, updated in items:
            self.upsert_vector(
                f"memory:{iid}", content,
                {"session_id": sid or "", "persona_id": pid or "",
                 "kind": mtype or "episodic", "sensitivity": sens or "safe_auto",
                 "created_at": updated or ""})
            count += 1
        logger.info("[memory_store] reindexed %d memories into vector store.", count)
        return count

    def _fallback_semantic_recall(self, query: str, session_id: str,
                                  limit: int = 3) -> list:
        query_tokens = Counter(_tokenize(query))
        if not query_tokens:
            return []
        candidates = self._candidates_for_fallback(session_id)
        return self._rank_candidates(candidates, query_tokens, limit)

    def _candidates_for_fallback(self, session_id: str) -> list:
        # Reads from `turns` (SessionStore territory) — cross-store
        # READ via shared DB is OK; write-ownership is the rule.
        with self._connect() as conn:
            turn_rows = conn.execute(
                "SELECT text FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT 50",
                (session_id,),
            ).fetchall()
            facts = conn.execute(
                "SELECT key, value FROM facts WHERE session_id = ? OR session_id = '' "
                "ORDER BY updated_at DESC LIMIT 20",
                (session_id,),
            ).fetchall()
        candidates = [text for (text,) in turn_rows if text]
        candidates.extend(f"{key}: {value}" for key, value in facts if key)
        return candidates

    @staticmethod
    def _rank_candidates(candidates: list, query_tokens: Counter,
                         limit: int) -> list:
        scored = []
        for text in candidates:
            tokens = Counter(_tokenize(text))
            overlap = sum(min(query_tokens[t], tokens[t]) for t in query_tokens)
            if overlap:
                scored.append((overlap, text))
        scored.sort(key=lambda item: (-item[0], -len(item[1])))
        unique, seen = [], set()
        for _, text in scored:
            if text not in seen:
                unique.append(text)
                seen.add(text)
            if len(unique) >= limit:
                break
        return unique
