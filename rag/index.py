"""CLI entry point and background indexer for the RAG package.

Usage::

    python -m rag.index <path>

Design:
- ``index_project(root)`` chunks and indexes a directory
- ``start_background_indexer(root)`` launches a daemon thread
- CLI entry point via ``python -m rag.index``
"""
from __future__ import annotations

import atexit
import logging
import math
import sys
import threading
import time
from pathlib import Path

import numpy as np

from ..config.settings import load_config
from .chunker import CHUNKER_VERSION, CodeChunk, chunk_directory
from .embed import (
    clear_embedding_cache,
    get_embedding_config,
    get_embeddings,
    is_embedding_available,
)
from .store import NumpyVectorStore


_logger = logging.getLogger(__name__)


INDEX_SCHEMA_VERSION = 1
PSEUDO_VECTOR_DIMENSION = 64
PSEUDO_EMBEDDING_MODEL = "pseudo-sha256-v1"
_MANIFEST_IDENTITY_FIELDS = (
    "schema_version",
    "chunker_version",
    "embedding_mode",
    "embedding_model",
)


# ─── Project root detection ─────────────────────────────────────

_cwd_store: NumpyVectorStore | None = None
_cwd_root: Path | None = None
_cwd_lock = threading.RLock()


def _get_project_root() -> Path | None:
    """Detect the project root (look for .git or pyproject.toml)."""
    global _cwd_root
    with _cwd_lock:
        if _cwd_root is not None:
            return _cwd_root

    cwd = Path.cwd()
    # Walk up to find .git or pyproject.toml
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            with _cwd_lock:
                _cwd_root = parent.resolve()
                return _cwd_root

    # Default to cwd
    with _cwd_lock:
        _cwd_root = cwd.resolve()
        return _cwd_root


def _get_store_for_cwd() -> NumpyVectorStore | None:
    """Get (or create) a vector store for the current project."""
    global _cwd_store
    with _cwd_lock:
        if _cwd_store is not None:
            return _cwd_store

    root = _get_project_root()
    if root is None:
        return None
    with _cwd_lock:
        if _cwd_store is None:
            _cwd_store = NumpyVectorStore(root)
        return _cwd_store


# ─── Indexing ───────────────────────────────────────────────────

def _configured_dimension(config: dict) -> int | None:
    value = config.get("dimension", config.get("dimensions"))
    if value in (None, ""):
        return None
    try:
        dimension = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("embedding dimension must be a positive integer") from exc
    if dimension <= 0:
        raise ValueError("embedding dimension must be a positive integer")
    return dimension


def _desired_manifest(use_embeddings: bool, config: dict) -> dict:
    if use_embeddings:
        return {
            "schema_version": INDEX_SCHEMA_VERSION,
            "chunker_version": CHUNKER_VERSION,
            "embedding_mode": "real",
            "embedding_model": str(config.get("model") or ""),
            "embedding_dimension": _configured_dimension(config),
        }
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "embedding_mode": "pseudo",
        "embedding_model": PSEUDO_EMBEDDING_MODEL,
        "embedding_dimension": PSEUDO_VECTOR_DIMENSION,
    }


def _manifest_requires_rebuild(
    store: NumpyVectorStore,
    current: dict | None,
    desired: dict,
) -> bool:
    if current is None:
        return True
    if any(current.get(key) != desired.get(key) for key in _MANIFEST_IDENTITY_FIELDS):
        return True

    requested_dimension = desired.get("embedding_dimension")
    current_dimension = current.get("embedding_dimension")
    if requested_dimension is not None and current_dimension != requested_dimension:
        return True
    if store.size > 0:
        if not isinstance(current_dimension, int) or current_dimension <= 0:
            return True
        if store.vector_dimension != current_dimension:
            return True
    return False


def _validate_vectors(vectors: np.ndarray, expected_rows: int) -> int:
    if vectors.ndim != 2 or vectors.shape[0] != expected_rows or vectors.shape[1] <= 0:
        raise ValueError("embedding provider returned an invalid vector matrix")
    return int(vectors.shape[1])


