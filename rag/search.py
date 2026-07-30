"""Search tool + repo map generator.

Design pattern adapted from aider's repomap.py:
- Symbol graph extraction + simplified PageRank ranking
- Markdown repo map generation with token budget

code_search is registered as a StructuredTool for the agent.
Only the design pattern is ported; implementation is original.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import numpy as np

from .chunker import CodeChunk, chunk_directory
from .embed import get_embeddings, is_embedding_available
from .store import NumpyVectorStore, ScoredChunk


DEFAULT_RETRIEVAL_TOP_K = 6
DEFAULT_RETRIEVAL_MAX_CHARS = 6000
MAX_RETRIEVAL_TOP_K = 20
MAX_RETRIEVAL_CHARS = 20000


# ─── Repo map ───────────────────────────────────────────────────

def _extract_symbols_python(content: str) -> dict[str, list[str]]:
    """Extract defined symbols and referenced names from Python source.

    Returns {"defs": [names], "refs": [names]}.
    """
    defs: list[str] = []
    refs: list[str] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return {"defs": defs, "refs": refs}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append(node.name)
        elif isinstance(node, ast.ClassDef):
            defs.append(node.name)
        elif isinstance(node, ast.Name):
            refs.append(node.id)
        elif isinstance(node, ast.Attribute):
            refs.append(node.attr)

    return {"defs": defs, "refs": refs}


def _extract_symbols_generic(content: str, language: str) -> dict[str, list[str]]:
    """Simple regex-based symbol extraction for non-Python languages."""
    defs: list[str] = []
    # Match common function/class patterns
    patterns = [
        r"(?:def|function|func|fn)\s+(\w+)\s*\(",
        r"class\s+(\w+)",
        r"(?:const|let|var)\s+(\w+)\s*=",
    ]
    for pat in patterns:
        defs.extend(re.findall(pat, content))
    return {"defs": defs, "refs": []}


def _build_symbol_graph(root: Path) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Build a symbol reference graph.

    Returns:
        graph: {symbol: set(referenced_symbols)}
        symbol_to_file: {symbol: file_path}
    """
    root = Path(root)
    if not root.is_dir():
        return {}, {}

    all_defs: set[str] = set()
    file_symbols: dict[str, dict[str, list[str]]] = {}  # path -> {defs, refs}

    # Collect all symbols
    for dirpath, dirnames, filenames in __import__("os").walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in {".git", "__pycache__", "node_modules", ".venv", "venv",
                         ".mypy_cache", ".pytest_cache", "dist", "build"}
        ]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() == ".py":
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                syms = _extract_symbols_python(content)
                file_symbols[str(fpath)] = syms
                all_defs.update(syms["defs"])
            elif fpath.suffix.lower() in (".js", ".ts", ".jsx", ".tsx",
                                           ".java", ".go", ".rs", ".rb"):
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                syms = _extract_symbols_generic(content, fpath.suffix.lower())
                file_symbols[str(fpath)] = syms
                all_defs.update(syms["defs"])

    # Build graph: symbol -> symbols it references
    graph: dict[str, set[str]] = {s: set() for s in all_defs}
    symbol_to_file: dict[str, str] = {}
    for fpath, syms in file_symbols.items():
        for d in syms["defs"]:
            symbol_to_file[d] = fpath
        for r in syms["refs"]:
            for d in syms["defs"]:
                if r != d and r in all_defs:
                    graph[d].add(r)
                    graph[r].add(d)  # undirected

    return graph, symbol_to_file


