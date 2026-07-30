"""Embedding client – OpenAI-compatible /embeddings API.

Design pattern adapted from mentat's embeddings.py:
- Batch requests (64 texts per call)
- Local disk cache to avoid re-billing for identical text
- Graceful degradation when embedding is not configured

Only the design pattern is ported; implementation is original.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import httpx
import numpy as np

from ..config.settings import get_data_dir

BATCH_SIZE = 64
CACHE_FILE_NAME = "embeddings.json"


# ─── Config helpers ─────────────────────────────────────────────

def _get_rag_config() -> dict:
    """Load rag config from settings."""
    from ..config.settings import load_config
    cfg = load_config()
    return cfg.get("rag", {})


def _get_embedding_config() -> dict:
    """Load embedding config, merging with active model's base_url/api_key."""
    rag_cfg = _get_rag_config()
    emb_cfg = dict(rag_cfg.get("embedding", {}))

    # If base_url / api_key not set in rag.embedding, try to reuse the
    # active model's credentials.
    if not emb_cfg.get("base_url") or not emb_cfg.get("api_key"):
        from ..config.settings import get_active_model_config
        try:
            mc = get_active_model_config()
            if not emb_cfg.get("base_url"):
                emb_cfg["base_url"] = mc.get("base_url")
            if not emb_cfg.get("api_key"):
                emb_cfg["api_key"] = mc.get("api_key")
        except (ValueError, KeyError):
            pass

    return emb_cfg


def get_embedding_config() -> dict:
    """Return the effective runtime embedding config.

    The mapping can contain a resolved API key and must never be persisted.
    """
    return dict(_get_embedding_config())


def is_embedding_available() -> bool:
    """Return True if embedding is configured and enabled."""
    cfg = _get_rag_config()
    if not cfg.get("enabled", False):
        return False
    emb = get_embedding_config()
    base_url = emb.get("base_url")
    api_key = emb.get("api_key")
    model = emb.get("model")
    return bool(base_url and api_key and model)


# ─── Cache ──────────────────────────────────────────────────────

def _cache_dir() -> Path:
    d = get_data_dir() / "rag_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path() -> Path:
    return _cache_dir() / CACHE_FILE_NAME


class _EmbeddingCache:
    """Thread-safe disk cache for embedding vectors.

    Keys include an endpoint/model namespace so a model switch cannot silently
    reuse vectors generated with different semantics or dimensions.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict[str, list[float]] | None = None

    def _load(self) -> dict[str, list[float]]:
        if self._cache is not None:
            return self._cache
        path = _cache_path()
        if path.exists():
            try:
                self._cache = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._cache = {}
        else:
            self._cache = {}
        return self._cache

    def _save(self) -> None:
        path = _cache_path()
        path.write_text(json.dumps(self._cache), encoding="utf-8")

    @staticmethod
    def _key(text: str, namespace: str = "") -> str:
        value = f"{namespace}\0{text}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    def get(self, text: str, namespace: str = "") -> list[float] | None:
        with self._lock:
            cache = self._load()
            return cache.get(self._key(text, namespace))

    def get_many(
        self, texts: list[str], namespace: str = ""
    ) -> dict[int, list[float]]:
        """Return {index: vector} for texts that are in cache."""
        with self._lock:
            cache = self._load()
            result: dict[int, list[float]] = {}
            for i, text in enumerate(texts):
                k = self._key(text, namespace)
                if k in cache:
                    result[i] = cache[k]
            return result

    def put(self, text: str, vec: list[float], namespace: str = "") -> None:
        with self._lock:
            cache = self._load()
            cache[self._key(text, namespace)] = vec

    def put_many(
        self,
        texts: list[str],
        vectors: list[list[float]],
        namespace: str = "",
    ) -> None:
        with self._lock:
            cache = self._load()
            for text, vec in zip(texts, vectors):
                cache[self._key(text, namespace)] = vec
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._cache = {}
            self._save()


_cache = _EmbeddingCache()


# ─── API call ───────────────────────────────────────────────────

def _call_embeddings_api(
    texts: list[str], base_url: str, api_key: str, model: str
) -> list[list[float]]:
    """Call the OpenAI-compatible /embeddings endpoint."""
    url = base_url.rstrip("/") + "/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "input": texts}

    with httpx.Client(timeout=60) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    # OpenAI returns {"data": [{"embedding": [...], "index": 0}, ...]}
    sorted_data = sorted(data["data"], key=lambda x: x.get("index", 0))
    return [item["embedding"] for item in sorted_data]


# ─── Public API ─────────────────────────────────────────────────

def get_embeddings(
    texts: list[str],
    config: dict | None = None,
    *,
    force_refresh: bool = False,
) -> np.ndarray:
    """Return embeddings for *texts*.

    Parameters
    ----------
    texts : list[str]
        Texts to embed.
    config : dict, optional
        If provided, uses this config dict instead of loading from settings.
        Must contain ``embedding.base_url``, ``embedding.api_key``, ``embedding.model``
        (flat keys ``base_url``, ``api_key``, ``model`` also accepted).

    Returns
    -------
    np.ndarray of shape ``(len(texts), dim)``.
    Empty array of shape ``(0,)`` if embedding is unavailable.
    """
    if not texts:
        return np.array([])

    # Resolve config
    if config is None:
        emb_cfg = _get_embedding_config()
    else:
        emb_cfg = config

    base_url = emb_cfg.get("base_url")
    api_key = emb_cfg.get("api_key")
    model = emb_cfg.get("model")

    if not base_url or not api_key or not model:
        # Graceful degradation: return empty array
        return np.array([])

    # Credentials are deliberately excluded from the namespace. Endpoint and
    # model identify vector semantics without leaking a secret to disk.
    namespace = hashlib.sha256(
        f"{base_url}|{model}".encode("utf-8")
    ).hexdigest()[:16]

    # A dimension migration must bypass old vectors cached under the same
    # model name. Normal calls retain the existing no-cost cache behavior.
    cached = {} if force_refresh else _cache.get_many(texts, namespace)
    all_indices = set(range(len(texts)))
    missing_indices = sorted(all_indices - set(cached.keys()))

    # Fetch missing embeddings
    new_vectors: dict[int, list[float]] = {}
    if missing_indices:
        missing_texts = [texts[i] for i in missing_indices]
        batch_results: list[list[float]] = []
        for start in range(0, len(missing_texts), BATCH_SIZE):
            batch = missing_texts[start : start + BATCH_SIZE]
            batch_vecs = _call_embeddings_api(batch, base_url, api_key, model)
            batch_results.extend(batch_vecs)

        # Cache new results
        for idx_local, vec in zip(missing_indices, batch_results):
            new_vectors[idx_local] = vec
        _cache.put_many(missing_texts, batch_results, namespace)

    # Assemble final result
    all_vecs: list[list[float]] = []
    for i in range(len(texts)):
        if i in cached:
            all_vecs.append(cached[i])
        elif i in new_vectors:
            all_vecs.append(new_vectors[i])
        else:
            # This should not happen, but return zero vector as fallback
            dim = len(all_vecs[0]) if all_vecs else 0
            all_vecs.append([0.0] * dim if dim else [])

    return np.array(all_vecs, dtype=np.float32)


def clear_embedding_cache() -> None:
    """Clear the on-disk embedding cache."""
    _cache.clear()
