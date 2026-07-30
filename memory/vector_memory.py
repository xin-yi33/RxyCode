"""Bounded, persistent local vector memory for verified agent experience.

The store deliberately uses stable feature hashing instead of a remote
embedding service. This keeps retrieval deterministic, offline, and free while
still performing real cosine similarity over normalized vectors.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from RxyCode.RxyCode1_1_0.config.settings import get_data_dir
from RxyCode.RxyCode1_1_0.utils.atomic_file import atomic_write_text


_STORE_LOCK = threading.RLock()
_WORD_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:sk|key|token)-[a-z0-9._-]{6,}"),
    re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)"
        r"\s*[:=]\s*[\"']?[^\s,;\"']+"
    ),
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
)


@dataclass(frozen=True)
class ExperienceMatch:
    """One persisted experience plus its query-time cosine score."""

    text: str
    kind: str
    outcome: str
    project: str
    session: str
    timestamp: str
    score: float


def _redact(text: str) -> str:
    result = str(text)
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _WORD_RE.findall(text.casefold()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", raw):
            tokens.extend(raw)
            tokens.extend(raw[index:index + 2] for index in range(len(raw) - 1))
        else:
            tokens.append(raw)
    return tokens


def feature_hash_vector(text: str, dimension: int = 256) -> list[float]:
    """Return a stable, L2-normalized hashing vector for *text*."""
    dimension = max(32, min(int(dimension), 4096))
    vector = [0.0] * dimension
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") % dimension
        sign = -1.0 if digest[8] & 1 else 1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


class ExperienceVectorMemory:
    """JSONL-backed experience store with bounded cosine retrieval."""

    SCHEMA_VERSION = 1
    DEFAULT_DIMENSION = 256
    DEFAULT_MAX_ENTRIES = 2000
    MAX_TOP_K = 20
    MAX_TEXT_CHARS = 12_000

    def __init__(
        self,
        *,
        project: str,
        dimension: int = DEFAULT_DIMENSION,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        path: str | Path | None = None,
    ) -> None:
        self.project = str(project)
        self.dimension = max(32, min(int(dimension), 4096))
        self.max_entries = max(1, min(int(max_entries), 20_000))
        self.path = Path(path) if path else (
            get_data_dir() / "memory" / "experiences" / "vectors.jsonl"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load_records(self) -> list[dict]:
        if not self.path.exists():
            return []
        records: list[dict] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            vector = record.get("vector")
            if (
                record.get("schema_version") != self.SCHEMA_VERSION
                or record.get("dimension") != self.dimension
                or not isinstance(vector, list)
                or len(vector) != self.dimension
            ):
                continue
            records.append(record)
        return records

    def _save_records(self, records: list[dict]) -> None:
        content = "\n".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            for record in records[-self.max_entries:]
        )
        if content:
            content += "\n"
        atomic_write_text(self.path, content)

    def add(
        self,
        text: str,
        *,
        kind: str,
        outcome: str,
        session: str,
        timestamp: str | None = None,
    ) -> bool:
        """Persist one experience; return False for empty or duplicate text."""
        clean_text = _redact(str(text)).strip()[:self.MAX_TEXT_CHARS]
        if not clean_text:
            return False
        kind = str(kind).strip()[:64] or "experience"
        outcome = str(outcome).strip()[:64] or "unknown"
        session = str(session).strip()[:256]
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        fingerprint_source = "\0".join(
            (self.project, session, kind, outcome, clean_text)
        )
        record_id = hashlib.sha256(
            fingerprint_source.encode("utf-8")
        ).hexdigest()
        record = {
            "schema_version": self.SCHEMA_VERSION,
            "id": record_id,
            "text": clean_text,
            "kind": kind,
            "outcome": outcome,
            "project": self.project,
            "session": session,
            "timestamp": timestamp,
            "dimension": self.dimension,
            "vector": feature_hash_vector(clean_text, self.dimension),
        }
        with _STORE_LOCK:
            records = self._load_records()
            if any(item.get("id") == record_id for item in records):
                return False
            records.append(record)
            self._save_records(records)
        return True

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        kind: str | None = None,
        outcome: str | None = None,
        session: str | None = None,
        min_score: float = -1.0,
    ) -> list[ExperienceMatch]:
        """Search this project using cosine similarity and metadata filters."""
        query = str(query).strip()
        if not query:
            return []
        bounded_k = max(1, min(int(top_k), self.MAX_TOP_K))
        query_vector = feature_hash_vector(query, self.dimension)
        if not any(query_vector):
            return []
        with _STORE_LOCK:
            records = self._load_records()
        matches: list[ExperienceMatch] = []
        for record in records:
            if record.get("project") != self.project:
                continue
            if kind is not None and record.get("kind") != kind:
                continue
            if outcome is not None and record.get("outcome") != outcome:
                continue
            if session is not None and record.get("session") != session:
                continue
            vector = record["vector"]
            score = float(sum(a * b for a, b in zip(query_vector, vector)))
            if score < min_score:
                continue
            matches.append(ExperienceMatch(
                text=str(record.get("text", "")),
                kind=str(record.get("kind", "")),
                outcome=str(record.get("outcome", "")),
                project=str(record.get("project", "")),
                session=str(record.get("session", "")),
                timestamp=str(record.get("timestamp", "")),
                score=score,
            ))
        matches.sort(key=lambda item: (item.score, item.timestamp), reverse=True)
        return matches[:bounded_k]

    def retrieve_context(
        self,
        query: str,
        *,
        top_k: int = 5,
        max_chars: int = 3000,
        min_score: float = 0.05,
        session: str | None = None,
    ) -> str:
        """Render bounded retrieval text suitable for prompt injection."""
        max_chars = max(0, min(int(max_chars), 20_000))
        if max_chars == 0:
            return ""
        lines: list[str] = []
        for item in self.search(
            query,
            top_k=top_k,
            min_score=min_score,
            session=session,
        ):
            line = (
                f"- [kind={item.kind} outcome={item.outcome} "
                f"session={item.session} timestamp={item.timestamp}] {item.text}"
            )
            prefix = "\n" if lines else ""
            remaining = max_chars - len("\n".join(lines)) - len(prefix)
            if remaining <= 0:
                break
            if len(line) > remaining:
                if remaining > 3:
                    lines.append(line[:remaining - 3] + "...")
                break
            lines.append(line)
        return "\n".join(lines)

    def delete_session(self, session: str) -> int:
        """Delete experience records owned by one logical session."""
        session = str(session).strip()
        if not session:
            return 0
        with _STORE_LOCK:
            records = self._load_records()
            kept = [item for item in records if item.get("session") != session]
            removed = len(records) - len(kept)
            if removed:
                self._save_records(kept)
        return removed
