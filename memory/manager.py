from typing import Optional
from pathlib import Path
from collections import OrderedDict
import math
import threading
import time
from typing import Any

from RxyCode.RxyCode1_1_0.config.settings import load_config

from .short_term import ShortTermMemory
from .long_term import LongTermMemory
from .compressor import ContextCompressor
from .vector_memory import ExperienceVectorMemory


def _positive_int(value, default: int, maximum: int) -> int:
    """Parse a bounded positive integer from user configuration."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, maximum))


def _enabled(value) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _positive_float(value, default: float, maximum: float) -> float:
    """Parse a bounded positive float from user configuration."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if not math.isfinite(parsed) or parsed <= 0:
        parsed = default
    return min(parsed, maximum)


class MemoryManager:
    """Memory manager with improved context retrieval.
    
    FIX-1: Reduced default window_size and threshold to prevent context pollution.
    Added query-aware context retrieval to prevent "牛头不对马嘴" issue.
    """
    def __init__(
        self,
        session_id: Optional[str] = None,
        window_size: Optional[int] = None,
        threshold: Optional[int] = None,
        llm=None,
        max_tokens: int = 258_000,
    ):
        cfg = load_config()
        raw_memory_cfg = cfg.get("memory", {})
        memory_cfg = raw_memory_cfg if isinstance(raw_memory_cfg, dict) else {}
        raw_rag_cfg = cfg.get("rag", {})
        rag_cfg = raw_rag_cfg if isinstance(raw_rag_cfg, dict) else {}

        configured_window = (
            window_size
            if window_size is not None
            else memory_cfg.get("short_term_window", 10)
        )
        resolved_window = _positive_int(configured_window, 10, 500)
        message_capacity = resolved_window * 2
        configured_threshold = (
            threshold
            if threshold is not None
            else memory_cfg.get("long_term_threshold", min(30, message_capacity))
        )
        resolved_threshold = _positive_int(
            configured_threshold, min(30, message_capacity), message_capacity,
        )
        # Interactions are stored in user/assistant pairs, so keep this even.
        resolved_threshold = max(2, resolved_threshold - resolved_threshold % 2)

        self.session_id = session_id or "latest"
        self.short_term = ShortTermMemory(window_size=resolved_window)
        self.long_term = LongTermMemory(session_id=self.session_id)
        self.threshold = resolved_threshold
        self._compressor = ContextCompressor(llm=llm, max_tokens=max_tokens)
        self._overflow_keep_messages = max(
            2, min(10, resolved_threshold // 2),
        )
        if self._overflow_keep_messages % 2:
            self._overflow_keep_messages -= 1

        self._experience_top_k = _positive_int(
            memory_cfg.get("experience_top_k", 4), 4,
            ExperienceVectorMemory.MAX_TOP_K,
        )
        self._experience_max_chars = _positive_int(
            memory_cfg.get("experience_max_chars", 3000), 3000, 20_000,
        )
        self._experience_cross_session = _enabled(
            memory_cfg.get("experience_cross_session", False)
        )
        dimension = _positive_int(
            memory_cfg.get("experience_vector_dimension", 256), 256, 4096,
        )
        max_entries = _positive_int(
            memory_cfg.get("experience_max_entries", 2000), 2000, 20_000,
        )
        self._project_root = Path.cwd().resolve()
        self.experience = ExperienceVectorMemory(
            project=str(self._project_root),
            dimension=dimension,
            max_entries=max_entries,
        )
        self._rag_enabled = _enabled(rag_cfg.get("enabled", False))
        self._rag_top_k = _positive_int(rag_cfg.get("top_k", 6), 6, 20)
        rag_max_chars = rag_cfg.get(
            "max_context_chars", rag_cfg.get("max_chars", 6000),
        )
        self._rag_max_chars = _positive_int(rag_max_chars, 6000, 20_000)
        self._rag_cache_limit = _positive_int(
            rag_cfg.get("context_cache_entries", 64), 64, 256,
        )
        self._rag_cache_ttl_seconds = _positive_float(
            rag_cfg.get("context_cache_ttl_seconds", 30), 30.0, 3600.0,
        )
        self._rag_context_cache: OrderedDict[
            str, tuple[float, str]
        ] = OrderedDict()
        self._rag_cache_lock = threading.RLock()
        self._rag_cache_epoch = 0
        self._rag_indexer: Any | None = None
        self._rag_index_dirty = False
        self._rag_refresh_generation: int | None = None
        # FIX-1: Track current query for context-aware retrieval
        self._current_query = ""


    async def initialize(self):
        """Initialize memory system (async compatibility)."""
        pass

    async def close(self):
        """Cleanup resources (async compatibility)."""
        pass

    def add_interaction(self, user_input: str, ai_response: str):
        """Add a user+assistant interaction to short-term memory.

        If overflow is detected, runs Tier 1/2 compression (sync, no LLM)
        unless ``autoCompact`` is disabled in config.
        """
        self.short_term.add_user_message(user_input)
        self.short_term.add_ai_message(ai_response)
        cfg = load_config() or {}
        if not _enabled(cfg.get("autoCompact", True)):
            return
        if self.short_term.is_overflow(self.threshold):
            self._compress_and_store()

    def _compress_and_store(self):
        """Sync compression: Tier 1 + Tier 2 only (no LLM cost).

        Called from add_interaction() when short-term overflows.
        """
        messages = self.short_term.get_messages_as_dicts()
        long_ctx = self.long_term.load_session_context()

        compressed, new_long_ctx = self._compressor.compress_sync(messages, long_ctx)

        # Token compression intentionally ignores small messages. The message
        # count is an independent bound, so archive old complete turns here.
        if len(compressed) >= self.threshold:
            keep_count = min(
                self._overflow_keep_messages,
                max(0, len(compressed) - 2),
            )
            if keep_count % 2:
                keep_count -= 1
            if keep_count:
                archived = compressed[:-keep_count]
                compressed = compressed[-keep_count:]
            else:
                archived = compressed
                compressed = []
            archived_text = self._compressor._messages_to_str(archived)
            if len(archived_text) > 10_000:
                archived_text = (
                    archived_text[:5000] + "\n...\n" + archived_text[-5000:]
                )
            segment = f"[Archived conversation segment]\n{archived_text}"
            new_long_ctx = (
                f"{new_long_ctx}\n\n{segment}".strip()
                if new_long_ctx else segment
            )
            if len(new_long_ctx) > 50_000:
                new_long_ctx = new_long_ctx[-30_000:]

        # Load compressed messages back
        self.short_term.load_from_dicts(compressed)

        # Update long-term context
        if new_long_ctx != long_ctx:
            self.long_term.save_session_context(new_long_ctx)

    def get_context_for_prompt(self, query: str = "", *, include_long_term: bool = True) -> str:
        """Get context for prompt injection.
        
        FIX-1: Added query parameter for context-aware retrieval.
        If query is provided, returns relevant context instead of all context.
        include_long_term=False skips archived session context (social turns).
        """
        parts = []
        self._current_query = query
        
        # Long-term memory (always include, but truncate if too long)
        if include_long_term:
            long_ctx = self.long_term.load_session_context()
            if long_ctx:
                # Truncate long-term context to prevent overflow
                if len(long_ctx) > 2000:
                    long_ctx = long_ctx[:2000] + "..."
                parts.append(f"[Long-term memory]\n{long_ctx}")

        if query:
            experience_ctx = self.get_retrieval_context(query)
            if experience_ctx:
                parts.append(f"[Relevant verified experience]\n{experience_ctx}")

            code_ctx = self.get_code_context(query)
            if code_ctx:
                parts.append(f"[Relevant code context]\n{code_ctx}")
        
        # Short-term memory (use relevant context if query provided)
        if query:
            # FIX-1: Use query-aware context retrieval
            short_ctx = self.short_term.get_relevant_context(query, max_items=3)
        else:
            # Fallback to recent context (limited turns)
            short_ctx = self.short_term.get_context_string(max_turns=3)
        
        if short_ctx:
            parts.append(f"[Recent conversation]\n{short_ctx}")
        
        return "\n\n".join(parts)

    def get_retrieval_context(
        self,
        query: str,
        *,
        top_k: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> str:
        """Return bounded, project-local experience context for an LLM prompt."""
        return self.experience.retrieve_context(
            query,
            top_k=top_k if top_k is not None else self._experience_top_k,
            max_chars=(
                max_chars if max_chars is not None else self._experience_max_chars
            ),
            session=None if self._experience_cross_session else self.session_id,
        )

    def get_code_context(self, query: str) -> str:
        """Return cached, bounded, offline code RAG context when enabled."""
        if not self._rag_enabled:
            return ""
        normalized = str(query).strip()[:4000]
        if not normalized:
            return ""

        prefer_live_files = self._prefer_live_code_files()
        now = time.monotonic()
        with self._rag_cache_lock:
            self._purge_expired_rag_cache_locked(now)
            cached = self._rag_context_cache.get(normalized)
            if cached is not None:
                self._rag_context_cache.move_to_end(normalized)
                return cached[1]
            cache_epoch = self._rag_cache_epoch

        try:
            from RxyCode.RxyCode1_1_0.rag.search import retrieve_context

            retrieval_kwargs = {
                "root": self._project_root,
                "top_k": self._rag_top_k,
                "max_chars": self._rag_max_chars,
                "allow_network": False,
            }
            if prefer_live_files:
                retrieval_kwargs["prefer_live_files"] = True
            result = retrieve_context(normalized, **retrieval_kwargs)
        except Exception:
            result = ""

        context = str(result).strip()[:self._rag_max_chars] if result else ""
        if context.casefold() in {
            "[no code chunks found]",
            "[no project found]",
            "[no project indexed]",
            "[no results found]",
        }:
            context = ""
        # Cache empty/error outcomes too. The epoch check prevents a retrieval
        # racing with a write from repopulating stale code context.
        with self._rag_cache_lock:
            if cache_epoch == self._rag_cache_epoch:
                expires_at = time.monotonic() + self._rag_cache_ttl_seconds
                self._rag_context_cache[normalized] = (expires_at, context)
                self._rag_context_cache.move_to_end(normalized)
                while len(self._rag_context_cache) > self._rag_cache_limit:
                    self._rag_context_cache.popitem(last=False)
        return context

    def bind_rag_indexer(self, indexer: Any | None) -> None:
        """Attach the process-local index coordinator used for freshness state."""
        if self._rag_enabled:
            self._rag_indexer = indexer

    def begin_run(self, run_id: str = "") -> None:
        """Start a run with live retrieval and a non-blocking index refresh."""
        if not self._rag_enabled:
            return
        generation = None
        indexer = self._rag_indexer
        if indexer is not None:
            try:
                generation = indexer.request_refresh()
            except Exception:
                generation = None
        with self._rag_cache_lock:
            self._rag_cache_epoch += 1
            self._rag_context_cache.clear()
            self._rag_index_dirty = True
            self._rag_refresh_generation = generation

    def invalidate_code_context(
        self,
        *,
        code_changed: bool = False,
        refresh_generation: int | None = None,
    ) -> None:
        """Invalidate cached retrievals after a code-affecting operation."""
        if not self._rag_enabled:
            return
        with self._rag_cache_lock:
            self._rag_cache_epoch += 1
            self._rag_context_cache.clear()
            if code_changed:
                self._rag_index_dirty = True
                self._rag_refresh_generation = refresh_generation

    def rag_cache_status(self) -> dict[str, int | float | bool]:
        """Return content-free live cache state for runtime diagnostics."""
        if not self._rag_enabled:
            return {"enabled": False, "entries": 0, "dirty": False}
        self._prefer_live_code_files()
        with self._rag_cache_lock:
            self._purge_expired_rag_cache_locked(time.monotonic())
            return {
                "enabled": True,
                "entries": len(self._rag_context_cache),
                "limit": self._rag_cache_limit,
                "ttl_seconds": self._rag_cache_ttl_seconds,
                "dirty": self._rag_index_dirty,
            }

    def _purge_expired_rag_cache_locked(self, now: float) -> None:
        expired = [
            key
            for key, (expires_at, _context) in self._rag_context_cache.items()
            if expires_at <= now
        ]
        for key in expired:
            self._rag_context_cache.pop(key, None)

    def _prefer_live_code_files(self) -> bool:
        """Use live files until the refresh covering the latest write succeeds."""
        with self._rag_cache_lock:
            dirty = self._rag_index_dirty
            expected_generation = self._rag_refresh_generation
            indexer = self._rag_indexer
        if not dirty:
            return False
        if indexer is None or expected_generation is None:
            return True
        try:
            status = indexer.status()
            completed_generation = int(
                status.get("last_success_generation", 0) or 0
            )
        except Exception:
            return True
        if completed_generation < expected_generation:
            return True
        with self._rag_cache_lock:
            if self._rag_refresh_generation == expected_generation:
                self._rag_index_dirty = False
                self._rag_refresh_generation = None
        return False

    def save_session(self):
        messages = self.short_term.get_messages_as_dicts()
        if messages:
            self.long_term.save_history(messages)

    def load_session(self):
        """Load session history.
        
        FIX-1: Only load recent history to prevent context pollution.
        Old implementation loaded ALL history into short-term memory.
        """
        messages = self.long_term.load_history()
        if messages:
            # Only load the last 10 messages (5 turns) to prevent pollution
            recent_messages = messages[-10:] if len(messages) > 10 else messages
            self.short_term.load_from_dicts(recent_messages)

    def clear(self, *, persisted: bool = False):
        self.short_term.clear()
        self.invalidate_code_context()
        if persisted:
            self.long_term.clear_session()
            self.experience.delete_session(self.session_id)

    async def get_context(self, session_id: str = "", query: str = "") -> str:
        """Get memory context for a session (async compatibility with graph)."""
        return self.get_context_for_prompt(query)

    async def get_task_context(
        self,
        session_id: str = "",
        task_id: str = "",
        parent_id: str = "",
        tree=None,
    ) -> str:
        """Get task-specific context, filtered by dependency chain.

        Stitched from CrewAI task-level context passing + MetaGPT
        subscription-filter model:
        - Global long-term memory summary (always included)
        - TaskTree ancestor chain results (parent task results)
        - Current task description
        - Does NOT return all short-term memory; only task-relevant context.
        """
        parts: list[str] = []

        # 1. Long-term memory summary (always included, truncated to 2000 chars)
        long_ctx = self.long_term.load_session_context()
        if long_ctx:
            if len(long_ctx) > 2000:
                long_ctx = long_ctx[:2000] + "..."
            parts.append(f"[Long-term memory]\n{long_ctx}")

        # 2. Ancestor chain results from TaskTree (if available)
        if tree is not None and task_id:
            ancestor_results = self._collect_ancestor_results(tree, task_id)
            if ancestor_results:
                parts.append(f"[Ancestor task results]\n{ancestor_results}")

            dependency_results = self._collect_dependency_results(tree, task_id)
            if dependency_results:
                parts.append(
                    f"[Verified dependency results]\n{dependency_results}"
                )

        # 3. Parent task result (if parent_id is provided but no tree)
        if tree is not None and parent_id:
            parent_node = tree.nodes.get(parent_id)
            if parent_node and parent_node.result:
                # Truncate parent result to prevent context overflow
                parent_result = parent_node.result
                if len(parent_result) > 1000:
                    parent_result = parent_result[:1000] + "..."
                parts.append(
                    f"[Parent task: {parent_node.title}]\n{parent_result}"
                )
        elif parent_id and not tree:
            # No tree available but parent_id was passed — nothing we can do
            pass

        # 4. Current task description (if available from tree)
        if tree is not None and task_id:
            current_node = tree.nodes.get(task_id)
            if current_node:
                task_desc_parts = [f"[Current task: {current_node.title}]"]
                query_parts = [current_node.title]
                if current_node.description:
                    desc = current_node.description
                    if len(desc) > 500:
                        desc = desc[:500] + "..."
                    task_desc_parts.append(desc)
                    query_parts.append(current_node.description)
                if current_node.requirement:
                    task_desc_parts.append(f"Requirement: {current_node.requirement}")
                    query_parts.append(current_node.requirement)
                parts.append("\n".join(task_desc_parts))

                experience_ctx = self.get_retrieval_context("\n".join(query_parts))
                if experience_ctx:
                    parts.append(
                        f"[Relevant verified experience]\n{experience_ctx}"
                    )

                code_ctx = self.get_code_context("\n".join(query_parts))
                if code_ctx:
                    parts.append(f"[Relevant code context]\n{code_ctx}")

        return "\n\n".join(parts) if parts else ""

    def _collect_ancestor_results(self, tree, task_id: str) -> str:
        """Walk up the parent_id chain and collect results from ancestors.

        Returns a formatted string of ancestor task results.
        Only includes ancestors that have a non-None result.
        """
        results: list[str] = []
        visited: set[str] = set()
        node = tree.nodes.get(task_id)

        while node and node.parent_id and node.parent_id not in visited:
            visited.add(node.parent_id)
            ancestor = tree.nodes.get(node.parent_id)
            if ancestor and ancestor.result:
                result_text = ancestor.result
                if len(result_text) > 500:
                    result_text = result_text[:500] + "..."
                results.append(f"- {ancestor.title}: {result_text}")
            node = ancestor

        return "\n".join(results) if results else ""

    def _collect_dependency_results(self, tree, task_id: str) -> str:
        """Collect only PASSED direct/transitive DAG prerequisite results."""
        current = tree.nodes.get(task_id)
        if current is None:
            return ""

        results: list[str] = []
        visited: set[str] = {task_id}

        def visit(dependency_id: str) -> None:
            if dependency_id in visited:
                return
            visited.add(dependency_id)
            dependency = tree.nodes.get(dependency_id)
            if dependency is None:
                return
            status = getattr(dependency.status, "value", dependency.status)
            if status != "passed":
                return
            for nested_id in dependency.dependent_tasks:
                visit(nested_id)
            if dependency.result:
                result_text = dependency.result
                if len(result_text) > 1000:
                    result_text = result_text[:1000] + "..."
                results.append(f"- {dependency.title}: {result_text}")

        for dependency_id in current.dependent_tasks:
            visit(dependency_id)
        return "\n".join(results)

    async def store_execution(self, session_id: str = "", task_id: str = "", result: str = "") -> None:
        """Persist a verified execution result as reusable experience.

        Only call this AFTER the result has passed validation.
        Unverified or failed results should use log_error() instead.

        Execution records are deliberately kept out of short-term memory:
        they are internal plan artifacts, not user/assistant conversation
        turns.  AgentV2 records the real user input and final answer once via
        :meth:`add_interaction`.
        """
        self.experience.add(
            f"Task {task_id}: {result}",
            kind="execution",
            outcome="success",
            session=session_id or self.session_id,
        )

    async def log_error(self, session_id: str = "", task_id: str = "", error: str = "") -> None:
        """Log an error to the error log (NOT conversation memory).

        This keeps errors accessible for debugging without polluting
        the conversation context that future LLM calls will see.
        """
        self.long_term.append_error_log(task_id, error)
        self.experience.add(
            f"Task {task_id}: {error}",
            kind="failure",
            outcome="failed",
            session=session_id or self.session_id,
        )

    def store_experience(
        self,
        text: str,
        *,
        kind: str = "reflection",
        outcome: str = "unknown",
        session_id: str = "",
    ) -> bool:
        """Public bounded persistence hook for planner/reflection lessons."""
        return self.experience.add(
            text,
            kind=kind,
            outcome=outcome,
            session=session_id or self.session_id,
        )

    async def store_plan_experience(
        self,
        *,
        plan_summary: str,
        failure_type: str,
        corrective_action: str,
        lessons: list[str],
        outcome: str,
        session_id: str = "",
        reason: str = "",
    ) -> bool:
        """Persist one bounded, machine-readable plan lesson.

        Callers must only use ``failed`` after a validated failure/reflection
        and ``success`` after final verification.  The strict outcome contract
        keeps incomplete execution prose out of the reusable success corpus.
        """
        import json

        normalized_outcome = str(outcome).strip().casefold()
        if normalized_outcome not in {"failed", "success"}:
            raise ValueError(
                "plan experience outcome must be 'failed' or 'success'"
            )

        normalized_lessons = [
            str(item).strip()[:500]
            for item in lessons[:8]
            if str(item).strip()
        ]
        resolved_session = str(session_id or self.session_id).strip()[:256]
        payload = {
            "schema_version": 1,
            "plan_summary": str(plan_summary).strip()[:3000],
            "failure_type": str(failure_type).strip()[:64] or "unknown",
            "reason": str(reason).strip()[:1000],
            "corrective_action": str(corrective_action).strip()[:1000],
            "lessons": normalized_lessons,
            "session": resolved_session,
            "project": str(self.experience.project)[:1000],
            "outcome": normalized_outcome,
        }
        return self.store_experience(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            kind=(
                "plan_reflection"
                if normalized_outcome == "failed"
                else "plan_outcome"
            ),
            outcome=normalized_outcome,
            session_id=resolved_session,
        )

    async def compress_if_needed(self, session_id: str = "") -> str:
        """Full three-tier compression (may call LLM for Tier 3).

        Called from the LangGraph compressor_node when route_next()
        detects the context is too large, and from the tool-loop when
        context usage crosses ~85%. Honours ``autoCompact`` config.
        """
        cfg = load_config() or {}
        if not _enabled(cfg.get("autoCompact", True)):
            return self.get_context_for_prompt()

        messages = self.short_term.get_messages_as_dicts()
        long_ctx = self.long_term.load_session_context()

        compressed, new_long_ctx, llm_used = await self._compressor.compress_async(
            messages, long_ctx,
        )

        # Load compressed messages back
        self.short_term.load_from_dicts(compressed)

        # Update long-term context
        if new_long_ctx != long_ctx:
            self.long_term.save_session_context(new_long_ctx)

        return self.get_context_for_prompt()

    def count_tokens(self, text: str) -> int:
        """Delegate to compressor's token counter."""
        return self._compressor.count_tokens(text)
