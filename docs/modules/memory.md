# memory/ - Memory System

## What Is This Module?
Manages conversation memory across sessions. Implements a tiered memory architecture:
- Short-term memory: recent conversation context (window-based)
- Long-term memory: compressed historical context (persistent)
- User memory: explicit user-saved facts and preferences
- Chat storage: named conversation save/load

The `history` tool exposes only explicitly global memory
(`memory/user`, `memory/projects/global`) plus the current session under
`sessions/YYYY-MM-DD/memory/<current_session_id>`. It searches that session
across dates and the legacy `memory/sessions/<current_session_id>` path, but
never enumerates another session's private facts.


## Key Files
| File | Purpose |
|------|---------|
| manager.py | MemoryManager - orchestrates short/long-term memory, context injection. AgentSpec.memory_scope=private gives each expert-team role its own namespace; shared joins the session. |
| short_term.py | ShortTermMemory - sliding window of recent messages |
| long_term.py | LongTermMemory - persistent compressed context store |
| compressor.py | Compresses conversation history into summaries |
| search.py | BM25 keyword search across memory entries |
| vector_memory.py | ExperienceVectorMemory - retrievable vector store for reusable execution experiences/plans |
| session_tui.py | SessionRecordingTUI - full-session recording TUI adapter |
| auto_memory.py | Automatic extraction of important facts from conversations (regex + LLM) |
| user_memory.py | UserMemory - explicit /memory add/list/remove/search commands |
| chat_storage.py | ChatStorage - save/load/list named conversations |

## Core Code: manager.py (MemoryManager)

**Memory Tiers:**
- Short-term: last N message pairs (window_size=10, reduced from 20 to prevent context pollution)
- Long-term session memory: stored in `~/.RxyCode/sessions/YYYY-MM-DD/memory/<session_id>/`
- Named chats: stored in `~/.RxyCode/sessions/YYYY-MM-DD/chats/`

**Key Methods:**
- add_interaction(user_input, ai_response): Adds to short-term, triggers compression if needed
- get_context_for_prompt(query) -> str: Builds context string for LLM. Uses get_relevant_context() for query-aware retrieval instead of dumping all memory.
- get_code_context(query) -> str: Adds bounded code RAG context through a thread-safe LRU. Entries have a TTL and the cache is cleared at every top-level run.
- begin_run(run_id): Clears prior-run code context, requests a non-blocking incremental index refresh, and uses live files until that refresh succeeds.
- invalidate_code_context(code_changed=True, refresh_generation=N): Atomically advances the cache epoch so an older concurrent lookup cannot repopulate stale context.
- rag_cache_status() -> dict: Content-free cache size/limit/TTL/dirty state used by runtime status.
- _compress_and_store(): Compresses short-term into long-term when threshold exceeded
- save_session() / load_session(): Persists/restores session state
- get_context(session_id) -> str: Returns memory context for a session
- count_tokens(text) -> int: Estimates token count using tiktoken

**Compression Strategy:**
- Tier 1: Keep last 5 tool calls, discard older ones
- Tier 2: Summarize reasoning chains into 500-char max
- Tier 3: Store compressed summaries in long-term memory

## Core Code: search.py
- `search_memory(query, top_k=10) -> list[SearchResult]`: **BM25 keyword
  search** across all memory entries (not embedding similarity)

## Core Code: vector_memory.py (ExperienceVectorMemory)

Reusable-experience vector store used by MemoryManager:
- `store_execution(...)`: persist a validated execution
- `store_experience(...)` / `store_plan_experience(...)`: persist reusable
  experiences / validated plans
- `log_error(...)`: record a failure for later retrieval
- `get_retrieval_context(query)`: inject retrieved experiences into prompt context

## Core Code: user_memory.py
- UserMemory.add(text) -> dict: Save a user fact
- UserMemory.list_all() -> list: List all saved facts
- UserMemory.remove(id) -> bool: Remove a fact by ID
- search_memory(query) -> list: Search saved facts by keyword similarity

