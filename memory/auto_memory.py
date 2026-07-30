"""Automatic memory extraction from conversations."""

import re
import json
import threading
from functools import wraps
from pathlib import Path
from datetime import datetime
from typing import Optional

from RxyCode.RxyCode1_1_0.config.settings import get_data_dir, get_dated_data_dir
from RxyCode.RxyCode1_1_0.memory.long_term import validate_session_id
from RxyCode.RxyCode1_1_0.utils.atomic_file import atomic_write_text

_MEMORY_LOCK = threading.RLock()


def _locked(method):
    @wraps(method)
    def wrapper(*args, **kwargs):
        with _MEMORY_LOCK:
            return method(*args, **kwargs)

    return wrapper


def _sessions_dir() -> Path:
    d = get_dated_data_dir("sessions") / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_session_dir(session_id: str) -> Path | None:
    current = _sessions_dir() / session_id
    if current.exists():
        return current
    matches = sorted(
        (get_data_dir() / "sessions").glob(f"*/memory/{session_id}"),
        key=lambda item: item.parent.parent.name,
        reverse=True,
    )
    if matches:
        return matches[0]
    legacy = get_data_dir() / "memory" / "sessions" / session_id
    return legacy if legacy.exists() else None


class AutoMemory:
    def __init__(self, session_id: Optional[str] = None):
        self.session_id = validate_session_id(session_id or "latest")
        existing_dir = _find_session_dir(self.session_id)
        self._dir = _sessions_dir() / self.session_id
        self._dir.mkdir(parents=True, exist_ok=True)
        existing_dir = existing_dir or self._dir
        self._facts_file = self._dir / "auto_facts.md"
        self._compress_file = self._dir / "compressed.md"
        self._existing_facts_file = existing_dir / "auto_facts.md"
        self._existing_compress_file = existing_dir / "compressed.md"

    def _refresh_session_dir(self) -> None:
        current = _sessions_dir() / self.session_id
        current.mkdir(parents=True, exist_ok=True)
        if current != self._dir:
            self._dir = current
            self._facts_file = current / "auto_facts.md"
            self._compress_file = current / "compressed.md"

    def extract_facts(self, messages: list[dict]) -> list[str]:
        facts = []
        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")
            if not content:
                continue
            if role == "user":
                facts.extend(self._extract_user_facts(content))
            elif role == "assistant":
                facts.extend(self._extract_assistant_facts(content))
        return list(dict.fromkeys(facts))

    # ------------------------------------------------------------------
    # LLM-based fact extraction (stitched from mem0 extraction prompt)
    # ------------------------------------------------------------------

    _LLM_EXTRACT_PROMPT = (
        "Extract key facts from the following conversation. Focus on:\n"
        "1. User preferences and habits\n"
        "2. Project context and tech stack\n"
        "3. Important decisions and constraints\n"
        "4. File paths and configurations mentioned\n"
        "\n"
        "Respond with JSON: "
        '{"facts": ["fact1", "fact2", ...], '
        '"updates": [{"old": "old_fact", "new": "new_fact"}], '
        '"deletes": ["outdated_fact"]}'
    )

    async def extract_facts_llm(self, messages: list[dict], llm) -> list[str]:
        """Extract facts using an LLM (mem0-style).

        Falls back to regex extraction if LLM is None or errors out.

        Args:
            messages: Conversation messages as list of dicts with
                      ``role`` and ``content`` keys.
            llm: An LLM object exposing ``async def chat(messages) -> str``
                 (or a compatible callable).

        Returns:
            A list of extracted fact strings.
        """
        # Fallback: no LLM provided -> use regex extraction
        if llm is None:
            return self.extract_facts(messages)

        # Build conversation text for the LLM
        conversation_lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                conversation_lines.append(f"{role}: {content}")
        conversation_text = "\n".join(conversation_lines)

        if not conversation_text.strip():
            return []

        # Build LLM messages
        llm_messages = [
            {"role": "system", "content": self._LLM_EXTRACT_PROMPT},
            {"role": "user", "content": conversation_text},
        ]

        try:
            # Support both sync and async LLM interfaces
            import asyncio
            if asyncio.iscoroutinefunction(getattr(llm, "chat", None)):
                raw_response = await llm.chat(llm_messages)
            elif callable(getattr(llm, "chat", None)):
                raw_response = llm.chat(llm_messages)
            elif asyncio.iscoroutinefunction(llm):
                raw_response = await llm(llm_messages)
            elif callable(llm):
                raw_response = llm(llm_messages)
            else:
                # Unsupported LLM interface -> fallback
                return self.extract_facts(messages)
        except Exception:
            return self.extract_facts(messages)

        # Parse JSON response
        facts, updates, deletes = self._parse_llm_response(raw_response)

        # Persist via store_facts_llm (handles updates / deletes / 100-cap)
        self.store_facts_llm(facts, updates, deletes)

        # Return the newly extracted facts (merged with regex fallback for robustness)
        regex_facts = self.extract_facts(messages)
        merged = list(dict.fromkeys(facts + regex_facts))
        return merged

    def _parse_llm_response(self, response: str) -> tuple[list[str], list[dict], list[str]]:
        """Parse the LLM JSON response into (facts, updates, deletes)."""
        # Try to extract JSON from the response (may be wrapped in ```json ... ```)
        json_str = response.strip()

        # Strip markdown code fences if present
        if json_str.startswith("```"):
            lines = json_str.splitlines()
            # Remove first and last line (fences)
            lines = [l for l in lines if not l.strip().startswith("```")]
            json_str = "\n".join(lines)

        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            # Try to find a JSON object in the text
            import re
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except (json.JSONDecodeError, TypeError):
                    return [], [], []
            else:
                return [], [], []

        facts = data.get("facts", [])
        updates = data.get("updates", [])
        deletes = data.get("deletes", [])

        # Type safety
        if not isinstance(facts, list):
            facts = []
        if not isinstance(updates, list):
            updates = []
        if not isinstance(deletes, list):
            deletes = []

        return [str(f) for f in facts], updates, deletes

    @_locked
    def store_facts_llm(
        self,
        facts: list[str],
        updates: list[dict] | None = None,
        deletes: list[str] | None = None,
    ):
        """Store facts with update/delete operations (mem0-style).

        - ``facts``: new facts to append (after deduplication).
        - ``updates``: list of ``{"old": "old_fact", "new": "new_fact"}``
          entries; replaces the old fact with the new one.
        - ``deletes``: list of outdated facts to remove.

        Preserves the 100-fact upper bound and deduplication.
        """
        if not facts and not updates and not deletes:
            return

        existing = self._load_facts()

        # Apply deletes
        if deletes:
            delete_set = {d.strip() for d in deletes if d}
            existing = [f for f in existing if f not in delete_set]

        # Apply updates (replace old fact with new)
        if updates:
            for upd in updates:
                old_fact = upd.get("old", "").strip() if isinstance(upd, dict) else ""
                new_fact = upd.get("new", "").strip() if isinstance(upd, dict) else ""
                if old_fact and old_fact in existing:
                    idx = existing.index(old_fact)
                    if new_fact:
                        existing[idx] = new_fact
                    else:
                        existing.pop(idx)
                elif new_fact and new_fact not in existing:
                    existing.append(new_fact)

        # Append new facts (deduplicated)
        if facts:
            existing = existing + [f for f in facts if f not in existing]

        # Deduplicate and cap at 100
        all_facts = list(dict.fromkeys(existing))[-100:]

        content = f"# Auto-extracted facts\n\n_Session: {self.session_id}_\n\n"
        for i, fact in enumerate(all_facts, 1):
            content += f"- {fact}\n"
        atomic_write_text(self._facts_file, content)

    def _extract_user_facts(self, text: str) -> list[str]:
        facts = []

        # === Chinese patterns ===
        zh_patterns = [
            r"(?:我叫|我的名字是|叫我)\s*(\S+)",
            r"(?:我喜欢|我偏好|我习惯)\s*(.{2,20})",
            r"(?:我在|我住在|我在)\s*(\S+)",
            r"(?:我正在做|我在做|我正在研究)\s*(.{2,30})",
            r"(?:请记住|记住|注意)\s*(.{2,50})",
            r"(?:我需要|我想要|我希望)\s*(.{2,30})",
            r"(?:使用|用)\s*(\S+(?:框架|库|工具))",
            r"(?:项目|应用)\s*(?:叫做|名为|叫)\s*(\S+)",
            r"(?:文件|代码)\s*(?:在|位于|路径)\s*(\S+)",
            r"(?:版本|ver)\s*[:：]?\s*(\S+)",
        ]

        # === English patterns ===
        en_patterns = [
            r"(?:my name is|i'm|i am|call me)\s+(\w+)",
            r"(?:i like|i prefer|i love|i enjoy)\s+(.{2,30})",
            r"(?:i live in|i'm in|i'm from|i work in)\s+(\S+)",
            r"(?:i'm working on|i'm building|i'm developing|i'm studying)\s+(.{2,30})",
            r"(?:please remember|remember this|remember that|note that|keep in mind)\s+(.{2,50})",
            r"(?:i need|i want|i would like|i wish)\s+(.{2,30})",
            r"(?:my favorite|my fav)\s+(\w+)\s+(?:is|are)\s+(.{2,20})",
            r"(?:i use|i'm using|using)\s+(\S+(?:framework|library|tool|language))",
            r"(?:project|app|application)\s+(?:called|named|is)\s+(\S+)",
            r"(?:file|code|source)\s+(?:is at|located at|at|in)\s+(\S+)",
            r"(?:version|ver)\s*[:]?\s*(\S+)",
        ]

        for pattern in zh_patterns + en_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                if isinstance(m, tuple):
                    m = m[0] if m[0] else m[1] if len(m) > 1 else ""
                if len(m.strip()) >= 2:
                    facts.append(m.strip())

        # Capture code-related context
        code_keywords = ["python", "java", "javascript", "typescript", "react", "vue",
                         "node", "django", "flask", "fastapi", "requests", "selenium",
                         "框架", "接口", "API", "数据库", "SQL", "Redis", "MySQL"]
        text_lower = text.lower()
        for kw in code_keywords:
            if kw.lower() in text_lower and len(text) < 200:
                facts.append(f"用户提及: {text[:100].strip()}")
                break

        if len(text) > 100 and any(kw in text for kw in ["项目", "project", "代码", "code"]):
            facts.append(text[:80].strip())
        return facts

    def _extract_assistant_facts(self, text: str) -> list[str]:
        facts = []
        patterns = [
            r'(?:关键点|重点|总结|概括一下|总结一下)\s*[:：]\s*(.{5,60})',
            r'(?:建议|推荐)\s*[:：]\s*(.{5,60})',
            r'(?:记住|注意|注意)\s*[:：]\s*(.{5,60})',
            r'(?:Key point|Summary|Important|Note)\s*[:]\s*(.{5,60})',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                facts.append(m.strip())
        return facts

    @_locked
    def store_facts(self, facts: list[str]):
        if not facts:
            return
        self._refresh_session_dir()
        existing = self._load_facts()
        all_facts = existing + facts
        all_facts = list(dict.fromkeys(all_facts))[-100:]
        content = f"# Auto-extracted facts\n\n_Session: {self.session_id}_\n\n"
        for i, fact in enumerate(all_facts, 1):
            content += f"- {fact}\n"
        atomic_write_text(self._facts_file, content)

    def _load_facts(self) -> list[str]:
        source = self._facts_file if self._facts_file.exists() else self._existing_facts_file
        if not source.exists():
            return []
        try:
            text = source.read_text(encoding="utf-8")
            facts = []
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("- "):
                    facts.append(line[2:].strip())
            return facts
        except OSError:
            return []

    @_locked
    def compress_old_messages(self, messages: list[dict], keep_recent: int = 6) -> str:
        self._refresh_session_dir()
        if len(messages) <= keep_recent:
            return ""
        old = messages[:-keep_recent]
        parts = []
        for msg in old:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]
            parts.append(f"{role}: {content}")
        compressed = "\n---\n".join(parts)
        header = f"# Compressed conversation\n\n_Session: {self.session_id} | {datetime.now().isoformat()}_\n\n"
        atomic_write_text(self._compress_file, header + compressed)
        return compressed

    def load_compressed(self) -> str:
        self._refresh_session_dir()
        source = self._compress_file if self._compress_file.exists() else self._existing_compress_file
        if not source.exists():
            return ""
        try:
            return source.read_text(encoding="utf-8")
        except OSError:
            return ""

    def load_facts(self) -> str:
        self._refresh_session_dir()
        source = self._facts_file if self._facts_file.exists() else self._existing_facts_file
        if not source.exists():
            return ""
        try:
            return source.read_text(encoding="utf-8")
        except OSError:
            return ""

    def get_context(self, max_facts: int = 10) -> str:
        if not hasattr(self, "_facts_file"):
            return ""
        self._refresh_session_dir()
        source = self._facts_file if self._facts_file.exists() else self._existing_facts_file
        if not source.exists():
            return ""
        try:
            text = source.read_text(encoding="utf-8")
            lines = text.split("\n")
            fact_lines = [l for l in lines if l.startswith("- ")][:max_facts]
            if not fact_lines:
                return ""
            return "# Auto-extracted facts\n" + "\n".join(fact_lines)
        except Exception:
            return ""
