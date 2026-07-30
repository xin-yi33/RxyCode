"""ContextCompressor: Codex-style three-tier context compression.

Tier 1 — Lossless truncation (zero LLM cost)
    1. Middle truncation for tool outputs > threshold tokens
       (keep beginning summary + ending error info, discard middle)
    2. Trim old assistant replies to first 2 sentences
    3. Remove irrelevant tool definitions (caller responsibility)

Tier 2 — Rule-based simplification (still no LLM)
    1. Protected zone: last N tokens of user messages untouched
    2. Older messages replaced with placeholder, raw text moved to long-term

Tier 3 — Incremental LLM summary (fallback, calls LLM)
    1. Extract delta between last handoff summary and protected zone
    2. LLM generates unified handoff summary (old + delta)
    3. Delete original history, keep: summary + protected zone
    4. Incremental merge: only summarize new content, not everything
"""

from __future__ import annotations

import re
from typing import Optional


class ContextCompressor:
    """Three-tier context compression following Codex strategy."""

    def __init__(
        self,
        llm=None,
        max_tokens: int = 258_000,
        trigger_ratio: float = 0.9,
        tier1_tool_threshold: int = 10_000,
        tier2_protected_tokens: int = 20_000,
    ):
        self._llm = llm
        self._max_tokens = max_tokens
        self._trigger_ratio = trigger_ratio
        self._tier1_tool_threshold = tier1_tool_threshold
        self._tier2_protected_tokens = tier2_protected_tokens
        self._last_handoff: str = ""
        self._encoder = None

    # ------------------------------------------------------------------
    # Token counting
    # ------------------------------------------------------------------

    def _get_encoder(self):
        if self._encoder is None:
            try:
                import tiktoken
                self._encoder = tiktoken.get_encoding("cl100k_base")
            except Exception:
                pass
        return self._encoder

    def count_tokens(self, text: str) -> int:
        """Count tokens in *text* using tiktoken, with char fallback."""
        enc = self._get_encoder()
        if enc:
            return len(enc.encode(text))
        # Rough: 4 chars/token for English, 1.5 for Chinese → 3 avg
        return len(text) // 3

    def needs_compression(self, context_str: str) -> bool:
        return self.count_tokens(context_str) > int(self._max_tokens * self._trigger_ratio)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def compress_sync(
        self,
        messages: list[dict],
        long_term_ctx: str = "",
    ) -> tuple[list[dict], str]:
        """Sync compression: Tier 1 + Tier 2 only (no LLM).

        Used by MemoryManager._compress_and_store() which is called
        synchronously from add_interaction().

        Returns:
            (compressed_messages, updated_long_term_ctx)
        """
        total_ctx = self._build_context(messages, long_term_ctx)
        if not self.needs_compression(total_ctx):
            return messages, long_term_ctx

        # Tier 1
        messages = self._tier1(messages)
        total_ctx = self._build_context(messages, long_term_ctx)
        if not self.needs_compression(total_ctx):
            return messages, long_term_ctx

        # Tier 2
        messages, long_term_ctx = self._tier2(messages, long_term_ctx)
        return messages, long_term_ctx

    async def compress_async(
        self,
        messages: list[dict],
        long_term_ctx: str = "",
    ) -> tuple[list[dict], str, bool]:
        """Async compression: full Tier 1 + 2 + 3 (may call LLM).

        Used by MemoryManager.compress_if_needed() which is called
        from the LangGraph compressor_node.

        Returns:
            (compressed_messages, updated_long_term_ctx, llm_was_used)
        """
        # Run sync tiers first
        messages, long_term_ctx = self.compress_sync(messages, long_term_ctx)

        total_ctx = self._build_context(messages, long_term_ctx)
        if not self.needs_compression(total_ctx):
            return messages, long_term_ctx, False

        # Tier 3 — needs LLM
        if self._llm:
            messages, long_term_ctx = await self._tier3(messages, long_term_ctx)
            return messages, long_term_ctx, True

        return messages, long_term_ctx, False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_context(self, messages: list[dict], long_term_ctx: str) -> str:
        parts = []
        if long_term_ctx:
            parts.append(f"[Long-term memory]\n{long_term_ctx}")
        msg_str = self._messages_to_str(messages)
        if msg_str:
            parts.append(f"[Recent conversation]\n{msg_str}")
        return "\n\n".join(parts)

    @staticmethod
    def _messages_to_str(messages: list[dict]) -> str:
        parts = []
        for m in messages:
            role = "User" if m.get("role") == "user" else "Assistant"
            parts.append(f"{role}: {m.get('content', '')}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Tier 1: Lossless truncation
    # ------------------------------------------------------------------

    def _tier1(self, messages: list[dict]) -> list[dict]:
        """Tier 1: middle truncation + assistant reply trimming."""
        result = []
        for m in messages:
            content = m.get("content", "")
            tokens = self.count_tokens(content)

            # 1a. Middle truncation for long outputs (> 10k tokens)
            if tokens > self._tier1_tool_threshold:
                content = self._middle_truncate(content)

            # 1b. Trim assistant replies to first 2 sentences (> 500 tokens)
            elif m.get("role") == "assistant" and tokens > 500:
                content = self._trim_to_two_sentences(content)

            result.append({**m, "content": content})
        return result

    def _middle_truncate(self, text: str) -> str:
        """Keep beginning + ending, discard middle. Insert truncation marker."""
        # Target: ~500 tokens each end
        chars_per_token = 3
        keep_chars = 500 * chars_per_token

        if len(text) <= keep_chars * 2 + 100:
            return text

        beginning = text[:keep_chars]
        ending = text[-keep_chars:]

        # Clean break: find last newline in beginning
        nl = beginning.rfind("\n")
        if nl > keep_chars * 0.5:
            beginning = beginning[:nl]

        # Clean break: find first newline in ending
        nl = ending.find("\n")
        if 0 <= nl < keep_chars * 0.5:
            ending = ending[nl:]

        truncated = len(text) - len(beginning) - len(ending)
        marker = f"\n...[truncated {truncated} chars]...\n"
        return f"{beginning}{marker}{ending}"

    @staticmethod
    def _trim_to_two_sentences(text: str) -> str:
        """Keep first 2 sentences of assistant reply."""
        sentences = re.split(r"(?<=[.!?。！？])\s+", text.strip())
        if len(sentences) <= 2:
            return text
        first_two = " ".join(sentences[:2])
        remaining = len(sentences) - 2
        return f"{first_two}\n...[trimmed {remaining} sentences]"

    # ------------------------------------------------------------------
    # Tier 2: Rule-based simplification
    # ------------------------------------------------------------------

    def _tier2(self, messages: list[dict], long_term_ctx: str) -> tuple[list[dict], str]:
        """Protected zone + placeholder replacement."""
        if not messages:
            return messages, long_term_ctx

        # Walk backwards to find protected zone boundary
        protected_tokens = 0
        protected_start = len(messages)

        for i in range(len(messages) - 1, -1, -1):
            msg_tokens = self.count_tokens(messages[i].get("content", ""))
            if protected_tokens + msg_tokens > self._tier2_protected_tokens:
                break
            protected_tokens += msg_tokens
            protected_start = i

        if protected_start <= 0:
            return messages, long_term_ctx

        # Move old messages to long-term as raw text (no LLM)
        old_messages = messages[:protected_start]
        old_text = self._messages_to_str(old_messages)

        # Truncate individual old messages to prevent bloat
        if len(old_text) > 10000:
            old_text = old_text[:5000] + "\n...\n" + old_text[-5000:]

        new_long_term = f"{long_term_ctx}\n\n{old_text}".strip() if long_term_ctx else old_text

        # Cap long-term at 50KB
        if len(new_long_term) > 50000:
            new_long_term = new_long_term[-30000:]

        placeholder = f"[Previous {protected_start} messages simplified]"
        new_messages = [{"role": "system", "content": placeholder}] + messages[protected_start:]

        return new_messages, new_long_term

    # ------------------------------------------------------------------
    # Tier 3: LLM-based incremental summary
    # ------------------------------------------------------------------

    async def _tier3(self, messages: list[dict], long_term_ctx: str) -> tuple[list[dict], str]:
        """Generate handoff summary using LLM. Incremental merge."""
        if not self._llm or not messages:
            return messages, long_term_ctx

        # Define protected zone (same as Tier 2)
        protected_tokens = 0
        protected_start = len(messages)

        for i in range(len(messages) - 1, -1, -1):
            msg_tokens = self.count_tokens(messages[i].get("content", ""))
            if protected_tokens + msg_tokens > self._tier2_protected_tokens:
                break
            protected_tokens += msg_tokens
            protected_start = i

        # Extract delta: messages between last handoff and protected zone
        delta_messages = messages[:protected_start]
        if not delta_messages:
            return messages, long_term_ctx

        delta_text = self._messages_to_str(delta_messages)
        # Cap delta to 10k chars to keep LLM prompt reasonable
        if len(delta_text) > 10000:
            delta_text = delta_text[:5000] + "\n...\n" + delta_text[-5000:]

        old_summary = self._last_handoff or long_term_ctx or "(no prior summary)"

        prompt = f"""You are generating a handoff summary for a general-purpose AI agent.

Previous handoff summary:
{old_summary}

New conversation since last handoff:
{delta_text}

Generate a unified handoff summary that:
1. Merges the previous summary with the new conversation
2. Keeps key facts, decisions, file paths, code snippets, and user preferences
3. Drops redundant or obsolete information
4. Is concise but complete — another AI will use this as its only context

Output the summary as plain text, no JSON, no markdown headers:"""

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            resp = await self._llm.ainvoke([
                SystemMessage(content="You are a concise summarizer for AI agent context."),
                HumanMessage(content=prompt),
            ])

            new_summary = resp.content.strip()
            self._last_handoff = new_summary

            # Keep only protected zone messages + summary as system msg
            protected_messages = messages[protected_start:]
            return protected_messages, new_summary

        except Exception:
            # LLM failed, return what we have
            return messages, long_term_ctx
