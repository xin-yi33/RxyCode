"""Vector store – numpy brute-force cosine similarity.

Design pattern adapted from mentat's embeddings.py vector store:
- Protocol interface (add / search / delete_files)
- NumpyVectorStore: chunk metadata JSONL + vectors .npy
- mtime + hash incremental update

Only the design pattern is ported; implementation is original.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from ..config.settings import get_data_dir
from .chunker import CodeChunk, ScoredChunk


_MANIFEST_FIELDS = {
    "schema_version",
    "chunker_version",
    "embedding_mode",
    "embedding_model",
    "embedding_dimension",
}


# ─── Path helpers ───────────────────────────────────────────────

def _project_hash(root: Path | str) -> str:
    """Return a stable hash for a project root path."""
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]


def _index_dir(project_hash: str) -> Path:
    d = get_data_dir() / "rag_index" / project_hash
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─── Protocol ───────────────────────────────────────────────────

@runtime_checkable
class VectorStore(Protocol):
    """Protocol for vector store implementations."""

    def add(self, chunks: list[CodeChunk], vectors: np.ndarray) -> None:
        """Add chunks and their embedding vectors to the store."""
        ...

    def search(self, query_vec: np.ndarray, top_k: int = 8) -> list[ScoredChunk]:
        """Search for the top-k most similar chunks."""
        ...

    def delete_files(self, paths: list[str]) -> None:
        """Remove all chunks for the given file paths."""
        ...

    def get_indexed_files(self) -> dict[str, dict]:
        """Return {path: {mtime, hash}} for all indexed files."""
        ...


# ─── NumpyVectorStore ───────────────────────────────────────────

class NumpyVectorStore:
    """Vector store backed by numpy arrays + JSONL metadata.

    Persistence layout::

        ~/.rxycode/rag_index/<project_hash>/
            meta.jsonl     – one CodeChunk dict per line
            vectors.npy    – (N, dim) float32 numpy array
            file_index.json – {path: {mtime, hash}} for incremental updates
            manifest.json  – index/chunker/embedding compatibility contract
    """

    def __init__(self, project_root: Path | str):
        self.project_root = str(project_root)
        self._phash = _project_hash(project_root)
        self._dir = _index_dir(self._phash)
        self._meta_path = self._dir / "meta.jsonl"
        self._vec_path = self._dir / "vectors.npy"
        self._file_index_path = self._dir / "file_index.json"
        self._manifest_path = self._dir / "manifest.json"
        self._lock = threading.Lock()

        # In-memory state
        self._chunks: list[CodeChunk] = []
        self._vectors: np.ndarray = np.array([], dtype=np.float32)
        self._file_index: dict[str, dict] = {}  # path -> {mtime, hash}
        self._manifest: dict | None = None

        self._load()

    # ─── Persistence ────────────────────────────────────────────

    def _load(self) -> None:
        """Load existing index from disk."""
        if self._meta_path.exists():
            try:
                lines = self._meta_path.read_text(encoding="utf-8").strip().splitlines()
                self._chunks = [CodeChunk.from_dict(json.loads(line)) for line in lines if line.strip()]
            except (json.JSONDecodeError, KeyError, OSError):
                self._chunks = []

        if self._vec_path.exists():
            try:
                self._vectors = np.load(self._vec_path)
            except (ValueError, OSError):
                self._vectors = np.array([], dtype=np.float32)

        if self._file_index_path.exists():
            try:
                self._file_index = json.loads(self._file_index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._file_index = {}

        if self._manifest_path.exists():
            try:
                raw_manifest = json.loads(
                    self._manifest_path.read_text(encoding="utf-8")
                )
                if isinstance(raw_manifest, dict):
                    self._manifest = {
                        key: raw_manifest[key]
                        for key in _MANIFEST_FIELDS
                        if key in raw_manifest
                    }
            except (json.JSONDecodeError, OSError):
                self._manifest = None

        # Ensure vectors shape is consistent
        if len(self._chunks) == 0:
            self._vectors = np.array([], dtype=np.float32)
        elif self._vectors.ndim == 1 or len(self._vectors) != len(self._chunks):
            # A partial/corrupt index cannot safely participate in incremental
            # updates because unchanged files would never regain vectors.
            self._clear_in_memory()
        elif self._manifest is not None:
            dimension = self._manifest.get("embedding_dimension")
            if (
                isinstance(dimension, int)
                and dimension > 0
                and self._vectors.shape[1] != dimension
            ):
                self._clear_in_memory()

    def _clear_in_memory(self) -> None:
        self._chunks = []
        self._vectors = np.array([], dtype=np.float32)
        self._file_index = {}

    def _save(self) -> None:
        """Persist index to disk."""
        # Save metadata as JSONL
        lines = [json.dumps(c.to_dict(), ensure_ascii=False) for c in self._chunks]
        self._meta_path.write_text("\n".join(lines), encoding="utf-8")

        # Save vectors
        if len(self._vectors) > 0:
            np.save(self._vec_path, self._vectors)
        else:
            # Write empty array
            np.save(self._vec_path, np.array([], dtype=np.float32))

        # Save file index
        self._file_index_path.write_text(
            json.dumps(self._file_index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if self._manifest is None:
            if self._manifest_path.exists():
                self._manifest_path.unlink()
        else:
            self._manifest_path.write_text(
                json.dumps(self._manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def get_manifest(self) -> dict | None:
        """Return a copy of the persisted index compatibility manifest."""
        with self._lock:
            return dict(self._manifest) if self._manifest is not None else None

    def set_manifest(self, manifest: dict) -> None:
        """Persist only the non-secret compatibility fields."""
        sanitized = {
            key: manifest[key]
            for key in _MANIFEST_FIELDS
            if key in manifest
        }
        with self._lock:
            self._manifest = sanitized
            self._save()

    def reset(self, manifest: dict | None = None) -> None:
        """Discard all chunks/vectors before an incompatible full rebuild."""
        sanitized = None
        if manifest is not None:
            sanitized = {
                key: manifest[key]
                for key in _MANIFEST_FIELDS
                if key in manifest
            }
        with self._lock:
            self._clear_in_memory()
            self._manifest = sanitized
            self._save()

    # ─── Incremental update helpers ─────────────────────────────

    def needs_reindex(self, path: str, mtime: float, file_hash: str) -> bool:
        """Return True if a file needs re-indexing (mtime or hash changed)."""
        info = self._file_index.get(path)
        if info is None:
            return True
        if abs(info.get("mtime", 0) - mtime) > 0.001:
            return True
        if info.get("hash") != file_hash:
            return True
        return False

    def _compute_file_hash(self, chunks: list[CodeChunk]) -> str:
        """Compute a combined hash for all chunks of a file."""
        combined = "|".join(c.hash for c in chunks)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]

    # ─── Protocol implementation ────────────────────────────────

    def add(self, chunks: list[CodeChunk], vectors: np.ndarray) -> None:
        """Add (or replace) chunks for a set of files.

        If chunks for the same path already exist, they are replaced.
        """
        with self._lock:
            if not chunks:
                return
            if len(vectors) > 0:
                if vectors.ndim != 2 or len(vectors) != len(chunks):
                    raise ValueError(
                        "vectors must be a 2D array with one row per chunk"
                    )
                if (
                    len(self._vectors) > 0
                    and self._vectors.ndim == 2
                    and self._vectors.shape[1] != vectors.shape[1]
                ):
                    raise ValueError(
                        "embedding dimension changed; reset the index before adding"
                    )

            # Group new chunks by file path
            new_by_path: dict[str, list[CodeChunk]] = {}
            for c in chunks:
                new_by_path.setdefault(c.path, []).append(c)

            # Remove existing chunks for those paths
            paths_to_replace = set(new_by_path.keys())
            keep_indices = [
                i for i, c in enumerate(self._chunks)
                if c.path not in paths_to_replace
            ]

            self._chunks = [self._chunks[i] for i in keep_indices]
            if len(self._vectors) > 0 and len(keep_indices) > 0:
                self._vectors = self._vectors[keep_indices]
            elif len(keep_indices) == 0:
                self._vectors = np.array([], dtype=np.float32)

            # Append new chunks
            new_chunks_flat: list[CodeChunk] = []
            for path, file_chunks in new_by_path.items():
                new_chunks_flat.extend(file_chunks)
                # Update file index
                file_hash = self._compute_file_hash(file_chunks)
                mtime = file_chunks[0].mtime if file_chunks else 0.0
                self._file_index[path] = {"mtime": mtime, "hash": file_hash}

            self._chunks.extend(new_chunks_flat)

            # Append new vectors
            if len(vectors) > 0:
                if len(self._vectors) == 0:
                    self._vectors = vectors.astype(np.float32)
                else:
                    self._vectors = np.vstack(
                        [self._vectors, vectors.astype(np.float32)]
                    )

            self._save()

    def search(self, query_vec: np.ndarray, top_k: int = 8) -> list[ScoredChunk]:
        """Brute-force cosine similarity search."""
        with self._lock:
            if len(self._chunks) == 0 or len(self._vectors) == 0:
                return []
            if query_vec.ndim == 1:
                query_vec = query_vec.reshape(1, -1)

            # Ensure shapes match
            if self._vectors.ndim == 1:
                self._vectors = self._vectors.reshape(1, -1)

            # Normalize for cosine similarity
            vecs = self._vectors.astype(np.float32)
            query = query_vec.astype(np.float32).reshape(-1)

            vec_norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            vec_norms[vec_norms == 0] = 1.0
            vecs_normed = vecs / vec_norms

            query_norm = np.linalg.norm(query)
            if query_norm > 0:
                query_normed = query / query_norm
            else:
                query_normed = query

            scores = vecs_normed @ query_normed

            k = min(top_k, len(self._chunks))
            # Get top-k indices (descending)
            if k < len(scores):
                top_idx = np.argpartition(-scores, k)[:k]
            else:
                top_idx = np.arange(len(scores))
            top_idx = top_idx[np.argsort(-scores[top_idx])]

            results: list[ScoredChunk] = []
            for idx in top_idx:
                results.append(ScoredChunk(
                    chunk=self._chunks[idx],
                    score=float(scores[idx]),
                ))
            return results

    def delete_files(self, paths: list[str]) -> None:
        """Remove all chunks for the given file paths."""
        with self._lock:
            path_set = set(paths)
            keep_indices = [
                i for i, c in enumerate(self._chunks)
                if c.path not in path_set
            ]
            self._chunks = [self._chunks[i] for i in keep_indices]
            if len(self._vectors) > 0:
                if len(keep_indices) > 0:
                    self._vectors = self._vectors[keep_indices]
                else:
                    self._vectors = np.array([], dtype=np.float32)
            for p in paths:
                self._file_index.pop(p, None)
            self._save()

    def get_indexed_files(self) -> dict[str, dict]:
        """Return {path: {mtime, hash}} for all indexed files."""
        return dict(self._file_index)

    @property
    def size(self) -> int:
        """Number of indexed chunks."""
        return len(self._chunks)

    @property
    def vector_dimension(self) -> int | None:
        """Stored vector width, or None for an empty/corrupt index."""
        if self._vectors.ndim == 2 and self._vectors.shape[0] > 0:
            return int(self._vectors.shape[1])
        return None
