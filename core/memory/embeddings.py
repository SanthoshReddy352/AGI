"""Embedding infrastructure for FRIDAY memory stores.

Provides a single process-wide semantic embedder shared by every memory
subsystem (MemoryStore vector recall, plan archive, …) so only one model
is ever resident in RAM. Falls back to a deterministic hash embedder when
sentence-transformers is not installed.

RAG overhaul (2026-05-25):
* ``get_shared_embedder()`` is the canonical entry point — a cached
  singleton over a real sentence-transformer (default all-MiniLM-L6-v2,
  384-dim). ``get_best_embedder()`` is kept as a back-compat alias.
* ``SentenceTransformerEmbedder`` lazy-loads the model, L2-normalizes,
  and keeps a content-hash LRU cache so identical text is embedded once
  (Track 7).

Usage:
    embedder = get_shared_embedder()        # shared singleton
    vectors = embedder.embed(["some text"])  # list[list[float]]
"""
from __future__ import annotations

import hashlib
import os
import struct
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import List

from core.logger import logger


# Default local model — matches the embedding_router so a single
# all-MiniLM-L6-v2 instance can serve both routing and memory recall.
# Override with FRIDAY_EMBED_MODEL (e.g. BAAI/bge-small-en-v1.5 for
# slightly higher retrieval quality at ~130 MB).
DEFAULT_MODEL = os.environ.get(
    "FRIDAY_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
_EMBED_CACHE_SIZE = int(os.environ.get("FRIDAY_EMBED_CACHE", "2048"))


def _content_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbedderProtocol(ABC):
    """Contract every embedder must satisfy."""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...


class HashEmbedder(EmbedderProtocol):
    """Deterministic SHA-256 based embedder — no model download required.

    Not semantically meaningful but provides consistent, stable vector
    identities for deduplication and approximate retrieval. Used as the
    low-memory fallback when sentence-transformers is unavailable.
    """

    def __init__(self, dimensions: int = 64):
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> List[float]:
        digest = hashlib.sha256(text.encode()).digest()
        # Tile digest to cover requested dimensions
        tiled = digest * ((self._dimensions // len(digest)) + 1)
        return [(struct.unpack_from("B", tiled, i)[0] / 255.0) * 2.0 - 1.0 for i in range(self._dimensions)]


class SentenceTransformerEmbedder(EmbedderProtocol):
    """Real local semantic embedder over any sentence-transformers model.

    Lazy-loads the model (first ``embed``/``dimensions`` call), L2-normalizes
    output, and caches vectors by content hash so repeated text — common in
    recall workloads — is embedded once. CPU by default; the tiny models we
    use have higher GPU launch overhead than inference cost.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = "cpu",
                 cache_size: int = _EMBED_CACHE_SIZE):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._dim: int | None = None
        self._load_lock = threading.Lock()
        self._cache: "OrderedDict[str, List[float]]" = OrderedDict()
        self._cache_size = max(0, int(cache_size))
        self._cache_lock = threading.Lock()

    @property
    def dimensions(self) -> int:
        if self._dim is None:
            self._ensure_model()
        return self._dim or 384

    @property
    def model(self):
        """Underlying SentenceTransformer — exposed so other subsystems
        (e.g. the embedding router) can reuse the one resident instance."""
        return self._ensure_model()

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        if getattr(self, "_model_failed", False):
            raise RuntimeError("model load previously failed; running hash-fallback mode")
        with self._load_lock:
            if self._model is not None:
                return self._model
            if getattr(self, "_model_failed", False):
                raise RuntimeError("model load previously failed; running hash-fallback mode")
            try:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415
                cache_dir = os.environ.get("FRIDAY_ST_CACHE") or os.path.join(
                    os.path.expanduser("~"), ".cache", "huggingface"
                )
                self._model = SentenceTransformer(
                    self.model_name, cache_folder=cache_dir, device=self.device
                )
                _dim_fn = (getattr(self._model, "get_embedding_dimension", None)
                           or self._model.get_sentence_embedding_dimension)
                self._dim = int(_dim_fn())
                logger.info("[embeddings] Loaded %s (dim=%d).", self.model_name, self._dim)
            except Exception:
                self._model_failed = True
                raise
        return self._model

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        results: list = [None] * len(texts)
        missing_idx: list[int] = []
        missing_txt: list[str] = []
        with self._cache_lock:
            for i, text in enumerate(texts):
                hit = self._cache.get(_content_key(text)) if self._cache_size else None
                if hit is not None:
                    self._cache.move_to_end(_content_key(text))
                    results[i] = hit
                else:
                    missing_idx.append(i)
                    missing_txt.append(text)
        if missing_txt:
            model = self._ensure_model()
            vectors = model.encode(
                missing_txt, normalize_embeddings=True,
                convert_to_numpy=True, show_progress_bar=False,
            )
            with self._cache_lock:
                for j, i in enumerate(missing_idx):
                    vec = vectors[j].tolist()
                    results[i] = vec
                    if self._cache_size:
                        self._cache[_content_key(texts[i])] = vec
                        while len(self._cache) > self._cache_size:
                            self._cache.popitem(last=False)
        return results


# Back-compat: BGE-small remains addressable by name for callers that
# explicitly want it. Most code should use get_shared_embedder().
class BGESmallEmbedder(SentenceTransformerEmbedder):
    MODEL_NAME = "BAAI/bge-small-en-v1.5"

    def __init__(self):
        super().__init__(model_name=self.MODEL_NAME)


_shared_lock = threading.Lock()
_shared_embedder: EmbedderProtocol | None = None


def get_shared_embedder(model_name: str | None = None) -> EmbedderProtocol:
    """Return the process-wide singleton embedder.

    Uses a real sentence-transformer when the package is installed,
    otherwise a deterministic HashEmbedder so the system still runs
    offline (with keyword-grade recall). All memory subsystems share the
    same instance to keep RAM to one resident model.
    """
    global _shared_embedder
    want = model_name or DEFAULT_MODEL
    cur = _shared_embedder
    if cur is not None and getattr(cur, "model_name", None) in (want, None):
        return cur
    with _shared_lock:
        cur = _shared_embedder
        if cur is not None and getattr(cur, "model_name", None) in (want, None):
            return cur
        try:
            import sentence_transformers  # noqa: F401  PLC0415
            embedder = SentenceTransformerEmbedder(model_name=want)
            embedder._ensure_model()  # fail fast if offline/not cached
            _shared_embedder = embedder
        except Exception as exc:  # ImportError or model load failure
            logger.warning(
                "[embeddings] sentence-transformers unavailable (%s); "
                "falling back to HashEmbedder (keyword-grade recall).", exc
            )
            _shared_embedder = HashEmbedder(dimensions=64)
    return _shared_embedder


def get_best_embedder() -> EmbedderProtocol:
    """Back-compat alias — returns the shared singleton."""
    return get_shared_embedder()
