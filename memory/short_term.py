from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from collections import deque
from typing import List


class ShortTermMemory:
    """Short-term memory with improved context isolation.
    
    FIX-1: Reduce default window_size to prevent context pollution.
    The old window_size=20 stored 40 messages, causing old context
    to pollute new conversations (牛头不对马嘴 issue).
    """
    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self._messages: deque[BaseMessage] = deque(maxlen=window_size * 2)
        # FIX-1: Track conversation turns for better context management
        self._turn_count = 0

    def add_user_message(self, content: str):
        self._messages.append(HumanMessage(content=content))
        self._turn_count += 1

    def add_ai_message(self, content: str):
        self._messages.append(AIMessage(content=content))

    def get_messages(self) -> List[BaseMessage]:
        return list(self._messages)

    def get_messages_as_dicts(self) -> list[dict]:
        result = []
        for msg in self._messages:
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            result.append({"role": role, "content": msg.content})
        return result

    def load_from_dicts(self, messages: list[dict]):
        self._messages.clear()
        for msg in messages:
            role = msg.get("role")
            if role == "user":
                self._messages.append(HumanMessage(content=msg["content"]))
            elif role == "assistant":
                self._messages.append(AIMessage(content=msg["content"]))
        self._turn_count = len([m for m in messages if m["role"] == "user"])

    def get_context_string(self, max_turns: int = 5) -> str:
        """Get recent context string, limited to last N turns.
        
        FIX-1: Only return recent turns to prevent context pollution.
        Old implementation returned ALL messages in the window.
        """
        messages = list(self._messages)
        # Only include recent messages (last max_turns * 2 messages)
        recent = messages[-(max_turns * 2):] if len(messages) > max_turns * 2 else messages
        parts = []
        for msg in recent:
            role = "User" if isinstance(msg, HumanMessage) else "Assistant"
            # Truncate long messages to prevent context overflow
            content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
            parts.append(f"{role}: {content}")
        return "\n".join(parts)

    def clear(self):
        self._messages.clear()
        self._turn_count = 0

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def turn_count(self) -> int:
        return self._turn_count

    def is_overflow(self, threshold: int = 30) -> bool:
        """Check if memory is overflowing.
        
        FIX-1: Reduced threshold from 50 to 30 to trigger compression earlier.
        """
        return len(self._messages) >= threshold

    def pop_oldest_pair(self) -> tuple[str, str] | None:
        if len(self._messages) < 2:
            return None
        user_msg = self._messages.popleft()
        ai_msg = self._messages.popleft()
        return user_msg.content, ai_msg.content

    def get_relevant_context(self, query: str, max_items: int = 3) -> str:
        """Get context relevant to the current query.
        
        FIX-1: New method to extract relevant context based on query keywords.
        This helps prevent the "牛头不对马嘴" issue by filtering relevant messages.
        """
        if not self._messages:
            return ""
        
        # Simple keyword matching for relevance scoring
        import re

        query_lower = query.lower()
        query_words = set(query_lower.split())
        # CJK runs (no spaces): treat 2+ char substrings as tokens
        for run in re.findall(r"[\u4e00-\u9fff]{2,}", query_lower):
            query_words.add(run)
            for i in range(len(run) - 1):
                query_words.add(run[i : i + 2])

        scored_messages = []
        for msg in self._messages:
            content_lower = msg.content.lower()
            # Calculate relevance score based on word overlap
            content_words = set(content_lower.split())
            for run in re.findall(r"[\u4e00-\u9fff]{2,}", content_lower):
                content_words.add(run)
                for i in range(len(run) - 1):
                    content_words.add(run[i : i + 2])
            overlap = len(query_words.intersection(content_words))
            # Substring fallback when split tokens miss
            if overlap == 0:
                for token in query_words:
                    if len(token) >= 2 and token in content_lower:
                        overlap += 1
            # Boost score for recent messages
            recency_boost = 1.0 if isinstance(msg, AIMessage) else 0.5
            score = overlap * recency_boost
            scored_messages.append((score, msg))
        
        # Sort by relevance score (descending) and take top N
        scored_messages.sort(key=lambda x: x[0], reverse=True)
        # Zero-score history must not pollute unrelated turns (e.g. 你好 after parkour).
        if not scored_messages or scored_messages[0][0] <= 0:
            return ""
        relevant = scored_messages[:max_items]
        
        # Sort by original order (timestamp)
        relevant.sort(key=lambda x: list(self._messages).index(x[1]))
        
        parts = []
        for _, msg in relevant:
            role = "User" if isinstance(msg, HumanMessage) else "Assistant"
            content = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content
            parts.append(f"{role}: {content}")
        
        return "\n".join(parts)
