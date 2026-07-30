import re
import math
import asyncio
from pathlib import Path
from typing import Literal
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


MemoryScope = Literal["user", "sessions", "global"]
_SCOPE_PATHS = {
    "user": Path("user"),
    "sessions": Path("sessions"),
    "global": Path("projects") / "global",
}
_SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class MemoryInput(BaseModel):
    operation: str = Field(default="search", description="Operation: search, add, list, or remove")
    query: str = Field(default="", description="Search query (keywords) or text to add")
    scope: MemoryScope = Field(
        default="user", description="Scope: user (default), sessions, or global"
    )
    scope_id: str = Field(default="", description="Scope id filter")
    limit: int = Field(default=10, description="Max results")


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_\-]+", text.lower())


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], avg_dl: float, N: int, df: dict) -> float:
    score = 0.0
    dl = len(doc_tokens)
    doc_freqs = {}
    for t in doc_tokens:
        doc_freqs[t] = doc_freqs.get(t, 0) + 1
    for qt in query_tokens:
        if qt not in df:
            continue
        f = doc_freqs.get(qt, 0)
        idf = math.log((N - df[qt] + 0.5) / (df[qt] + 0.5) + 1)
        tf = (f * 2.0) / (f + 1.0 + 0.5 * dl / avg_dl) if avg_dl > 0 else 0
        score += idf * tf
    return score


def memory_operation(
    operation: str = "search",
    query: str = "",
    scope: MemoryScope = "user",
    scope_id: str = "",
    limit: int = 10,
) -> str:
    """Memory tool supporting search, add, list, and remove operations."""
    if operation == "add":
        if not query:
            return "[error: query is required for add operation]"
        from ..memory.user_memory import UserMemory
        um = UserMemory()
        # Deduplicate: check if same text already exists
        existing = um.list_all()
        for e in existing:
            if e.get("text", "").strip().lower() == query.strip().lower():
                return f"[already exists: memory #{e['id']}]"
        entry = um.add(query)
        return f"[saved: memory #{entry['id']}]"

    elif operation == "list":
        from ..memory.user_memory import UserMemory
        um = UserMemory()
        entries = um.list_all()
        if not entries:
            return "[no memories saved]"
        lines = []
        for e in entries[-limit:]:
            lines.append(f"[{e['id']}] {e.get('text', '')[:80]}")
        return "\n".join(lines)

    elif operation == "remove":
        if not query:
            return "[error: query is required for remove operation (use memory ID)]"
        try:
            entry_id = int(query)
        except ValueError:
            return "[error: query must be a numeric memory ID]"
        from ..memory.user_memory import UserMemory
        um = UserMemory()
        if um.remove(entry_id):
            return f"[removed: memory #{entry_id}]"
        return f"[error: memory #{entry_id} not found]"

    elif operation == "search":
        if not query:
            return "[error: query is required for search operation]"
        return _search_memory(query, scope, scope_id, limit)

    else:
        return f"[error: unknown operation '{operation}']"


async def memory_operation_async(
    operation: str = "search",
    query: str = "",
    scope: MemoryScope = "user",
    scope_id: str = "",
    limit: int = 10,
) -> str:
    await asyncio.sleep(0)
    return memory_operation(operation, query, scope, scope_id, limit)


def _resolve_search_root(scope: str, scope_id: str) -> Path:
    from ..config.settings import get_data_dir

    if scope not in _SCOPE_PATHS:
        raise ValueError("scope must be one of: user, sessions, global")
    if scope_id and (
        not _SCOPE_ID_RE.fullmatch(scope_id) or scope_id in {".", ".."}
    ):
        raise ValueError(
            "scope_id must be a single 1-64 character identifier using "
            "letters, numbers, '.', '_' or '-'"
        )

    memory_root = (get_data_dir() / "memory").resolve()
    scope_root = (memory_root / _SCOPE_PATHS[scope]).resolve()
    base = (scope_root / scope_id).resolve() if scope_id else scope_root
    if not scope_root.is_relative_to(memory_root) or not base.is_relative_to(scope_root):
        raise ValueError("memory search path escapes its allowed scope")
    return base


def _search_memory(
    query: str,
    scope: MemoryScope = "user",
    scope_id: str = "",
    limit: int = 10,
) -> str:
    try:
        base = _resolve_search_root(scope, scope_id)
    except (OSError, ValueError) as exc:
        return f"[error: invalid memory scope: {exc}]"

    if not base.exists():
        return f"[no memory files found in {base}]"

    md_files = []
    for path in base.rglob("*.md"):
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_relative_to(base):
            md_files.append(resolved)
    if not md_files:
        return "[no memory files found]"

    query_tokens = _tokenize(query)
    docs = []
    for fp in md_files:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
            docs.append((str(fp), text, _tokenize(text)))
        except Exception:
            continue

    if not docs:
        return "[no readable memory files]"

    N = len(docs)
    df = {}
    for _, _, dtokens in docs:
        seen = set(dtokens)
        for t in seen:
            df[t] = df.get(t, 0) + 1

    avg_dl = sum(len(d[2]) for d in docs) / N if N > 0 else 1

    scored = []
    for path, text, dtokens in docs:
        score = _bm25_score(query_tokens, dtokens, avg_dl, N, df)
        if score > 0:
            scored.append((score, path, text))
    scored.sort(key=lambda x: -x[0])

    if not scored:
        return "[no matching memory entries]"

    lines = []
    for score, path, text in scored[:limit]:
        snippet = text.strip()[:200].replace("\n", " ")
        lines.append(f"[{score:.2f}] {path}\n  {snippet}")
    return "\n\n".join(lines)


memory_tool = StructuredTool(
    name="memory",
    description="Manage persistent memory. Operations: search (find memories), add (save new memory), list (show all memories), remove (delete by ID). Use 'add' to remember user preferences, names, facts.",
    func=memory_operation,
    coroutine=memory_operation_async,
    args_schema=MemoryInput,
)
