"""Pure artifact → sandboxed-HTML converters for preview jobs.

Contract (UI-2026-10-22 §07 API-PREVIEW-01/02, extended so
``所有类型的文件都可以预览``):

- Every function here is pure: bytes in, a complete UTF-8 HTML document out.
  No S3, no database, no temp files — the preview service owns storage.
- The produced document is self-contained: inline ``<style>`` only, images as
  ``data:image/png;base64,...``, **no** external resource loads, so it fits the
  ``Content-Security-Policy`` the content endpoint serves
  (``default-src 'none'; style-src 'unsafe-inline'; img-src data:``).
- All artifact-controlled text is HTML-escaped before it lands in the page; a
  document's bytes are never injected raw.
- Conversion is bounded (page/row/member/byte caps). Over-cap output is
  truncated with an honest note instead of an unbounded response.
- Unparsable Office/archive containers degrade to the binary metadata page —
  every artifact still gets *some* preview. A PDF that cannot be rendered
  raises :class:`ConverterError` so the service records an honest failed job
  instead of hanging.

Kind dispatch lives in :func:`convert`; ``image``/``media`` are streamed as
original bytes by the service and therefore must not be converted here.
"""

from __future__ import annotations

import base64
import datetime
import gzip
import hashlib
import html
import io
import math
import posixpath
import re
import tarfile
import zipfile
import zlib
from typing import Iterable
from xml.etree import ElementTree

from rxycode_server.previews import kinds

try:  # pragma: no cover - lxml is pinned in infra/docker/requirements-web.txt
    from lxml import etree as _lxml_etree
except ImportError:  # pragma: no cover - exercised in CI (stdlib fallback)
    _lxml_etree = None

__all__ = [
    "ConversionFailed",
    "ConverterError",
    "ConverterUnavailable",
    "NoConversion",
    "convert",
    "convert_archive",
    "convert_binary",
    "convert_office",
    "convert_pdf",
    "convert_text",
]

# ---------------------------------------------------------------------------
# Limits. Everything that reads artifact bytes goes through one of these caps.
# ---------------------------------------------------------------------------

