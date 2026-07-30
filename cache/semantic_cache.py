"""Semantic cache for namespace-scoped, near-duplicate requests."""

import logging
import math
import re
import time
from contextlib import nullcontext
from difflib import SequenceMatcher
from pathlib import Path

from ..config.settings import get_data_dir
from .json_store import atomic_write_json, load_json_index, path_lock


_logger = logging.getLogger(__name__)

_STOPWORDS = frozenset({
    "what", "is", "the", "a", "an", "in", "on", "at", "to", "for",
    "of", "and", "or", "it", "this", "that", "with", "from", "by",
    "how", "why", "when", "where", "can", "you", "please", "answer",
    "one", "sentence", "word", "just", "only", "give", "tell", "me",
    "explain", "define", "describe", "list", "show", "write", "create",
    "about", "do", "does", "did", "was", "were", "be", "been", "being",
    "have", "has", "had", "will", "would", "could", "should", "may",
    "use", "using", "used", "some", "any", "all", "each", "every",
    "i", "we", "they", "he", "she", "my", "your", "our", "their",
    "用", "中文", "回答", "请", "的", "是", "在", "了", "和", "有",
    "我", "你", "他", "她", "它", "们", "这", "那", "个", "一",
    "什么", "怎么", "如何", "为什么", "哪个", "哪些", "可以", "能",
})


def _is_finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_valid_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    if not isinstance(entry.get("query"), str):
        return False
    if not isinstance(entry.get("response"), str):
        return False
    if not isinstance(entry.get("namespace", ""), str):
        return False
    if not _is_finite_number(entry.get("created")):
        return False
    if not _is_finite_number(entry.get("ttl", 7200)) or entry.get("ttl", 7200) < 0:
        return False
    hits = entry.get("hits", 0)
    if not isinstance(hits, int) or isinstance(hits, bool) or hits < 0:
        return False
    if entry.get("tool_calls") is not None and not isinstance(entry["tool_calls"], list):
        return False
    if "last_hit" in entry and not _is_finite_number(entry["last_hit"]):
        return False
    return True


def _sanitize_index(payload: list) -> list:
    return [entry for entry in payload if _is_valid_entry(entry)]