def _embed_chunks(
    chunks: list[CodeChunk],
    *,
    use_embeddings: bool,
    embedding_config: dict,
    force_refresh: bool = False,
) -> np.ndarray:
    if use_embeddings:
        return get_embeddings(
            [chunk.content for chunk in chunks],
            config=embedding_config,
            force_refresh=force_refresh,
        )
    return np.array(
        [
            _pseudo_vector(chunk.hash, PSEUDO_VECTOR_DIMENSION)
            for chunk in chunks
        ],
        dtype=np.float32,
    )


def index_project(root: Path, store: NumpyVectorStore | None = None) -> int:
    """Index all source files under *root*.

    Performs incremental update: only re-chunks files whose mtime or hash
    has changed since the last index.

    Returns the number of chunks indexed.
    """
    root = Path(root)
    if not root.is_dir():
        return 0

    if store is None:
        store = NumpyVectorStore(root)

    use_embeddings = is_embedding_available()
    embedding_config = get_embedding_config() if use_embeddings else {}
    desired_manifest = _desired_manifest(use_embeddings, embedding_config)
    current_manifest = store.get_manifest()
    if _manifest_requires_rebuild(store, current_manifest, desired_manifest):
        store.reset(desired_manifest)
        current_manifest = desired_manifest
    elif desired_manifest["embedding_dimension"] is None:
        # Preserve the actual dimension discovered during the first build.
        desired_manifest["embedding_dimension"] = current_manifest.get(
            "embedding_dimension"
        )

    # Get existing file index
    indexed_files = store.get_indexed_files()

    # Chunk all files
    all_chunks = chunk_directory(root)

    # Group chunks by file for incremental check
    chunks_by_path: dict[str, list[CodeChunk]] = {}
    for c in all_chunks:
        chunks_by_path.setdefault(c.path, []).append(c)

    # Determine which files need re-indexing
    files_to_index: list[str] = []
    chunks_to_embed: list[CodeChunk] = []

    for fpath, file_chunks in chunks_by_path.items():
        if len(file_chunks) == 0:
            continue
        # Compute combined hash for the file
        combined_hash = "|".join(c.hash for c in file_chunks)
        file_hash = __import__("hashlib").sha256(combined_hash.encode()).hexdigest()[:16]
        mtime = file_chunks[0].mtime

        if store.needs_reindex(fpath, mtime, file_hash):
            files_to_index.append(fpath)
            chunks_to_embed.extend(file_chunks)

    # Also handle deleted files
    deleted_files = set(indexed_files.keys()) - set(chunks_by_path.keys())
    if deleted_files:
        store.delete_files(list(deleted_files))

    if not chunks_to_embed:
        # Nothing to index
        if store.get_manifest() != desired_manifest:
            store.set_manifest(desired_manifest)
        return store.size

    vectors = _embed_chunks(
        chunks_to_embed,
        use_embeddings=use_embeddings,
        embedding_config=embedding_config,
    )
    actual_dimension = _validate_vectors(vectors, len(chunks_to_embed))
    requested_dimension = _configured_dimension(embedding_config) if use_embeddings else None
    if requested_dimension is not None and actual_dimension != requested_dimension:
        raise ValueError(
            "embedding provider dimension does not match configured dimension "
            f"({actual_dimension} != {requested_dimension})"
        )

    known_dimension = desired_manifest.get("embedding_dimension")
    if known_dimension is not None and actual_dimension != known_dimension:
        # Same model name, different returned dimension. The partial vectors are
        # unusable; clear both the index and cached vectors and rebuild all files.
        clear_embedding_cache()
        chunks_to_embed = all_chunks
        vectors = _embed_chunks(
            chunks_to_embed,
            use_embeddings=use_embeddings,
            embedding_config=embedding_config,
            force_refresh=True,
        )
        actual_dimension = _validate_vectors(vectors, len(chunks_to_embed))
        if requested_dimension is not None and actual_dimension != requested_dimension:
            raise ValueError(
                "embedding provider dimension changed during full rebuild"
            )
        desired_manifest["embedding_dimension"] = actual_dimension
        store.reset(desired_manifest)
    else:
        desired_manifest["embedding_dimension"] = actual_dimension
        store.set_manifest(desired_manifest)

    # Add to store
    store.add(chunks_to_embed, vectors)

    return len(chunks_to_embed)


