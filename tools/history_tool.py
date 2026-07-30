import math
import re
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class HistoryInput(BaseModel):
    operation: str = Field(default="search", description="Operation: search or around")
    query: str = Field(default="", description="Search query for search operation")
    limit: int = Field(default=10, description="Max results")


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_\-]+", text.lower())


def _bm25(query_tokens: list[str], doc_tokens: list[str], avg_dl: float, N: int, df: dict) -> float:
    score = 0.0
    dl = len(doc_tokens)
    freqs = {}
    for t in doc_tokens:
        freqs[t] = freqs.get(t, 0) + 1
    for qt in query_tokens:
        if qt not in df:
            continue
        f = freqs.get(qt, 0)
        idf = math.log((N - df[qt] + 0.5) / (df[qt] + 0.5) + 1)
        tf = (f * 2.0) / (f + 1.0 + 0.5 * dl / avg_dl) if avg_dl > 0 else 0
        score += idf * tf
    return score


def _history_markdown_files() -> list[Path]:
    """Return global memories plus only the active session's memories."""
    from ..config.settings import get_data_dir
    from ..core.session_runtime import current_session_id

    data_dir = get_data_dir()
    memory_dir = data_dir / "memory"
    session_id = current_session_id()
    dated_session_roots = sorted(
        (data_dir / "sessions").glob(f"*/memory/{session_id}"),
        key=lambda item: item.parent.parent.name,
        reverse=True,
    )
    roots = (
        memory_dir / "user",
        memory_dir / "projects" / "global",
        memory_dir / "sessions" / session_id,
        *dated_session_roots,
    )
    return sorted(
        path
        for root in roots
        if root.exists()
        for path in root.rglob("*.md")
        if path.is_file()
    )


def search_history(operation: str = "search", query: str = "", limit: int = 10) -> str:
    from ..config.settings import get_data_dir

    base = get_data_dir() / "memory"
    if not base.exists():
        return "[error: history directory not found]"

    md_files = _history_markdown_files()
    if not md_files:
        return "[no history files found]"

    if operation == "around":
        return f"[around operation: found {len(md_files)} files, use search with a query to find specific content]"

    if operation != "search":
        return f"[error: unknown operation '{operation}']"
    if not query:
        return "[error: query is required for search]"

    query_tokens = _tokenize(query)
    docs = []
    for fp in md_files:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
            docs.append((str(fp), text, _tokenize(text)))
        except Exception:
            continue

    if not docs:
        return "[no readable files]"

    N = len(docs)
    df = {}
    for _, _, dtokens in docs:
        for t in set(dtokens):
            df[t] = df.get(t, 0) + 1
    avg_dl = sum(len(d[2]) for d in docs) / N

    scored = []
    for path, text, dtokens in docs:
        score = _bm25(query_tokens, dtokens, avg_dl, N, df)
        if score > 0:
            scored.append((score, path, text))
    scored.sort(key=lambda x: -x[0])

    if not scored:
        return "[no matching history entries]"

    lines = []
    for score, path, text in scored[:limit]:
        snippet = text.strip()[:200].replace("\n", " ")
        lines.append(f"[{score:.2f}] {path}\n  {snippet}")
    return "\n\n".join(lines)


history_tool = StructuredTool(
    name="history",
    description="Search conversation history files. Supports search and around operations.",
    func=search_history,
    args_schema=HistoryInput,
)
