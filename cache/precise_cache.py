"""Precise cache - byte-exact hash matching for identical requests."""

import hashlib
import logging
import math
import time
from contextlib import nullcontext
from pathlib import Path

from ..config.settings import get_data_dir
from .json_store import atomic_write_json, load_json_index, path_lock


_logger = logging.getLogger(__name__)


def _is_finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_valid_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    if not isinstance(entry.get("response"), str):
        return False
    if not _is_finite_number(entry.get("created")):
        return False
    if not _is_finite_number(entry.get("ttl", 3600)) or entry.get("ttl", 3600) < 0:
        return False
    hits = entry.get("hits", 0)
    if not isinstance(hits, int) or isinstance(hits, bool) or hits < 0:
        return False
    if entry.get("tool_calls") is not None and not isinstance(entry["tool_calls"], list):
        return False
    if "last_hit" in entry and not _is_finite_number(entry["last_hit"]):
        return False
    if "query_preview" in entry and not isinstance(entry["query_preview"], str):
        return False
    return True


def _sanitize_index(payload: dict) -> dict:
    return {
        key: entry
        for key, entry in payload.items()
        if isinstance(key, str) and _is_valid_entry(entry)
    }


class PreciseCache:
    """First-level cache: byte-exact hash matching."""

    def __init__(self, cache_dir: Path | None = None):
        self._cache_dir = (
            Path(cache_dir) if cache_dir is not None else get_data_dir() / "cache"
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self._cache_dir / "precise_index.json"
        self._index = self._load_index()

    def _load_index(self) -> dict:
        if self._index_file is None:
            return self._index
        return load_json_index(
            self._index_file,
            dict,
            dict,
            sanitizer=_sanitize_index,
        )

    def _save_index(self) -> None:
        if self._index_file is None:
            return
        try:
            atomic_write_json(self._index_file, self._index)
        except (OSError, TypeError, ValueError) as exc:
            _logger.warning("Could not persist precise cache index: %s", exc)

    def _operation_lock(self):
        if self._index_file is None:
            return nullcontext()
        return path_lock(self._index_file)

    def _refresh_index(self) -> None:
        if self._index_file is not None:
            self._index = self._load_index()

    @staticmethod
    def _hash_parts(*parts: str) -> str:
        """Hash length-prefixed UTF-8 values without normalizing their bytes."""
        digest = hashlib.sha256()
        for part in parts:
            encoded = part.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    def _make_key(
        self,
        system_prompt: str,
        query: str,
        tool_name: str = "",
        tool_args: str = "",
        prompt_version: str = "",
        namespace: str = "",
    ) -> str:
        """Generate a stable key from exact, independently framed components."""
        system_hash = self._hash_parts(namespace, system_prompt)
        query_hash = self._hash_parts(query)
        tool_hash = (
            self._hash_parts(tool_name, tool_args)
            if tool_name or tool_args
            else ""
        )
        version_hash = self._hash_parts(prompt_version) if prompt_version else ""
        return f"{system_hash}:{query_hash}:{tool_hash}:{version_hash}"

    def get(
        self,
        system_prompt: str,
        query: str,
        tool_name: str = "",
        tool_args: str = "",
        prompt_version: str = "",
        namespace: str = "",
    ) -> dict | None:
        """Get a cached result only when every key component matches exactly."""
        key = self._make_key(
            system_prompt, query, tool_name, tool_args, prompt_version, namespace
        )
        with self._operation_lock():
            self._refresh_index()
            entry = self._index.get(key)
            if not entry:
                return None

            ttl = entry.get("ttl", 3600)
            if time.time() - entry.get("created", 0) > ttl:
                del self._index[key]
                self._save_index()
                return None

            entry["hits"] = entry.get("hits", 0) + 1
            entry["last_hit"] = time.time()
            self._save_index()
            return {
                "response": entry.get("response", ""),
                "tool_calls": entry.get("tool_calls"),
                "from_cache": True,
                "cache_type": "precise",
            }

    def put(
        self,
        system_prompt: str,
        query: str,
        response: str,
        tool_name: str = "",
        tool_args: str = "",
        tool_calls: list | None = None,
        ttl: int = 7200,
        prompt_version: str = "",
        namespace: str = "",
    ) -> None:
        """Store a result in the precise cache."""
        key = self._make_key(
            system_prompt, query, tool_name, tool_args, prompt_version, namespace
        )
        with self._operation_lock():
            self._refresh_index()
            self._index[key] = {
                "response": response,
                "tool_calls": tool_calls,
                "created": time.time(),
                "ttl": ttl,
                "hits": 0,
                "query_preview": query[:50],
            }
            self._save_index()

    def get_stats(self) -> dict:
        """Get cache-entry statistics from the latest persisted index."""
        with self._operation_lock():
            self._refresh_index()
            total = len(self._index)
            total_hits = sum(e.get("hits", 0) for e in self._index.values())
            expired = sum(
                1
                for entry in self._index.values()
                if time.time() - entry.get("created", 0)
                > entry.get("ttl", 3600)
            )
            return {
                "total_entries": total,
                "total_hits": total_hits,
                "expired_entries": expired,
                "active_entries": total - expired,
            }

    def clean_expired(self) -> int:
        """Remove expired entries and return the number removed."""
        with self._operation_lock():
            self._refresh_index()
            now = time.time()
            expired_keys = [
                key
                for key, entry in self._index.items()
                if now - entry.get("created", 0) > entry.get("ttl", 3600)
            ]
            for key in expired_keys:
                del self._index[key]
            if expired_keys:
                self._save_index()
            return len(expired_keys)

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._operation_lock():
            self._index.clear()
            self._save_index()


# Global singleton
precise_cache = PreciseCache()