def _extract_key_tokens(text: str) -> set:
    """Extract tokens that distinguish the subject of a query."""
    english_words = set(word.lower() for word in re.findall(r"[a-zA-Z]{3,}", text))
    chinese_segments = set(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    numbers = set(re.findall(r"\d+", text))
    quoted = set(re.findall(r"[\"'`][^\"'`]+[\"'`]", text))
    return (english_words | chinese_segments | numbers | quoted) - _STOPWORDS


class SemanticCache:
    """Second-level cache using similarity plus entity-overlap validation."""

    def __init__(self, cache_dir: Path | None = None):
        self._cache_dir = (
            Path(cache_dir) if cache_dir is not None else get_data_dir() / "cache"
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self._cache_dir / "semantic_index.json"
        self._index = self._load_index()
        self._similarity_threshold = 0.95

    def _load_index(self) -> list:
        if self._index_file is None:
            return self._index
        return load_json_index(
            self._index_file,
            list,
            list,
            sanitizer=_sanitize_index,
        )

    def _save_index(self) -> None:
        if self._index_file is None:
            return
        try:
            atomic_write_json(self._index_file, self._index)
        except (OSError, TypeError, ValueError) as exc:
            _logger.warning("Could not persist semantic cache index: %s", exc)

    def _operation_lock(self):
        if self._index_file is None:
            return nullcontext()
        return path_lock(self._index_file)

    def _refresh_index(self) -> None:
        if self._index_file is not None:
            self._index = self._load_index()

    def _normalize(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text.strip())
        return text.lower()

    def _similarity(self, first: str, second: str) -> float:
        return SequenceMatcher(
            None, self._normalize(first), self._normalize(second)
        ).ratio()

    def _entity_overlap(self, first: str, second: str) -> float:
        """Return the fraction of key tokens shared by two queries."""
        first_entities = _extract_key_tokens(first)
        second_entities = _extract_key_tokens(second)
        if not first_entities and not second_entities:
            return 1.0
        if not first_entities or not second_entities:
            return 0.0
        return len(first_entities & second_entities) / max(
            len(first_entities), len(second_entities)
        )

    def get(self, query: str, namespace: str = "") -> dict | None:
        """Get a non-expired near-duplicate result from the same namespace."""
        with self._operation_lock():
            self._refresh_index()
            if not self._index:
                return None

            now = time.time()
            active_entries = []
            expired_found = False
            for entry in self._index:
                ttl = entry.get("ttl", 7200)
                if now - entry.get("created", 0) > ttl:
                    expired_found = True
                    continue
                active_entries.append(entry)
            if expired_found:
                self._index = active_entries
                self._save_index()

            best_match = None
            best_score = 0.0
            for entry in active_entries:
                if entry.get("namespace", "") != namespace:
                    continue
                cached_query = entry.get("query", "")
                score = self._similarity(query, cached_query)
                if (
                    score > best_score
                    and self._entity_overlap(query, cached_query) >= 0.60
                ):
                    best_score = score
                    best_match = entry

            if not best_match or best_score < self._similarity_threshold:
                return None

            best_match["hits"] = best_match.get("hits", 0) + 1
            best_match["last_hit"] = time.time()
            self._save_index()
            return {
                "response": best_match.get("response", ""),
                "tool_calls": best_match.get("tool_calls"),
                "from_cache": True,
                "cache_type": "semantic",
                "similarity": best_score,
            }

    def put(
        self,
        query: str,
        response: str,
        tool_calls: list | None = None,
        ttl: int = 7200,
        namespace: str = "",
    ) -> None:
        """Store a response unless it looks erroneous or unhelpfully short."""
        response_lower = response.lower()
        error_indicators = [
            "no information", "not found", "cannot find", "no stored",
            "i don't know", "i cannot", "unable to", "failed", "error",
            "抱歉", "找不到", "无法", "不知道", "没有找到", "没有存储",
            "无法确定", "未能找到",
        ]
        if any(indicator in response_lower for indicator in error_indicators):
            return
        if len(response.strip()) < 10:
            return

        with self._operation_lock():
            self._refresh_index()
            self._index.append({
                "query": query,
                "namespace": namespace,
                "response": response,
                "tool_calls": tool_calls,
                "created": time.time(),
                "ttl": ttl,
                "hits": 0,
            })
            if len(self._index) > 500:
                self._index = sorted(
                    self._index,
                    key=lambda entry: entry.get("hits", 0),
                    reverse=True,
                )[:300]
            self._save_index()

    def get_stats(self) -> dict:
        """Get cache-entry statistics from the latest persisted index."""
        with self._operation_lock():
            self._refresh_index()
            total = len(self._index)
            total_hits = sum(entry.get("hits", 0) for entry in self._index)
            now = time.time()
            active = sum(
                1
                for entry in self._index
                if now - entry.get("created", 0) <= entry.get("ttl", 7200)
            )
            return {
                "total_entries": total,
                "total_hits": total_hits,
                "active_entries": active,
                "expired_entries": total - active,
            }

    def clear(self) -> None:
        """Clear all semantic cache entries."""
        with self._operation_lock():
            self._index.clear()
            self._save_index()

    def clean_expired(self) -> int:
        """Remove expired entries and return the number removed."""
        with self._operation_lock():
            self._refresh_index()
            now = time.time()
            before = len(self._index)
            self._index = [
                entry
                for entry in self._index
                if now - entry.get("created", 0) <= entry.get("ttl", 7200)
            ]
            removed = before - len(self._index)
            if removed:
                self._save_index()
            return removed


# Global singleton
semantic_cache = SemanticCache()