## Core Code: chat_storage.py
- ChatStorage.save(name, messages) -> bool: Save conversation
- ChatStorage.load(name) -> list: Load conversation
- ChatStorage.list_chats() -> list: List all saved conversations

OpenTUI `/session` **不是**这张表。默认 TUI 的会话目录权威是 appserver `sessions/list`（UPDATE-01 轨 H）。`chat_storage` 只服务手动 `/save-chat` 与 Ink HTTP `/session`。禁止把 OpenTUI 列表改回 `list_chats()`。

隔夜对话 hydrate 走 `save_session` / `load_session(append_only=True)`（dated `sessions/*/memory/<id>`）。**列表在 `tasks.json` 里不等于 transcript 在。** 换模型、快照、`/goal`/`/loop` 续跑、bash timeout：UPDATE-01 **轨 K U63–U68**；对照 [`../plans/opus5-plan/rxycode/research/2026-09-15-session-durability-snapshots-loop-timeout.md`](../plans/opus5-plan/rxycode/research/2026-09-15-session-durability-snapshots-loop-timeout.md)。

2026-09-23 修复：appserver worker 的 `bootstrap_agent` 现在把**真实 session_id** 传进 `AgentV2` 构造（此前不传，MemoryManager 永远绑兼容桶 `"latest"` → 重启后模型"遗忘"、多窗口互串）。`configure_agent_workspace` 与 `Session.prompt` 改走 `AgentV2.set_session()` 重绑（含 memory 重建），同 session 调用为 no-op。存量会话历史仍在 `"latest"` 桶、不做自动迁移（该桶可能混有多窗口内容）；修复后各 session 桶独立累积。注：`add_interaction` 溢出归档（`_compress_and_store`）维持**未接线**——两条未提交测试锁定"add 时不归档"（归档改写 short_term 前缀形态，违反 B5 append-only/缓存键稳定）；超窗口历史仍由 deque 截断，occupancy 压缩走 core/compaction.py。

## Core Code: manager.py - Task-Level Context Isolation

**`get_task_context(session_id, task_id, parent_id, tree) -> str`**

Returns task-specific context filtered by dependency chain, instead of dumping all short-term memory. Stitched from CrewAI task-level context passing + MetaGPT subscription-filter model.

**Context layers (in order):**
1. **Long-term memory summary** (always included, truncated to 2000 chars)
2. **Ancestor task results** from TaskTree - walks the dependency chain to collect parent/grandparent results
3. **Parent task result** (if parent_id is provided and tree is available, truncated to 1000 chars)
4. **Current task description** from TaskTree - title, description (500 chars), and requirement

This ensures each subtask only receives context relevant to its dependency chain, preventing context pollution from unrelated parallel tasks.

## Code RAG Cache Freshness

The code-context cache is scoped to one top-level Agent run and is also TTL-bound during long runs. It is an `OrderedDict` LRU protected by an `RLock`; insertion, expiry, promotion, eviction, invalidation, and status reads share the same lock. Reaching the entry limit evicts the least recently used query and never disables future retrieval.

Each lookup captures a cache epoch before reading the repository. A successful code-affecting tool increments that epoch and clears the cache. If an older lookup finishes afterward, its epoch no longer matches and its result is not cached. While the debounced durable index refresh is pending or has failed, retrieval bypasses the stored index and chunks current files directly. RAG-disabled managers do not start workers, schedule refreshes, inspect files, or call retrieval.

**`_collect_ancestor_results(tree, task_id) -> str`**: Internal helper that walks up the TaskTree from the given task to collect all ancestor results.

## Core Code: auto_memory.py - LLM Fact Extraction

**`extract_facts_llm(messages, llm) -> list[str]`**

Extracts facts from conversation using an LLM (mem0-style). Falls back to regex extraction if LLM is None or errors out.

- Uses a fixed system prompt that instructs the LLM to respond with JSON: `{"facts": [...], "updates": [...], "deletes": [...]}`
- Supports both sync and async LLM interfaces (`llm.chat()` or `llm()` callable)
- Graceful degradation: any LLM error falls back to `extract_facts()` (regex-based)
- Extracted facts can include new facts, updates to existing facts, and deletions of outdated facts
