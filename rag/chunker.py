"""Code chunker – splits source files into embedding-ready chunks.

Python files are split by AST (functions/classes with metadata).
Other languages use a sliding window (50 lines / 10-line overlap).

Design pattern adapted from mentat's embedding chunker.
"""
from __future__ import annotations

import ast
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


# ─── Constants ──────────────────────────────────────────────────

WINDOW_SIZE = 50
WINDOW_OVERLAP = 10
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB
# Bump whenever chunk boundaries or metadata semantics change. Persisted RAG
# indexes include this value and are rebuilt instead of mixing old/new chunks.
CHUNKER_VERSION = "1"

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp",
    ".pdf", ".zip", ".gz", ".tar", ".tgz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".class", ".jar",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flv",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pyc", ".pyo", ".o", ".a", ".lib",
    ".dat", ".bin", ".db", ".sqlite", ".sqlite3",
}

LANG_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".md": "markdown",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
}


@dataclass
class CodeChunk:
    """A single chunk of source code ready for embedding."""

    path: str
    symbol_name: str
    start_line: int
    end_line: int
    content: str
    language: str
    mtime: float
    hash: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "symbol_name": self.symbol_name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
            "language": self.language,
            "mtime": self.mtime,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CodeChunk:
        return cls(
            path=d["path"],
            symbol_name=d["symbol_name"],
            start_line=d["start_line"],
            end_line=d["end_line"],
            content=d["content"],
            language=d["language"],
            mtime=d["mtime"],
            hash=d["hash"],
        )


@dataclass(frozen=True)
class ScoredChunk:
    """A chunk with a similarity score from vector search."""

    chunk: CodeChunk
    score: float


# ─── .gitignore parsing ─────────────────────────────────────────

def _load_gitignore_patterns(root: Path) -> set[str]:
    """Load patterns from .gitignore at root. Returns a set of raw patterns."""
    patterns: set[str] = set()
    gitignore = root / ".gitignore"
    if gitignore.exists():
        try:
            for line in gitignore.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.add(line)
        except OSError:
            pass
    return patterns


def _is_ignored(rel_path: Path, patterns: set[str]) -> bool:
    """Check if a relative path matches any .gitignore pattern (simplified)."""
    if not patterns:
        return False
    parts = rel_path.parts
    name = rel_path.name
    str_path = str(rel_path).replace("\\", "/")
    for pat in patterns:
        pat_clean = pat.strip("/")
        # Exact directory match
        if pat_clean in parts:
            return True
        # Exact file match
        if pat_clean == name:
            return True
        # Suffix wildcard: *.pyc
        if pat_clean.startswith("*."):
            ext = pat_clean[1:]  # .pyc
            if name.endswith(ext):
                return True
        # Prefix wildcard
        if pat_clean.endswith("/*"):
            prefix_dir = pat_clean[:-2]
            if str_path.startswith(prefix_dir):
                return True
        # Full path match
        if pat_clean == str_path:
            return True
    return False


def _is_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTS:
        return True
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        if b"\x00" in chunk:
            return True
    except (OSError, PermissionError):
        return True
    return False


def _detect_language(path: Path) -> str:
    return LANG_MAP.get(path.suffix.lower(), "text")


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


# ─── Python AST chunker ─────────────────────────────────────────

def _chunk_python(path: Path, content: str, mtime: float) -> list[CodeChunk]:
    """Split a Python file into chunks based on top-level functions and classes."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Fall back to sliding window if parse fails
        return _chunk_window(path, content, mtime, "python")

    lines = content.splitlines(keepends=True)
    chunks: list[CodeChunk] = []
    lang = "python"

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbol = node.name
            start = node.lineno
            # end_lineno is available in Python 3.8+
            end = getattr(node, "end_lineno", start)
            # Ensure end is at least start
            if end < start:
                end = start
            # For classes, also capture nested defs as part of the class chunk
            chunk_lines = lines[start - 1 : end]
            chunk_content = "".join(chunk_lines)
            chunks.append(CodeChunk(
                path=str(path),
                symbol_name=symbol,
                start_line=start,
                end_line=end,
                content=chunk_content,
                language=lang,
                mtime=mtime,
                hash=_hash_content(chunk_content),
            ))

    # Module-level docstring / imports as a "<module>" chunk
    module_end = 0
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            break
        module_end = getattr(node, "end_lineno", node.lineno)
    if module_end > 0:
        preamble = "".join(lines[0:module_end])
        if preamble.strip():
            chunks.insert(0, CodeChunk(
                path=str(path),
                symbol_name="<module>",
                start_line=1,
                end_line=module_end,
                content=preamble,
                language=lang,
                mtime=mtime,
                hash=_hash_content(preamble),
            ))

    # If nothing was extracted (e.g., simple script), take whole file
    if not chunks:
        full = content
        chunks.append(CodeChunk(
            path=str(path),
            symbol_name="<module>",
            start_line=1,
            end_line=len(lines),
            content=full,
            language=lang,
            mtime=mtime,
            hash=_hash_content(full),
        ))

    return chunks


# ─── Sliding-window chunker ─────────────────────────────────────

def _chunk_window(path: Path, content: str, mtime: float, language: str) -> list[CodeChunk]:
    """Split text into overlapping windows."""
    lines = content.splitlines(keepends=True)
    total = len(lines)
    if total == 0:
        return []

    chunks: list[CodeChunk] = []
    step = WINDOW_SIZE - WINDOW_OVERLAP
    if step <= 0:
        step = WINDOW_SIZE

    i = 0
    idx = 0
    while i < total:
        end = min(i + WINDOW_SIZE, total)
        chunk_lines = lines[i:end]
        chunk_content = "".join(chunk_lines)
        symbol = f"chunk_{idx}"
        chunks.append(CodeChunk(
            path=str(path),
            symbol_name=symbol,
            start_line=i + 1,
            end_line=end,
            content=chunk_content,
            language=language,
            mtime=mtime,
            hash=_hash_content(chunk_content),
        ))
        idx += 1
        if end >= total:
            break
        i += step

    return chunks


# ─── Public API ─────────────────────────────────────────────────

def chunk_file(path: Path) -> list[CodeChunk]:
    """Chunk a single file. Returns empty list for binary/oversized/ignored files."""
    path = Path(path)
    if not path.is_file():
        return []

    # Size check
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size > MAX_FILE_SIZE:
        return []
    if size == 0:
        return []

    # Binary check
    if _is_binary(path):
        return []

    # Read content
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, PermissionError):
        return []

    mtime = path.stat().st_mtime
    language = _detect_language(path)

    if language == "python":
        return _chunk_python(path, content, mtime)
    else:
        return _chunk_window(path, content, mtime, language)


def chunk_directory(root: Path) -> list[CodeChunk]:
    """Recursively chunk all source files under *root*.

    Skips files listed in ``root/.gitignore``, binary files, and files >1 MB.
    """
    root = Path(root)
    if not root.is_dir():
        return []

    patterns = _load_gitignore_patterns(root)
    all_chunks: list[CodeChunk] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip common noise directories
        dirnames[:] = [
            d for d in dirnames
            if d not in {".git", "__pycache__", "node_modules", ".venv", "venv",
                         ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
                         ".egg-info"}
        ]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            rel = fpath.relative_to(root)
            if _is_ignored(rel, patterns):
                continue
            chunks = chunk_file(fpath)
            all_chunks.extend(chunks)

    return all_chunks