def _pagerank(
    graph: dict[str, set[str]],
    damping: float = 0.85,
    iterations: int = 30,
    tolerance: float = 1e-6,
) -> dict[str, float]:
    """Compute PageRank scores for a symbol graph.

    Simplified implementation (no networkx dependency).
    """
    nodes = list(graph.keys())
    n = len(nodes)
    if n == 0:
        return {}
    if n == 1:
        return {nodes[0]: 1.0}

    node_idx = {node: i for i, node in enumerate(nodes)}

    # Build adjacency (outgoing links)
    out_links: list[list[int]] = []
    for node in nodes:
        neighbors = list(graph.get(node, set()))
        out_links.append([node_idx[nb] for nb in neighbors if nb in node_idx])

    # Initialize
    scores = np.ones(n) / n

    for _ in range(iterations):
        new_scores = np.zeros(n)
        for i in range(n):
            # Distribute score to neighbors
            if out_links[i]:
                share = scores[i] / len(out_links[i])
                for j in out_links[i]:
                    new_scores[j] += share
            else:
                # Dangling node: distribute evenly
                new_scores += scores[i] / n

        new_scores = damping * new_scores + (1 - damping) / n
        new_scores /= new_scores.sum()  # normalize

        diff = np.abs(new_scores - scores).sum()
        scores = new_scores
        if diff < tolerance:
            break

    return {nodes[i]: float(scores[i]) for i in range(n)}


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def generate_repomap(root: Path, max_tokens: int = 2000) -> str:
    """Generate a repository map as Markdown.

    Uses symbol extraction + PageRank to rank the most important symbols,
    then formats them within a token budget.

    Parameters
    ----------
    root : Path
        Repository root directory.
    max_tokens : int
        Maximum estimated tokens for the output.

    Returns
    -------
    Markdown string with file paths and their key symbols.
    """
    root = Path(root)
    if not root.is_dir():
        return f"[error: directory not found: {root}]"

    graph, symbol_to_file = _build_symbol_graph(root)

    if not graph:
        # Fallback: simple file listing
        lines: list[str] = ["# Repository Map", ""]
        try:
            for item in sorted(root.rglob("*")):
                if item.is_file() and item.suffix in (".py", ".js", ".ts"):
                    rel = item.relative_to(root)
                    lines.append(f"- `{rel}`")
                    if _estimate_tokens("\n".join(lines)) > max_tokens:
                        lines.append("  ... (truncated)")
                        break
        except OSError:
            pass
        return "\n".join(lines) if len(lines) > 2 else "[no source files found]"

    # Compute PageRank
    scores = _pagerank(graph)

    # Group symbols by file
    file_symbols: dict[str, list[tuple[str, float]]] = {}
    for symbol, score in scores.items():
        fpath = symbol_to_file.get(symbol, "?")
        file_symbols.setdefault(fpath, []).append((symbol, score))

    # Sort files by their max symbol score
    file_max_score = {
        f: max((s for _, s in syms), default=0.0)
        for f, syms in file_symbols.items()
    }
    sorted_files = sorted(file_symbols.keys(), key=lambda f: -file_max_score[f])

    # Build markdown within token budget
    lines: list[str] = ["# Repository Map", ""]
    budget = max_tokens - _estimate_tokens("\n".join(lines))

    for fpath in sorted_files:
        syms = sorted(file_symbols[fpath], key=lambda x: -x[1])
        # Show top symbols per file
        sym_names = [name for name, _ in syms[:8]]
        try:
            rel = str(Path(fpath).relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = fpath
        entry = f"- `{rel}`: {', '.join(sym_names)}"
        entry_tokens = _estimate_tokens(entry)
        if budget - entry_tokens < 0:
            lines.append("  ... (truncated)")
            break
        lines.append(entry)
        budget -= entry_tokens + 1  # +1 for newline

    return "\n".join(lines)


# ─── Code search ────────────────────────────────────────────────

def _format_search_results(results: list[ScoredChunk], max_preview: int = 200) -> str:
    """Format search results into a readable string."""
    if not results:
        return "[no results found]"

    parts: list[str] = []
    for i, r in enumerate(results, 1):
        c = r.chunk
        # Truncate content preview
        preview = c.content.strip()
        if len(preview) > max_preview:
            preview = preview[:max_preview] + " ..."

        parts.append(
            f"[{i}] {c.path}:{c.start_line}-{c.end_line}"
            f" ({c.language}, symbol: {c.symbol_name}, score: {r.score:.3f})\n"
            f"    {preview}"
        )
    return "\n\n".join(parts)


def _format_bounded_results(
    results: list[ScoredChunk], max_chars: int
) -> str:
    """Format results while enforcing a hard character ceiling."""
    text = _format_search_results(results, max_preview=max_chars)
    if len(text) <= max_chars:
        return text
    marker = " ... [truncated]"
    if max_chars <= len(marker):
        return text[:max_chars]
    return text[: max_chars - len(marker)].rstrip() + marker


def _keyword_results(
    query: str,
    chunks: list[CodeChunk],
    top_k: int,
) -> list[ScoredChunk]:
    query_words = set(re.findall(r"\w+", query.lower()))
    if not query_words:
        return []

    scored: list[tuple[CodeChunk, float]] = []
    for chunk in chunks:
        content_lower = chunk.content.lower()
        matches = sum(1 for word in query_words if word in content_lower)
        if matches > 0:
            score = matches / (len(content_lower) / 100 + 1)
            scored.append((chunk, score))

    scored.sort(key=lambda item: -item[1])
    return [
        ScoredChunk(chunk=chunk, score=score)
        for chunk, score in scored[:top_k]
    ]


def retrieve_context(
    query: str,
    *,
    root: Path | None = None,
    top_k: int = DEFAULT_RETRIEVAL_TOP_K,
    max_chars: int = DEFAULT_RETRIEVAL_MAX_CHARS,
    allow_network: bool = False,
    prefer_live_files: bool = False,
) -> str:
    """Return bounded code context for planner/executor prompts.

    Retrieval is deliberately offline by default: it ranks indexed chunks (or
    freshly chunked local files) with keyword matching and never consults the
    embedding configuration or API. Callers may explicitly opt into vector
    query embedding with ``allow_network=True``. ``prefer_live_files`` is used
    after a mutating tool succeeds: it bypasses the durable index until the
    debounced incremental refresh has caught up.
    """
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    effective_top_k = min(int(top_k), MAX_RETRIEVAL_TOP_K)
    effective_max_chars = min(int(max_chars), MAX_RETRIEVAL_CHARS)

    if root is None:
        from .index import _get_project_root

        root = _get_project_root()
    if root is None:
        return "[no project found]"[:effective_max_chars]
    root = Path(root)
    if not root.is_dir():
        return "[no project found]"[:effective_max_chars]

    store = NumpyVectorStore(root)
    results: list[ScoredChunk] = []
    if (
        not prefer_live_files
        and allow_network
        and store.size > 0
        and (store.get_manifest() or {}).get("embedding_mode") == "real"
        and is_embedding_available()
    ):
        try:
            query_vec = get_embeddings([query])
            if (
                query_vec.ndim == 2
                and query_vec.shape[0] == 1
                and query_vec.shape[1] == store.vector_dimension
            ):
                results = store.search(query_vec[0], top_k=effective_top_k)
        except Exception:
            results = []

    if not results:
        chunks = (
            chunk_directory(root)
            if prefer_live_files or store.size == 0
            else list(store._chunks)
        )
        results = _keyword_results(query, chunks, effective_top_k)
    return _format_bounded_results(results, effective_max_chars)


def code_search(query: str, top_k: int = 8) -> str:
    """Search the codebase for code relevant to *query*.

    Uses vector similarity search if embeddings are available,
    otherwise falls back to keyword matching.

    Parameters
    ----------
    query : str
        Natural language search query.
    top_k : int
        Maximum number of results to return.

    Returns
    -------
    Formatted string with file paths, line numbers, and code snippets.
    """
    # Try vector search first
    if is_embedding_available():
        try:
            return _vector_search(query, top_k)
        except Exception:
            pass

    # Fallback: keyword search on chunks
    return _keyword_search(query, top_k)


def _vector_search(query: str, top_k: int) -> str:
    """Perform vector similarity search."""
    from .index import _get_store_for_cwd

    store = _get_store_for_cwd()
    if store is None or store.size == 0:
        return _keyword_search(query, top_k)

    query_vec = get_embeddings([query])
    if query_vec.size == 0:
        return _keyword_search(query, top_k)

    results = store.search(query_vec[0], top_k=top_k)
    return _format_search_results(results)


def _keyword_search(query: str, top_k: int) -> str:
    """Fallback keyword-based search on chunk content."""
    from .index import _get_store_for_cwd, _get_project_root

    root = _get_project_root()
    if root is None:
        return "[no project indexed]"

    # Try to get chunks from store first
    store = _get_store_for_cwd()
    chunks: list[CodeChunk] = []
    if store is not None and store.size > 0:
        # Access internal chunks list
        chunks = list(store._chunks)
    else:
        chunks = chunk_directory(root)

    if not chunks:
        return "[no code chunks found]"

    results = _keyword_results(query, chunks, top_k)
    return _format_search_results(results)


# ─── Tool registration ─────────────────────────────────────────

def _register_code_search_tool() -> None:
    """Register code_search as a StructuredTool in the global registry."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    class CodeSearchInput(BaseModel):
        query: str = Field(description="Natural language search query for code")
        top_k: int = Field(default=8, description="Maximum number of results to return")

    tool = StructuredTool.from_function(
        func=code_search,
        name="code_search",
        description=(
            "Search the codebase for code relevant to a natural language query. "
            "Returns file paths, line numbers, and code snippets. "
            "Uses vector similarity search when embeddings are available, "
            "falls back to keyword matching otherwise."
        ),
        args_schema=CodeSearchInput,
    )

    # Use absolute import (relative import ..tools.registry fails in some contexts)
    import importlib
    tools_mod = importlib.import_module("RxyCode.RxyCode1_1_0.tools.registry")
    tools_mod.registry.register(tool, risk="read")  # code_search is read-only


# Auto-register on import (best-effort)
try:
    _register_code_search_tool()
except Exception:
    pass
