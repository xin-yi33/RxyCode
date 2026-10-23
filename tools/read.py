"""Read tool - read text files and extract text from binary documents.

Ordinary text files are returned with line numbers exactly as before. Files that
are really binary containers get a plain-text extraction instead of UTF-8
mojibake: .docx/.xlsx/.pptx (OOXML), .odt/.ods/.odp (ODF) via the standard
library, and a clear actionable message for formats whose extractor is not
installed (PDF, legacy .doc/.xls/.ppt, RTF, archives, images).
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import resolve_session_path
from .document_text import (
    DocumentExtractionError,
    detect_binary_kind,
    extract_document_text,
    guidance_for_kind,
    is_utf16_with_bom,
    looks_binary,
)

#: Enough bytes to recognise every magic signature we support, plus a NUL sniff.
_PREFIX_BYTES = 8192


class ReadInput(BaseModel):
    filePath: str = Field(description="Absolute or session-relative file path")
    offset: int = Field(default=1, description="Starting line number (1-indexed)")
    limit: int = Field(default=800, description="Max lines to read (default 800; use offset to page through larger files)")


def _format_numbered(text: str, offset: int, limit: int) -> str:
    all_lines = text.splitlines()
    start = max(0, offset - 1)
    end = min(len(all_lines), start + limit)
    selected = all_lines[start:end]
    result = []
    for i, line in enumerate(selected, start=start + 1):
        result.append(f"{i}: {line.rstrip()}")
    return "\n".join(result)


def _read_prefix(path: Path) -> bytes:
    try:
        with open(path, "rb") as stream:
            return stream.read(_PREFIX_BYTES)
    except OSError:
        return b""


def _document_result(path: Path, offset: int, limit: int) -> str:
    """Return the read result for a recognised binary container."""
    kind = detect_binary_kind(path, _read_prefix(path)) or "binary"
    try:
        text, truncated = extract_document_text(path, kind)
    except DocumentExtractionError as exc:
        return str(exc)
    header = f"[extracted text of {path.name} ({kind})"
    if truncated:
        header += ", truncated at the extraction cap; page with offset"
    header += "]"
    if not text.strip():
        return f"{header}\n[the document was recognised but contains no extractable text]"
    body = _format_numbered(text, offset, limit)
    return f"{header}\n{body}" if body else header


def _binary_result(path: Path, prefix: bytes) -> str:
    """Actionable message for binary bytes without a known document kind."""
    size = 0
    try:
        size = path.stat().st_size
    except OSError:
        pass
    hint = ""
    if prefix[:4] in {b"\x7fELF", b"MZ\x90\x00"}:
        hint = " It looks like an executable, which is never document text."
    elif b"SQLite format 3" in prefix:
        hint = " It is a SQLite database; query it with bash and the sqlite3 module instead."
    return guidance_for_kind("binary", path).replace(
        "[error: cannot read " + path.name + " as text: binary file "
        "(unknown format) with no text extractor available.]",
        "[error: cannot read " + path.name + " as text: binary file "
        "(" + str(size) + " bytes) with no text extractor available." + hint + "]",
    )


def read_file(filePath: str, offset: int = 1, limit: int = 800) -> str:
    if any(ch in filePath for ch in ("*", "?", "[")):
        return (
            "[error: read 不支持通配符路径；请改用 glob 或 ls 工具定位文件后再 read 具体路径]"
        )
    p = resolve_session_path(filePath)
    if not p.exists():
        return f"[error: path not found: {filePath}]"
    if p.is_dir():
        return (
            f"[error: '{filePath}' 是目录，read 仅用于文件；请改用 ls 或 glob]"
        )

    prefix = _read_prefix(p)
    if is_utf16_with_bom(prefix):
        try:
            text = p.read_bytes().decode("utf-16", errors="replace")
        except OSError as exc:
            return f"[error reading file: {exc}]"
        return _format_numbered(text, offset, limit)
    if detect_binary_kind(p, prefix) is not None:
        return _document_result(p, offset, limit)
    if looks_binary(prefix):
        return _binary_result(p, prefix)

    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        start = max(0, offset - 1)
        end = min(len(all_lines), start + limit)
        selected = all_lines[start:end]
        result = []
        for i, line in enumerate(selected, start=start + 1):
            result.append(f"{i}: {line.rstrip()}")
        return "\n".join(result)
    except Exception as e:
        return f"[error reading file: {e}]"


read_tool = StructuredTool.from_function(
    func=read_file,
    name="read",
    description=(
        "Read a file (not a directory). Relative paths use the session working directory. "
        "Returns content with line numbers. Reads at most limit lines (default 800); "
        "for larger files, page through with offset. "
        "Text files return raw lines. Binary documents return extracted plain text: "
        ".docx/.xlsx/.pptx (plus .odt/.ods/.odp) are extracted with the standard library. "
        "Formats without an installed extractor (PDF, legacy .doc/.xls/.ppt, RTF, archives) "
        "return an actionable error instead of mojibake - never guess their content. "
        "Do not pass glob wildcards or directories - use glob/ls instead."
    ),
    args_schema=ReadInput,
)