def _pseudo_vector(hash_str: str, dim: int) -> list[float]:
    """Generate a deterministic pseudo-vector from a hash string.

    Used as a fallback when real embeddings are unavailable.
    """
    import hashlib
    # Expand hash to enough bytes for the vector dimension
    expanded = (hash_str * (dim // len(hash_str) + 1))[:dim * 2]
    h = hashlib.sha256(expanded.encode()).digest()
    vec = []
    for i in range(dim):
        byte_val = h[i % len(h)]
        vec.append((byte_val / 255.0) * 2 - 1)  # normalize to [-1, 1]
    return vec


# ─── Background indexer ─────────────────────────────────────────

def _rag_enabled(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _bounded_delay(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if not math.isfinite(parsed):
        parsed = default
    return max(0.0, min(parsed, 60.0))


def _reload_cwd_store(root: Path) -> None:
    """Make the code_search singleton observe a newly persisted index."""
    global _cwd_store
    resolved = root.resolve()
    with _cwd_lock:
        if _cwd_root is not None and _cwd_root.resolve() == resolved:
            _cwd_store = NumpyVectorStore(resolved)


class BackgroundIndexer:
    """One resilient, debounced indexing worker for a project root."""

    def __init__(self, root: Path, *, debounce_seconds: float = 0.25) -> None:
        self.root = Path(root).resolve()
        self.debounce_seconds = _bounded_delay(debounce_seconds, 0.25)
        self._condition = threading.Condition(threading.RLock())
        self._thread: threading.Thread | None = None
        self._stopped = False
        self._pending = False
        self._running = False
        self._due_at = 0.0
        self._requested_generation = 0
        self._completed_generation = 0
        self._last_success_generation = 0
        self._runs_succeeded = 0
        self._runs_failed = 0
        self._last_error_type: str | None = None
        self._last_duration_seconds: float | None = None
        self._last_chunk_count: int | None = None

    def start(self, *, initial_delay: float = 0.0) -> "BackgroundIndexer":
        """Start the sole worker thread and schedule the initial index."""
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return self
            if self._stopped:
                raise RuntimeError("background indexer has been stopped")
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name=f"rag-indexer-{abs(hash(str(self.root))) & 0xFFFF:04x}",
            )
            self._thread.start()
        self.request_refresh(delay=initial_delay)
        return self

    def request_refresh(self, *, delay: float | None = None) -> int | None:
        """Debounce a refresh request and return its monotonic generation."""
        with self._condition:
            if self._stopped:
                return None
            self._requested_generation += 1
            generation = self._requested_generation
            effective_delay = (
                self.debounce_seconds
                if delay is None
                else _bounded_delay(delay, self.debounce_seconds)
            )
            self._due_at = time.monotonic() + effective_delay
            self._pending = True
            self._condition.notify_all()
            return generation

    def stop(self, timeout: float = 2.0) -> bool:
        """Stop the worker and wait up to *timeout* seconds for termination."""
        with self._condition:
            self._stopped = True
            self._pending = False
            thread = self._thread
            self._condition.notify_all()
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, timeout))
        return thread is None or not thread.is_alive()

    def is_alive(self) -> bool:
        """Match ``threading.Thread.is_alive`` for compatibility."""
        with self._condition:
            return self._thread is not None and self._thread.is_alive()

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        """Wait until no refresh is queued or running."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while (self._pending or self._running) and not self._stopped:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return not self._pending and not self._running

    def status(self) -> dict[str, object]:
        """Return content-free worker health and freshness generations."""
        with self._condition:
            alive = self._thread is not None and self._thread.is_alive()
            if self._stopped:
                state = "stopped"
            elif self._running:
                state = "indexing"
            elif self._pending:
                state = "scheduled"
            elif alive:
                state = "idle"
            else:
                state = "not_started"
            return {
                "state": state,
                "worker_alive": alive,
                "pending": self._pending,
                "running": self._running,
                "requested_generation": self._requested_generation,
                "completed_generation": self._completed_generation,
                "last_success_generation": self._last_success_generation,
                "runs_succeeded": self._runs_succeeded,
                "runs_failed": self._runs_failed,
                "last_error_type": self._last_error_type,
                "last_duration_seconds": self._last_duration_seconds,
                "last_chunk_count": self._last_chunk_count,
            }

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._stopped and not self._pending:
                    self._condition.wait()
                if self._stopped:
                    return
                remaining = self._due_at - time.monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                generation = self._requested_generation
                self._pending = False
                self._running = True

            started = time.monotonic()
            try:
                chunk_count = index_project(self.root)
                _reload_cwd_store(self.root)
            except Exception as exc:
                with self._condition:
                    self._runs_failed += 1
                    self._last_error_type = type(exc).__name__
                _logger.warning(
                    "background RAG index refresh failed: %s", type(exc).__name__
                )
            else:
                with self._condition:
                    self._runs_succeeded += 1
                    self._last_success_generation = generation
                    self._last_error_type = None
                    self._last_chunk_count = int(chunk_count)
            finally:
                with self._condition:
                    self._completed_generation = max(
                        self._completed_generation, generation
                    )
                    self._last_duration_seconds = round(
                        time.monotonic() - started, 6
                    )
                    self._running = False
                    self._condition.notify_all()


_background_indexers: dict[str, BackgroundIndexer] = {}
_background_indexers_lock = threading.RLock()


def start_background_indexer(
    root: Path | None = None,
    delay: float = 2.0,
) -> BackgroundIndexer | None:
    """Return the single resilient background indexer for *root*."""
    cfg = load_config()
    raw_rag_cfg = cfg.get("rag", {})
    rag_cfg = raw_rag_cfg if isinstance(raw_rag_cfg, dict) else {}
    if not _rag_enabled(rag_cfg.get("enabled", False)):
        return None

    detected_root = root if root is not None else _get_project_root()
    if detected_root is None:
        return None
    resolved_root = Path(detected_root).resolve()
    if not resolved_root.is_dir():
        return None
    key = str(resolved_root).casefold()
    with _background_indexers_lock:
        existing = _background_indexers.get(key)
        if existing is not None and existing.is_alive():
            return existing
        debounce = _bounded_delay(
            rag_cfg.get("refresh_debounce_seconds", 0.25), 0.25
        )
        indexer = BackgroundIndexer(
            resolved_root,
            debounce_seconds=debounce,
        )
        _background_indexers[key] = indexer
        indexer.start(initial_delay=_bounded_delay(delay, 2.0))
        return indexer


def stop_background_indexer(root: Path | None = None, timeout: float = 2.0) -> int:
    """Stop one project worker, or every worker when *root* is omitted."""
    with _background_indexers_lock:
        if root is None:
            selected = list(_background_indexers.items())
            _background_indexers.clear()
        else:
            key = str(Path(root).resolve()).casefold()
            indexer = _background_indexers.pop(key, None)
            selected = [(key, indexer)] if indexer is not None else []
    for _key, indexer in selected:
        indexer.stop(timeout=timeout)
    return len(selected)


atexit.register(stop_background_indexer)


# ─── CLI ────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point: ``python -m rag.index <path>``"""
    if len(sys.argv) < 2:
        print("Usage: python -m rag.index <path>")
        print("  Indexes the codebase at <path> for vector search.")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: path not found: {path}")
        sys.exit(1)

    if not path.is_dir():
        print(f"Error: not a directory: {path}")
        sys.exit(1)

    print(f"Indexing {path} ...")
    count = index_project(path)
    print(f"Done. Indexed {count} chunks.")


if __name__ == "__main__":
    main()