_MAX_HTML_BYTES = 8 * 1024 * 1024
_PDF_MAX_PAGES = 30
_PDF_RENDER_SCALES = (2.0, 1.5, 1.2)
_PDF_MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
#: PNG bytes are base64-encoded (×4/3) into the document, so the raw image
#: budget must leave room for that expansion plus the page shell.
_PDF_IMAGE_BUDGET = int((_PDF_MAX_DOCUMENT_BYTES - 512 * 1024) * 3 // 4)
_PDF_MAX_PAGE_SIDE = 3000.0
_PDF_MAX_PAGE_PIXELS = 4_000_000.0
_PDF_MIN_PAGE_SIDE = 200.0
_OFFICE_MAX_PART_BYTES = 6 * 1024 * 1024
_OFFICE_MAX_BLOCKS = 4000
_XLSX_MAX_SHEETS = 5
_XLSX_MAX_ROWS = 200
_XLSX_MAX_COLS = 30
_XLSX_MAX_SHARED = 100_000
_PPTX_MAX_SLIDES = 50
_PPTX_MAX_LINES = 200
_ODF_MAX_ROWS = 200
_ODF_MAX_COLS = 30
_ARCHIVE_MAX_ENTRIES = 300
_ARCHIVE_MAX_SCAN = 100_000
_GZ_PROBE_BYTES = 4 * 1024 * 1024
_HEX_PREVIEW_BYTES = 4096

_TRUNCATED_NOTE = "内容超过预览上限，后面部分已省略。"
_OFFICE_FALLBACK_NOTE = "无法解析该 Office 文档（可能已损坏或格式不受支持），以下为文件元数据。"
_ARCHIVE_FALLBACK_NOTE = "无法解析该压缩包（可能已损坏），以下为文件元数据。"
_LEGACY_ARCHIVE_NOTE = "7z/rar 需要额外的解包组件，服务端无法列出成员，以下为文件元数据。"

# ---------------------------------------------------------------------------
# Errors — the service turns these into honest ``failed`` jobs, never hangs.
# ---------------------------------------------------------------------------


class ConverterError(Exception):
    """The bytes could not be turned into an honest preview document."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ConverterUnavailable(ConverterError):
    """An optional renderer (pypdfium2) is not installed on this deployment."""


class ConversionFailed(ConverterError):
    """The artifact itself cannot be converted (corrupt, encrypted, empty)."""


class NoConversion(ConverterError):
    """This kind streams original bytes; the service must not convert it."""


class _OfficeFallback(Exception):
    """Internal: an Office container is unreadable — show metadata instead."""


# ---------------------------------------------------------------------------
# Page shell
# ---------------------------------------------------------------------------

_CSS = (
    "body{font:13px/1.55 -apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    "margin:0;padding:16px 18px;color:#1b1b1b;background:#fff}"
    "h1{font-size:16px;margin:0 0 4px;word-break:break-word}"
    "h2{font-size:14px;margin:22px 0 8px;padding-bottom:4px;"
    "border-bottom:1px solid #e6e6e6;word-break:break-word}"
    "h3{font-size:13px;margin:16px 0 6px}"
    ".meta{color:#666;font-size:12px;margin:0 0 12px;word-break:break-word}"
    ".note{background:#fff8e1;border:1px solid #efd68a;padding:8px 10px;"
    "margin:0 0 14px;font-size:12px;border-radius:4px}"
    "p{margin:0 0 8px;white-space:pre-wrap;word-break:break-word}"
    "pre{white-space:pre-wrap;word-break:break-word;font:12px/1.5 ui-monospace,"
    "Consolas,'Courier New',monospace;background:#fafafa;border:1px solid #eee;"
    "padding:10px;margin:0 0 14px;border-radius:4px;overflow-wrap:anywhere}"
    "table{border-collapse:collapse;width:100%;font-size:12px;margin:0 0 14px}"
    "th,td{border:1px solid #ddd;padding:4px 8px;text-align:left;"
    "vertical-align:top;word-break:break-word}"
    "th{background:#f5f5f5;font-weight:600}"
    "td.key{width:110px;color:#555;background:#f7f7f7;font-weight:600}"
    ".page{margin:0 0 14px}"
    ".page img{display:block;width:100%;height:auto;border:1px solid #ddd}"
    ".slide{margin:0 0 18px}"
)


def _escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _document(
    title: str,
    body: str,
    *,
    subtitle: str = "",
    note: str = "",
) -> bytes:
    """Wrap already-escaped body HTML in the self-contained page shell."""
    parts = [
        "<!doctype html><meta charset=utf-8>",
        f"<title>{_escape(title)}</title>",
        f"<style>{_CSS}</style>",
        f"<h1>{_escape(title)}</h1>",
    ]
    if subtitle:
        parts.append(f'<p class="meta">{_escape(subtitle)}</p>')
    if note:
        parts.append(f'<p class="note">{_escape(note)}</p>')
    parts.append(body)
    return "".join(parts).encode("utf-8")


class _Budget:
    """Accumulate HTML fragments until the document byte budget runs out."""

    def __init__(self, limit: int = _MAX_HTML_BYTES) -> None:
        self.limit = limit
        self.truncated = False
        self._parts: list[str] = []
        self._size = 0

    def add(self, fragment: str) -> bool:
        if self.truncated or not fragment:
            return False
        size = len(fragment.encode("utf-8"))
        if self._size + size > self.limit:
            self.truncated = True
            return False
        self._parts.append(fragment)
        self._size += size
        return True

    def html(self) -> str:
        return "".join(self._parts)


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"  # pragma: no cover - loop always returns


def _format_timestamp(epoch: float | int | None) -> str:
    if epoch is None:
        return ""
    try:
        moment = datetime.datetime.fromtimestamp(float(epoch), tz=datetime.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return ""
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def _format_zip_time(date_time) -> str:
    try:
        year, month, day, hour, minute = (int(part) for part in date_time[:5])
    except (TypeError, ValueError):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"


def _table(headers: Iterable[str], rows: Iterable[Iterable[object]]) -> str:
    head = "".join(f"<th>{_escape(cell)}</th>" for cell in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


# ---------------------------------------------------------------------------
# XML helpers (lxml when available — entity-safe; stdlib ElementTree otherwise)
# ---------------------------------------------------------------------------


def _parse_xml(data: bytes):
    if _lxml_etree is not None:
        parser = _lxml_etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            recover=False,
            huge_tree=False,
            remove_comments=True,
            remove_pis=True,
        )
        return _lxml_etree.fromstring(data, parser=parser)
    # stdlib fallback: the Docker web image ships lxml, so this path is only
    # used on minimal installs/CI. Artifact XML is untrusted; the surrounding
    # byte cap bounds the parse and no downstream code executes content.
    return ElementTree.fromstring(data)


def _qualified(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def _iter_elements(node) -> Iterable[object]:
    for element in node.iter():
        if isinstance(element.tag, str):
            yield element


# ---------------------------------------------------------------------------
# Text / frontend_static
# ---------------------------------------------------------------------------


def convert_text(data: bytes, *, filename: str = "", content_type: str = "") -> bytes:
    """Frontend-static non-HTML text: decoded and escaped into a ``<pre>``."""
    text = data.decode("utf-8", errors="replace")
    return _document(filename or "文本预览", f"<pre>{_escape(text)}</pre>")


# ---------------------------------------------------------------------------
# Binary (also the honest fallback for unreadable containers)
# ---------------------------------------------------------------------------


def convert_binary(
    data: bytes,
    *,
    filename: str = "",
    content_type: str = "",
    note: str = "",
) -> bytes:
    """Metadata page: filename, type, size, SHA-256 and a 4 KiB hexdump."""
    size = len(data)
    digest = hashlib.sha256(data).hexdigest()
    title = filename or "文件预览"
    rows = (
        ("文件名", filename or "（未命名）"),
        ("类型", content_type or "application/octet-stream"),
        ("大小", f"{size} 字节（{_human_size(size)}）"),
        ("SHA-256", digest),
    )
    body = [
        "<table><tbody>",
        "".join(
            f'<tr><td class="key">{_escape(key)}</td><td>{_escape(value)}</td></tr>'
            for key, value in rows
        ),
        "</tbody></table>",
    ]
    if size == 0:
        body.append('<p class="meta">文件为空（0 字节）。</p>')
    else:
        chunk = data[:_HEX_PREVIEW_BYTES]
        lines = []
        for offset in range(0, len(chunk), 16):
            block = chunk[offset : offset + 16]
            hex_part = " ".join(f"{byte:02x}" for byte in block).ljust(16 * 3 - 1)
            ascii_part = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in block)
            lines.append(f"{offset:08x}  {hex_part}  |{ascii_part}|")
        hint = ""
        if size > _HEX_PREVIEW_BYTES:
            hint = f"（仅显示前 {_HEX_PREVIEW_BYTES} 字节，共 {size} 字节）"
        body.append(f"<h2>十六进制预览 {hint}</h2><pre>{_escape(chr(10).join(lines))}</pre>")
    return _document(
        title,
        "".join(body),
        subtitle="二进制文件 · 元数据 + 前 4KB 十六进制",
        note=note,
    )


# ---------------------------------------------------------------------------
# Office (OOXML + ODF) — stdlib zipfile, extract text/tables to styled HTML
# ---------------------------------------------------------------------------

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
_DRAW_NS = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"


def _w(local: str) -> str:
    return _qualified(_W_NS, local)


def _s(local: str) -> str:
    return _qualified(_S_NS, local)


def _a(local: str) -> str:
    return _qualified(_A_NS, local)


def _r(local: str) -> str:
    return _qualified(_R_NS, local)


def _p(local: str) -> str:
    return _qualified(_P_NS, local)


def _text(local: str) -> str:
    return _qualified(_TEXT_NS, local)


def _table_ns(local: str) -> str:
    return _qualified(_TABLE_NS, local)


def _office(local: str) -> str:
    return _qualified(_OFFICE_NS, local)


def _draw(local: str) -> str:
    return _qualified(_DRAW_NS, local)


def _read_zip_member(
    bundle: zipfile.ZipFile,
    name: str,
    *,
    limit: int = _OFFICE_MAX_PART_BYTES,
) -> bytes | None:
    """Bounded member read — protects against zip bombs inside Office files."""
    try:
        with bundle.open(name) as handle:
            data = handle.read(limit + 1)
    except KeyError:
        return None
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise _OfficeFallback(f"无法读取 {name}") from exc
    if len(data) > limit:
        raise _OfficeFallback("文档内部内容过大，无法在预览中完整解析")
    return data


def _detect_office_family(names: set[str], filename: str, content_type: str) -> str | None:
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    if name.endswith((".docx", ".docm")) or "wordprocessingml" in ctype:
        return "docx"
    if name.endswith((".xlsx", ".xlsm")) or "spreadsheetml" in ctype:
        return "xlsx"
    if name.endswith((".pptx", ".pptm")) or "presentationml" in ctype:
        return "pptx"
    if name.endswith((".odt", ".ods", ".odp")) or "opendocument" in ctype:
        return "odf"
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    if "ppt/presentation.xml" in names:
        return "pptx"
    if "content.xml" in names:
        return "odf"
    return None


def convert_office(data: bytes, *, filename: str = "", content_type: str = "") -> bytes:
    """docx/xlsx/pptx/odt/ods/odp → styled HTML; unreadable → metadata page."""
    if not data:
        return convert_binary(data, filename=filename, content_type=content_type)
    try:
        bundle = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        return convert_binary(
            data, filename=filename, content_type=content_type, note=_OFFICE_FALLBACK_NOTE
        )
    try:
        with bundle:
            names = set(bundle.namelist())
            family = _detect_office_family(names, filename, content_type)
            if family == "docx":
                return _convert_docx(bundle, filename)
            if family == "xlsx":
                return _convert_xlsx(bundle, filename)
            if family == "pptx":
                return _convert_pptx(bundle, filename)
            if family == "odf":
                return _convert_odf(bundle, filename)
            raise _OfficeFallback("不是可解析的 OOXML/ODF 容器")
    except _OfficeFallback as fallback:
        note = f"{fallback}，以下为文件元数据。"
        return convert_binary(data, filename=filename, content_type=content_type, note=note)
    except Exception:
        # Corrupt containers must never raise out of the converter.
        return convert_binary(
            data, filename=filename, content_type=content_type, note=_OFFICE_FALLBACK_NOTE
        )


# -- docx ------------------------------------------------------------------


def _element_text(element, *text_tags: str) -> str:
    """Concatenate direct ``text_tags`` descendants (docx/pptx style)."""
    pieces: list[str] = []
    for node in _iter_elements(element):
        if node.tag in text_tags:
            pieces.append(node.text or "")
        elif node.tag == _w("tab"):
            pieces.append("\t")
        elif node.tag in (_w("br"), _w("cr")):
            pieces.append("\n")
    return "".join(pieces)


def _docx_style(paragraph) -> str:
    properties = paragraph.find(_w("pPr"))
    if properties is None:
        return ""
    style = properties.find(_w("pStyle"))
    if style is None:
        return ""
    return (style.get(_w("val")) or "").strip()


def _docx_heading_tag(style: str) -> str | None:
    lowered = style.lower()
    if lowered in {"title", "heading1", "heading 1"}:
        return "h2"
    match = re.fullmatch(r"heading\s*(\d+)", lowered)
    if match:
        level = int(match.group(1))
        return "h2" if level <= 1 else ("h3" if level == 2 else "h4")
    return None


def _docx_paragraph(paragraph) -> str:
    text = _element_text(paragraph, _w("t")).strip()
    if not text:
        return ""
    tag = _docx_heading_tag(_docx_style(paragraph)) or "p"
    marker = ""
    if tag == "p":
        properties = paragraph.find(_w("pPr"))
        if properties is not None and properties.find(_w("numPr")) is not None:
            marker = "• "
    return f"<{tag}>{marker}{_escape(text)}</{tag}>"


def _docx_table(table) -> str:
    rows: list[list[str]] = []
    for row in table.findall(_w("tr")):
        if len(rows) >= _ODF_MAX_ROWS:
            break
        cells: list[str] = []
        for cell in row.findall(_w("tc")):
            if len(cells) >= _ODF_MAX_COLS:
                break
            paragraphs = [
                _element_text(paragraph, _w("t")).strip() for paragraph in cell.findall(_w("p"))
            ]
            cells.append("\n".join(part for part in paragraphs if part))
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    header = rows[0]
    body = rows[1:]
    head_html = "".join(f"<th>{_escape(cell)}</th>" for cell in header)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>" for row in body
    )
    return f"<table><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>"


def _convert_docx(bundle: zipfile.ZipFile, filename: str) -> bytes:
    xml = _read_zip_member(bundle, "word/document.xml")
    if xml is None:
        raise _OfficeFallback("缺少 word/document.xml")
    root = _parse_xml(xml)
    body = next((node for node in _iter_elements(root) if node.tag == _w("body")), None)
    if body is None:
        raise _OfficeFallback("文档缺少正文")
    budget = _Budget()
    blocks = 0
    for child in body:
        if not isinstance(child.tag, str):
            continue
        if child.tag == _w("p"):
            fragment = _docx_paragraph(child)
        elif child.tag == _w("tbl"):
            fragment = _docx_table(child)
        else:
            continue
        if not fragment:
            continue
        if not budget.add(fragment):
            break
        blocks += 1
        if blocks >= _OFFICE_MAX_BLOCKS:
            budget.truncated = True
            break
    if budget.truncated:
        return _document(
            filename or "Word 文档",
            budget.html(),
            subtitle="Word 文档 · 段落与表格提取",
            note=_TRUNCATED_NOTE,
        )
    return _document(
        filename or "Word 文档",
        budget.html(),
        subtitle="Word 文档 · 段落与表格提取",
        note="" if budget.html() else "文档没有可提取的文本内容。",
    )


# -- xlsx ------------------------------------------------------------------


def _xlsx_shared_strings(bundle: zipfile.ZipFile) -> list[str]:
    xml = _read_zip_member(bundle, "xl/sharedStrings.xml")
    if xml is None:
        return []
    root = _parse_xml(xml)
    strings: list[str] = []
    for item in _iter_elements(root):
        if item.tag != _s("si"):
            continue
        strings.append(
            "".join(node.text or "" for node in _iter_elements(item) if node.tag == _s("t"))
        )
        if len(strings) >= _XLSX_MAX_SHARED:
            break
    return strings


def _resolve_part(base_dir: str, target: str) -> str:
    cleaned = (target or "").replace("\\", "/").strip()
    if not cleaned:
        return ""
    if cleaned.startswith("/"):
        return posixpath.normpath(cleaned.lstrip("/"))
    return posixpath.normpath(posixpath.join(base_dir, cleaned))


def _relationship_targets(
    bundle: zipfile.ZipFile, rels_member: str, base_dir: str
) -> dict[str, str]:
    xml = _read_zip_member(bundle, rels_member)
    if xml is None:
        return {}
    root = _parse_xml(xml)
    mapping: dict[str, str] = {}
    for node in _iter_elements(root):
        if not isinstance(node.tag, str) or not node.tag.endswith("Relationship"):
            continue
        rel_id = node.get("Id")
        target = node.get("Target")
        if rel_id and target:
            mapping[rel_id] = _resolve_part(base_dir, target)
    return mapping


def _xlsx_sheet_sources(bundle: zipfile.ZipFile, names: set[str]) -> list[tuple[str, str]]:
    sheets: list[tuple[str, str]] = []
    workbook = _read_zip_member(bundle, "xl/workbook.xml")
    if workbook is not None:
        root = _parse_xml(workbook)
        targets = _relationship_targets(bundle, "xl/_rels/workbook.xml.rels", "xl")
        for node in _iter_elements(root):
            if node.tag != _s("sheet"):
                continue
            title = node.get("name") or "工作表"
            rid = node.get(_r("id"))
            member = targets.get(rid or "")
            if member:
                sheets.append((title, member))
    if sheets:
        return sheets
    fallback: list[tuple[str, str]] = []
    for pattern in (
        r"^xl/worksheets/sheet(\d+)\.xml$",
        r"^xl/worksheets/sheet(\d+)[^/]*\.xml$",
    ):
        candidates = []
        for name in names:
            match = re.match(pattern, name)
            if match:
                candidates.append((int(match.group(1)), name))
        if candidates:
            for index, member in sorted(candidates):
                fallback.append((f"Sheet {index}", member))
            break
    return fallback


def _column_index(reference: str) -> int:
    letters = re.match(r"([A-Z]+)", reference.upper())
    if not letters:
        return 0
    index = 0
    for letter in letters.group(1):
        index = index * 26 + (ord(letter) - 64)
    return index - 1


def _xlsx_cell_value(cell, shared: list[str]) -> str:
    cell_type = cell.get("t") or "n"
    if cell_type == "inlineStr":
        inline = cell.find(_s("is"))
        if inline is None:
            return ""
        return "".join(node.text or "" for node in _iter_elements(inline) if node.tag == _s("t"))
    value_node = cell.find(_s("v"))
    raw = (value_node.text or "") if value_node is not None else ""
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return raw
    if cell_type == "b":
        return "TRUE" if raw.strip() in {"1", "true", "TRUE"} else "FALSE"
    return raw


def _xlsx_sheet_table(xml: bytes, shared: list[str]) -> tuple[str, bool]:
    root = _parse_xml(xml)
    sheet_data = root.find(_s("sheetData"))
    if sheet_data is None:
        return "", False
    rows_html: list[str] = []
    truncated = False
    for row in sheet_data.findall(_s("row")):
        if len(rows_html) >= _XLSX_MAX_ROWS:
            truncated = True
            break
        cells_html: list[str] = []
        column = 0
        for cell in row.findall(_s("c")):
            if column >= _XLSX_MAX_COLS:
                truncated = True
                break
            reference = cell.get("r") or ""
            target = _column_index(reference) if reference else column
            if 0 <= target < _XLSX_MAX_COLS:
                while column < target:
                    cells_html.append("<td></td>")
                    column += 1
            cells_html.append(f"<td>{_escape(_xlsx_cell_value(cell, shared))}</td>")
            column += 1
        if cells_html:
            rows_html.append("<tr>" + "".join(cells_html) + "</tr>")
    if not rows_html:
        return '<p class="meta">（空工作表）</p>', False
    return f"<table><tbody>{''.join(rows_html)}</tbody></table>", truncated


def _convert_xlsx(bundle: zipfile.ZipFile, filename: str) -> bytes:
    names = set(bundle.namelist())
    shared = _xlsx_shared_strings(bundle)
    sheets = _xlsx_sheet_sources(bundle, names)
    if not sheets:
        raise _OfficeFallback("工作簿不含工作表")
    budget = _Budget()
    shown = 0
    rows_truncated = False
    for title, member in sheets[:_XLSX_MAX_SHEETS]:
        xml = _read_zip_member(bundle, member)
        if xml is None:
            continue
        table, sheet_rows_truncated = _xlsx_sheet_table(xml, shared)
        rows_truncated = rows_truncated or sheet_rows_truncated
        if not budget.add(f"<h2>{_escape(title)}</h2>"):
            break
        if not budget.add(table):
            break
        shown += 1
        if budget.truncated:
            break
    notes: list[str] = []
    if budget.truncated:
        notes.append(_TRUNCATED_NOTE)
    elif rows_truncated:
        notes.append(f"工作表内容超过 {_XLSX_MAX_ROWS} 行或 {_XLSX_MAX_COLS} 列，仅显示前面部分。")
    if len(sheets) > _XLSX_MAX_SHEETS:
        notes.append(f"工作簿共 {len(sheets)} 个工作表，仅显示前 {_XLSX_MAX_SHEETS} 个。")
    if not shown:
        notes.append("没有可显示的工作表内容。")
    return _document(
        filename or "Excel 工作簿",
        budget.html(),
        subtitle=f"Excel 工作簿 · {len(sheets)} 个工作表",
        note=" ".join(notes),
    )


# -- pptx ------------------------------------------------------------------


def _pptx_slide_sources(bundle: zipfile.ZipFile, names: set[str]) -> list[tuple[str, int]]:
    ordered: list[tuple[str, int]] = []
    presentation = _read_zip_member(bundle, "ppt/presentation.xml")
    if presentation is not None:
        root = _parse_xml(presentation)
        targets = _relationship_targets(bundle, "ppt/_rels/presentation.xml.rels", "ppt")
        for node in _iter_elements(root):
            if node.tag != _p("sldId"):
                continue
            target = targets.get(node.get(_r("id")) or "")
            if target and target in names:
                ordered.append((target, len(ordered) + 1))
    if ordered:
        return ordered
    candidates: list[tuple[int, str]] = []
    for name in names:
        match = re.match(r"^ppt/slides/slide(\d+)\.xml$", name)
        if match:
            candidates.append((int(match.group(1)), name))
    return [(member, index) for index, member in sorted(candidates)]


def _pptx_slide_lines(xml: bytes) -> list[str]:
    root = _parse_xml(xml)
    lines: list[str] = []
    for paragraph in _iter_elements(root):
        if paragraph.tag != _a("p"):
            continue
        text = "".join(
            node.text or "" for node in _iter_elements(paragraph) if node.tag == _a("t")
        ).strip()
        if text:
            lines.append(text)
        if len(lines) >= _PPTX_MAX_LINES:
            break
    return lines


def _convert_pptx(bundle: zipfile.ZipFile, filename: str) -> bytes:
    names = set(bundle.namelist())
    slides = _pptx_slide_sources(bundle, names)
    if not slides:
        raise _OfficeFallback("演示文稿不含幻灯片")
    budget = _Budget()
    shown = 0
    for member, ordinal in slides[:_PPTX_MAX_SLIDES]:
        xml = _read_zip_member(bundle, member)
        if xml is None:
            continue
        lines = _pptx_slide_lines(xml)
        section = [f'<section class="slide"><h2>第 {ordinal} 张幻灯片</h2>']
        if lines:
            section.extend(f"<p>{_escape(line)}</p>" for line in lines)
        else:
            section.append('<p class="meta">（本页没有可提取的文本）</p>')
        section.append("</section>")
        if not budget.add("".join(section)):
            break
        shown += 1
        if budget.truncated:
            break
    note = ""
    if budget.truncated:
        note = _TRUNCATED_NOTE
    elif len(slides) > _PPTX_MAX_SLIDES:
        note = f"演示文稿共 {len(slides)} 张幻灯片，仅显示前 {_PPTX_MAX_SLIDES} 张。"
    return _document(
        filename or "PowerPoint 演示文稿",
        budget.html(),
        subtitle=f"PowerPoint 演示文稿 · {len(slides)} 张幻灯片",
        note=note if shown else "没有可显示的幻灯片内容。",
    )


# -- ODF (odt/ods/odp) -----------------------------------------------------


def _odf_text(node) -> str:
    """ODF text extraction preserving ``text:s``/``text:tab``/line breaks."""

    pieces: list[str] = []

    def walk(element) -> None:
        tag = element.tag
        if isinstance(tag, str) and tag == _text("s"):
            count = 1
            try:
                count = int(element.get(_text("c")) or "1")
            except (TypeError, ValueError):
                count = 1
            pieces.append(" " * max(1, min(count, 80)))
        elif isinstance(tag, str) and tag == _text("tab"):
            pieces.append("\t")
        elif isinstance(tag, str) and tag in (
            _text("line-break"),
            _text("soft-page-break"),
        ):
            pieces.append("\n")
        elif isinstance(tag, str):
            if element.text:
                pieces.append(element.text)
            for child in element:
                walk(child)
        if element.tail:
            pieces.append(element.tail)

    walk(node)
    return "".join(pieces)


def _odf_cell_text(cell) -> str:
    """Visible cell text; numeric ODS cells keep their value attribute only."""
    text = " ".join(_odf_text(cell).split())
    if text:
        return text
    for attribute in (
        "value",
        "string-value",
        "boolean-value",
        "date-value",
        "time-value",
    ):
        value = cell.get(_office(attribute))
        if value not in (None, ""):
            return value
    return ""


def _odf_table(element) -> str:
    rows_html: list[str] = []
    for row in element.findall(_table_ns("table-row")):
        if len(rows_html) >= _ODF_MAX_ROWS:
            break
        cells_html: list[str] = []
        columns = 0
        for cell in list(row):
            if not isinstance(cell.tag, str) or cell.tag not in (
                _table_ns("table-cell"),
                _table_ns("covered-table-cell"),
            ):
                continue
            if columns >= _ODF_MAX_COLS:
                break
            repeat = 1
            try:
                repeat = int(cell.get(_table_ns("number-columns-repeated")) or "1")
            except (TypeError, ValueError):
                repeat = 1
            repeat = max(1, min(repeat, _ODF_MAX_COLS - columns))
            text = _odf_cell_text(cell)
            if repeat > 1:
                cells_html.append(f'<td colspan="{repeat}">{_escape(text)}</td>')
            else:
                cells_html.append(f"<td>{_escape(text)}</td>")
            columns += repeat
        if cells_html:
            rows_html.append("<tr>" + "".join(cells_html) + "</tr>")
    if not rows_html:
        return ""
    return f"<table><tbody>{''.join(rows_html)}</tbody></table>"


def _convert_odf(bundle: zipfile.ZipFile, filename: str) -> bytes:
    xml = _read_zip_member(bundle, "content.xml")
    if xml is None:
        raise _OfficeFallback("ODF 缺少 content.xml")
    root = _parse_xml(xml)
    body = next((node for node in _iter_elements(root) if node.tag == _office("body")), None)
    if body is None:
        raise _OfficeFallback("ODF 缺少 office:body")
    budget = _Budget()
    slide_number = 0

    def walk(element) -> None:
        nonlocal slide_number
        if budget.truncated:
            return
        tag = element.tag
        if not isinstance(tag, str):
            return
        if tag == _table_ns("table"):
            name = element.get(_table_ns("name"))
            if name:
                budget.add(f"<h2>{_escape(name)}</h2>")
            table_html = _odf_table(element)
            if table_html:
                budget.add(table_html)
            return
        if tag == _draw("page"):
            slide_number += 1
            budget.add(f'<section class="slide"><h2>第 {slide_number} 页</h2></section>')
            for child in element:
                walk(child)
            return
        if tag == _text("h"):
            heading = " ".join(_odf_text(element).split())
            if heading:
                try:
                    level = int(element.get(_text("outline-level")) or "1")
                except (TypeError, ValueError):
                    level = 1
                heading_tag = "h2" if level <= 1 else ("h3" if level == 2 else "h4")
                budget.add(f"<{heading_tag}>{_escape(heading)}</{heading_tag}>")
            return
        if tag == _text("p"):
            text = _odf_text(element).strip()
            if text:
                budget.add(f"<p>{_escape(text)}</p>")
            return
        for child in element:
            walk(child)

    for child in body:
        walk(child)
    note = _TRUNCATED_NOTE if budget.truncated else ""
    return _document(
        filename or "OpenDocument 文档",
        budget.html(),
        subtitle="OpenDocument · 文本与表格提取",
        note=note if budget.html() else "文档没有可提取的文本内容。",
    )


# ---------------------------------------------------------------------------
# Archive (listing only — members are never extracted to disk)
# ---------------------------------------------------------------------------


def _zip_listing(data: bytes, filename: str, content_type: str) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            infos = bundle.infolist()
    except (zipfile.BadZipFile, OSError, NotImplementedError):
        return convert_binary(
            data, filename=filename, content_type=content_type, note=_ARCHIVE_FALLBACK_NOTE
        )
    rows = []
    total_size = 0
    for info in infos:
        total_size += info.file_size
        if len(rows) < _ARCHIVE_MAX_ENTRIES:
            rows.append(
                (
                    info.filename,
                    _human_size(info.file_size),
                    _format_zip_time(info.date_time),
                )
            )
    note = ""
    if len(infos) > _ARCHIVE_MAX_ENTRIES:
        note = f"压缩包共 {len(infos)} 个成员，仅显示前 {_ARCHIVE_MAX_ENTRIES} 个。"
    if not infos:
        note = "压缩包为空。"
    subtitle = f"ZIP 压缩包 · {len(infos)} 个成员 · 解压后约 {_human_size(total_size)}"
    return _document(
        filename or "ZIP 压缩包",
        _table(("成员", "原始大小", "修改时间"), rows),
        subtitle=subtitle,
        note=note,
    )


def _tar_listing(data: bytes, filename: str, content_type: str) -> bytes:
    rows = []
    total = 0
    capped = False
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as bundle:
            for member in bundle:
                total += 1
                if len(rows) < _ARCHIVE_MAX_ENTRIES:
                    rows.append(
                        (
                            member.name,
                            _human_size(member.size),
                            _format_timestamp(member.mtime),
                        )
                    )
                elif total >= _ARCHIVE_MAX_SCAN:
                    capped = True
                    break
    except (tarfile.TarError, OSError, EOFError, ValueError):
        return convert_binary(
            data, filename=filename, content_type=content_type, note=_ARCHIVE_FALLBACK_NOTE
        )
    note = ""
    if total > _ARCHIVE_MAX_ENTRIES:
        note = (
            f"压缩包至少 {total} 个成员，仅显示前 {_ARCHIVE_MAX_ENTRIES} 个。"
            if capped
            else f"压缩包共 {total} 个成员，仅显示前 {_ARCHIVE_MAX_ENTRIES} 个。"
        )
    return _document(
        filename or "TAR 压缩包",
        _table(("成员", "原始大小", "修改时间"), rows),
        subtitle=f"TAR 压缩包 · {total} 个成员" + ("（扫描上限）" if capped else ""),
        note=note,
    )


def _gzip_header(data: bytes) -> tuple[str, int | None]:
    """Best-effort original filename + mtime from the gzip member header."""
    if len(data) < 10 or data[:2] != b"\x1f\x8b":
        return "", None
    mtime: int | None = int.from_bytes(data[4:8], "little") or None
    flags = data[3]
    position = 10
    try:
        if flags & 0x04:  # FEXTRA
            extra_len = int.from_bytes(data[position : position + 2], "little")
            position += 2 + extra_len
        name = ""
        if flags & 0x08:  # FNAME
            end = data.index(b"\x00", position)
            name = data[position:end].decode("utf-8", "replace")
        return name, mtime
    except (IndexError, ValueError):
        return "", mtime


def _gzip_listing(data: bytes, filename: str, content_type: str) -> bytes:
    member_name, mtime = _gzip_header(data)
    if not member_name:
        base = (filename or "").lower()
        member_name = filename[: -len(".gz")] if base.endswith(".gz") else "gzip 数据流"
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            head = stream.read(_GZ_PROBE_BYTES + 1)
    except (OSError, EOFError, zlib.error):
        return convert_binary(
            data, filename=filename, content_type=content_type, note=_ARCHIVE_FALLBACK_NOTE
        )
    complete = len(head) <= _GZ_PROBE_BYTES
    size_text = _human_size(len(head))
    if not complete:
        size_text = f"超过 {_human_size(_GZ_PROBE_BYTES)}（探测上限）"
    rows = ((member_name, size_text, _format_timestamp(mtime)),)
    return _document(
        filename or "GZIP 压缩流",
        _table(("成员", "解压后大小", "修改时间"), rows),
        subtitle="GZIP 单文件压缩流 · 无法在不完整解压时报告精确大小"
        if not complete
        else "GZIP 单文件压缩流",
    )


def _looks_like_7z_or_rar(data: bytes) -> bool:
    return (
        data[:6] == b"7z\xbc\xaf\x27\x1c"
        or data[:7] == b"Rar!\x1a\x07\x00"
        or data[:8] == b"Rar!\x1a\x07\x01\x00"
    )


def _opens_as_tar(data: bytes, mode: str) -> bool:
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode=mode):
            return True
    except (tarfile.TarError, OSError, EOFError, ValueError):
        return False


def convert_archive(data: bytes, *, filename: str = "", content_type: str = "") -> bytes:
    """Archive listing (zip/tar/gz); 7z/rar and unreadable data → metadata page."""
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    if not data:
        return convert_binary(
            data, filename=filename, content_type=content_type, note="压缩包为空。"
        )
    if (
        _looks_like_7z_or_rar(data)
        or name.endswith((".7z", ".rar"))
        or ctype
        in {
            "application/x-7z-compressed",
            "application/vnd.rar",
            "application/x-rar-compressed",
        }
    ):
        return convert_binary(
            data, filename=filename, content_type=content_type, note=_LEGACY_ARCHIVE_NOTE
        )
    if name.endswith(".gz") and not name.endswith((".tar.gz", ".tgz")):
        return _gzip_listing(data, filename, content_type)
    if name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        return _tar_listing(data, filename, content_type)
    if name.endswith(".zip"):
        return _zip_listing(data, filename, content_type)
    # Sniff the bytes when the name/content-type is not decisive.
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return _zip_listing(data, filename, content_type)
    if data[:2] == b"\x1f\x8b":
        return (
            _tar_listing(data, filename, content_type)
            if _opens_as_tar(data, "r:gz")
            else _gzip_listing(data, filename, content_type)
        )
    if data[:3] == b"BZh" or data[:6] == b"\xfd7zXZ\x00":
        return _tar_listing(data, filename, content_type)
    if len(data) >= 262 and data[257:262] == b"ustar":
        return _tar_listing(data, filename, content_type)
    return convert_binary(
        data, filename=filename, content_type=content_type, note=_ARCHIVE_FALLBACK_NOTE
    )


# ---------------------------------------------------------------------------
# PDF — pypdfium2 page rasterisation into a self-contained image page
# ---------------------------------------------------------------------------


def _pdfium_module():
    try:
        import pypdfium2
    except Exception as exc:  # pragma: no cover - dependency is pinned for web
        raise ConverterUnavailable(
            "服务端缺少 PDF 渲染组件（pypdfium2），无法生成 PDF 预览"
        ) from exc
    return pypdfium2


def _pdf_page_scale(page, requested: float) -> float:
    """Clamp the render scale so hostile page sizes cannot exhaust memory."""
    try:
        width, height = page.get_size()
    except Exception:
        return requested
    if width <= 0 or height <= 0:
        return requested
    scale = min(
        float(requested),
        _PDF_MAX_PAGE_SIDE / width,
        _PDF_MAX_PAGE_SIDE / height,
    )
    pixels = width * scale * height * scale
    if pixels > _PDF_MAX_PAGE_PIXELS and pixels > 0:
        scale *= math.sqrt(_PDF_MAX_PAGE_PIXELS / pixels)
    longest = max(width, height) * scale
    if 0 < longest < _PDF_MIN_PAGE_SIDE:
        scale = _PDF_MIN_PAGE_SIDE / max(width, height)
    return max(scale, 1e-6)


def _pdf_page_png(page, scale: float) -> bytes:
    """Render one page to PNG bytes (bitmap kept alive until encoding ends)."""
    bitmap = page.render(scale=scale)
    try:
        image = bitmap.to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        try:
            bitmap.close()
        except Exception:  # pragma: no cover - defensive
            pass


def convert_pdf(data: bytes, *, filename: str = "", content_type: str = "") -> bytes:
    """Rasterise up to 30 pages into ``data:image/png`` ``<img>`` tags."""
    if not data:
        raise ConversionFailed("PDF 文件为空")
    pdfium = _pdfium_module()
    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ConversionFailed(f"PDF 无法解析（{type(exc).__name__}）") from exc
    try:
        try:
            total_pages = len(document)
        except Exception as exc:
            raise ConversionFailed(f"PDF 无法读取页数（{type(exc).__name__}）") from exc
        if total_pages <= 0:
            raise ConversionFailed("PDF 不含可渲染页面")
        limit = min(total_pages, _PDF_MAX_PAGES)
        images: list[bytes] = []
        truncated = limit < total_pages
        page_note = ""
        for scale in _PDF_RENDER_SCALES:
            images = []
            size = 0
            truncated = limit < total_pages
            page_note = ""
            overflow = False
            for index in range(limit):
                page = None
                try:
                    page = document[index]
                    png = _pdf_page_png(page, _pdf_page_scale(page, scale))
                except Exception as exc:
                    truncated = True
                    page_note = f"第 {index + 1} 页渲染失败（{type(exc).__name__}）。"
                    break
                finally:
                    if page is not None:
                        try:
                            page.close()
                        except Exception:  # pragma: no cover - defensive
                            pass
                if size + len(png) > _PDF_IMAGE_BUDGET:
                    overflow = True
                    truncated = True
                    page_note = "页面图像总量超过预览上限，已截断。"
                    break
                images.append(png)
                size += len(png)
            if not overflow:
                break
        if not images:
            raise ConversionFailed("PDF 页面渲染失败，无法生成预览")
        pages_html = []
        for index, png in enumerate(images, start=1):
            encoded = base64.b64encode(png).decode("ascii")
            pages_html.append(
                f'<div class="page"><img alt="第 {index} 页" '
                f'src="data:image/png;base64,{encoded}"></div>'
            )
        note = ""
        if truncated:
            note = f"仅渲染前 {len(images)} / {total_pages} 页。"
            if page_note:
                note = f"{note}{page_note}"
        return _document(
            filename or "PDF 文档",
            "".join(pages_html),
            subtitle=f"{filename or 'PDF 文档'} · {total_pages} pages",
            note=note,
        )
    finally:
        try:
            document.close()
        except Exception:  # pragma: no cover - defensive
            pass


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def convert(
    kind: str,
    data: bytes,
    *,
    filename: str = "",
    content_type: str = "",
) -> bytes:
    """Convert ``data`` according to its shared preview ``kind``.

    ``image``/``media`` (and any unknown kind) raise :class:`NoConversion`:
    the service streams their original bytes instead.
    """
    if kind == kinds.PDF:
        return convert_pdf(data, filename=filename, content_type=content_type)
    if kind == kinds.OFFICE:
        return convert_office(data, filename=filename, content_type=content_type)
    if kind == kinds.ARCHIVE:
        return convert_archive(data, filename=filename, content_type=content_type)
    if kind == kinds.BINARY:
        return convert_binary(data, filename=filename, content_type=content_type)
    if kind == kinds.FRONTEND_STATIC:
        return convert_text(data, filename=filename, content_type=content_type)
    raise NoConversion(f"{kind or 'unknown'} 预览直接流式返回原始字节，无需转换")
