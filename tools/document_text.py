"""Plain-text extraction for binary documents read by the read tool.

The cloud worker image (infra/docker/worker.Dockerfile) is
python:3.12-slim-bookworm plus infra/docker/requirements-web.txt; that
dependency set ships no python-docx, openpyxl, pypdf or pdfminer. OOXML
(.docx/.xlsx/.pptx) and ODF (.odt/.ods/.odp) are ZIP containers of XML, so the
standard library (zipfile + xml.etree) is enough to return real text. Formats
that genuinely need a dependency the image does not have (PDF, legacy OLE
.doc/.xls/.ppt, RTF) return an actionable message instead of UTF-8 mojibake:
the model must never be handed ZIP bytes and asked to guess.

Design rules kept from tools/read.py:

* read-only, no temporary files, no network, no new pip dependencies;
* bounded work: every XML part and the final text are capped, so a malicious
  upload cannot balloon memory or the tool-result budget;
* detection uses magic bytes first and the extension only as a fallback, so a
  renamed container is still recognised and a corrupt one is explained.
"""

from __future__ import annotations

import codecs
import posixpath
import re
import zipfile
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

#: Hard ceiling for the extracted text handed back to read. The tool still
#: pages with offset/limit; this only stops one giant document from pinning
#: hundreds of MB in the worker process.
MAX_EXTRACTED_CHARS = 2_000_000
#: One compressed XML part may not inflate past this (zip-bomb guard).
MAX_XML_PART_BYTES = 16 * 1024 * 1024
#: Zip archives larger than this are reported, not opened for classification.
MAX_ZIP_ENTRIES = 50_000

_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF-"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_RTF_MAGIC = b"{\\rtf"

_ARCHIVE_MAGICS = (
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "rar"),
)

_IMAGE_MAGICS = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
    (b"II+\x00", "tiff"),
    (b"MM\x00+", "tiff"),
    (b"\x00\x00\x01\x00", "ico"),
)

#: OOXML / ODF extensions mapped to the container family. Macro-enabled and
#: template variants are still ZIP+XML; extracting their text is safe because
#: read never executes macros.
_OOXML_EXTENSIONS = {
    ".docx": "docx",
    ".docm": "docx",
    ".dotx": "docx",
    ".dotm": "docx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".xltx": "xlsx",
    ".xltm": "xlsx",
    ".pptx": "pptx",
    ".pptm": "pptx",
    ".potx": "pptx",
    ".potm": "pptx",
    ".ppsx": "pptx",
    ".odt": "odt",
    ".ods": "ods",
    ".odp": "odp",
}

#: Legacy binary Office family (OLE compound files) - detectable, not
#: extractable with the standard library alone.
_LEGACY_OFFICE_EXTENSIONS = frozenset(
    {".doc", ".dot", ".xls", ".xlt", ".ppt", ".pot", ".pps", ".wps", ".et", ".dps"}
)

_ODF_MIME_KINDS = {
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
    "application/vnd.oasis.opendocument.text-template": "odt",
    "application/vnd.oasis.opendocument.spreadsheet-template": "ods",
    "application/vnd.oasis.opendocument.presentation-template": "odp",
}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_ODF_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"

_BUILTIN_DATE_FORMAT_IDS = frozenset(set(range(14, 23)) | set(range(27, 37)))
_BUILTIN_TIME_FORMAT_IDS = frozenset(
    set(range(18, 22)) | set(range(45, 48)) | set(range(50, 59))
)
_SLIDE_NAME_RE = re.compile(r"ppt/slides/slide(\d+)\.xml\Z")
_WORKSHEET_NAME_RE = re.compile(r"xl/worksheets/[^/]+\.xml\Z")


class DocumentExtractionError(Exception):
    """The file was recognised but cannot be turned into text.

    str(exc) is already the actionable message read must return, so the caller
    simply surfaces it.
    """


def is_utf16_with_bom(prefix: bytes) -> bool:
    """True when prefix starts with a UTF-16 byte-order mark."""
    return prefix.startswith(codecs.BOM_UTF16_LE) or prefix.startswith(
        codecs.BOM_UTF16_BE
    )


def looks_binary(prefix: bytes) -> bool:
    """Cheap binary sniff used only when no document container was recognised.

    NUL bytes do not occur in ordinary UTF-8/ASCII text and are the one signal
    that reliably separates a binary payload from errors="replace" text.
    """
    return b"\x00" in prefix


def detect_binary_kind(path: Path, prefix: bytes) -> str | None:
    """Classify a non-text file, or return None for ordinary text.

    Kind values are docx, xlsx, pptx, odt, ods, odp, odf, pdf, ole, rtf, zip,
    archive, image and corrupt-<ext> (a known binary extension whose magic does
    not match). prefix must be the file's first bytes (8 KiB is plenty).
    """
    if prefix.startswith(_ZIP_MAGIC):
        kind = _classify_zip(path)
        return kind or "zip"
    if _PDF_MAGIC in prefix[:1024]:
        return "pdf"
    if prefix.startswith(_OLE_MAGIC):
        return "ole"
    if prefix.startswith(_RTF_MAGIC):
        return "rtf"
    if _image_kind(prefix) is not None:
        return "image"
    if _archive_kind(prefix) is not None:
        return "archive"
    extension = path.suffix.lower()
    if extension in _OOXML_EXTENSIONS:
        return f"corrupt-{extension.lstrip('.')}"
    if extension == ".pdf":
        return "corrupt-pdf"
    if extension in _LEGACY_OFFICE_EXTENSIONS:
        return f"corrupt-{extension.lstrip('.')}"
    if extension == ".rtf":
        return "corrupt-rtf"
    return None


def extract_document_text(path: Path, kind: str) -> tuple[str, bool]:
    """Return (text, truncated) for a supported document container.

    Raises DocumentExtractionError with an actionable message for every kind the
    stdlib cannot decode, and for damaged packages.
    """
    if kind not in {"docx", "xlsx", "pptx", "odt", "ods", "odp", "odf"}:
        raise DocumentExtractionError(guidance_for_kind(kind, path))
    try:
        with zipfile.ZipFile(path) as archive:
            if kind == "docx":
                text = _docx_text(archive)
            elif kind == "xlsx":
                text = _xlsx_text(archive)
            elif kind == "pptx":
                text = _pptx_text(archive)
            else:
                text = _odf_text(archive)
    except DocumentExtractionError:
        raise
    except (
        KeyError,
        OSError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
        zlib.error,
    ) as exc:
        raise DocumentExtractionError(
            f"[error: could not extract text from {path.name} ({kind}): "
            f"{type(exc).__name__}: {exc}. The package may be damaged or saved "
            "with an unsupported exporter; ask the user for a fresh copy or a "
            ".txt/.pdf-converted version.]"
        ) from exc
    except ET.ParseError as exc:
        raise DocumentExtractionError(
            f"[error: could not extract text from {path.name} ({kind}): its XML "
            f"is damaged ({exc}). Ask the user for a fresh copy.]"
        ) from exc
    truncated = len(text) > MAX_EXTRACTED_CHARS
    if truncated:
        text = text[:MAX_EXTRACTED_CHARS]
    return text, truncated


def guidance_for_kind(kind: str, path: Path) -> str:
    """Actionable, model-facing message for a binary the read tool cannot decode."""
    name = path.name
    if kind == "pdf":
        return (
            f"[error: cannot read {name} as text: it is a PDF and this environment "
            "has no PDF text extractor installed.]\n"
            "Do not present the raw bytes or a guessed summary as the document's "
            "content. Next steps: ask the user to paste the relevant text or "
            "upload a .docx/.txt copy; if you have bash, try converting the PDF "
            "to text first (for example an installed pdftotext) and read that "
            "output file."
        )
    if kind == "ole":
        return (
            f"[error: cannot read {name} as text: it is a legacy binary Office "
            "file (.doc/.xls/.ppt OLE container), not a ZIP/XML document.]\n"
            "Next steps: ask the user to re-save it as .docx/.xlsx/.pptx (or "
            ".txt) and upload again, or paste the content."
        )
    if kind == "rtf":
        return (
            f"[error: cannot read {name} as text: it is an RTF document and this "
            "environment has no RTF-to-text converter.]\n"
            "Next steps: ask the user to save it as .docx or .txt; the RTF "
            "control words are not readable content."
        )
    if kind in {"zip", "archive"}:
        detail = _archive_listing(path) if kind == "zip" else ""
        label = "ZIP archive" if kind == "zip" else "compressed archive"
        return (
            f"[error: cannot read {name} as text: it is a {label}, not a "
            "document.]"
            + (f"\nEntries: {detail}" if detail else "")
            + "\nNext steps: extract it with bash using the standard library, "
            "e.g. python3 -m zipfile -e <archive> <dest-dir> (or python3 -m gzip "
            "-d <file.gz>), then read the extracted file."
        )
    if kind == "image":
        return (
            f"[error: cannot read {name} as text: it is an image/video binary.]\n"
            "Next steps: to inspect the picture use the vision tool "
            '(operation="describe" or "ocr", filePath=...) ; for a screenshot '
            "with text, operation=\"ocr\" returns the text."
        )
    if kind.startswith("corrupt-"):
        extension = kind.split("-", 1)[1]
        return (
            f"[error: cannot read {name} as text: the file has a .{extension} "
            "extension but its bytes do not match that format "
            "(renamed, truncated, or a download placeholder).]\n"
            "Next steps: verify the upload is complete, or ask the user for a "
            "fresh copy. If the file is really plain text, rename it to .txt and "
            "read it again."
        )
    return (
        f"[error: cannot read {name} as text: binary file "
        f"({kind or 'unknown format'}) with no text extractor available.]\n"
        "Next steps: identify the real format with bash (e.g. file, or a hex "
        "header dump), then ask the user for a text/.docx/.xlsx copy; never "
        "present raw binary bytes as document content."
    )


def _image_kind(prefix: bytes) -> str | None:
    for magic, name in _IMAGE_MAGICS:
        if prefix.startswith(magic):
            return name
    if prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
        return "webp"
    if prefix[4:8] == b"ftyp":
        return "avif/heif"
    return None


def _archive_kind(prefix: bytes) -> str | None:
    for magic, name in _ARCHIVE_MAGICS:
        if prefix.startswith(magic):
            return name
    return None


def _classify_zip(path: Path) -> str | None:
    """Classify a ZIP container by its member names (docx/xlsx/pptx/odf)."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) > MAX_ZIP_ENTRIES:
                return None
            name_set = set(names)
            if "word/document.xml" in name_set:
                return "docx"
            if "xl/workbook.xml" in name_set:
                return "xlsx"
            if "ppt/presentation.xml" in name_set:
                return "pptx"
            if "content.xml" in name_set:
                try:
                    mime = _read_zip_part(archive, "mimetype", 256).decode(
                        "ascii", "replace"
                    ).strip()
                except DocumentExtractionError:
                    mime = ""
                return _ODF_MIME_KINDS.get(mime, "odf")
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, zlib.error):
        return None
    return None


def _archive_listing(path: Path) -> str:
    """Best-effort first entries of a ZIP so the model can choose a file."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = [
                name for name in archive.namelist() if name and not name.endswith("/")
            ]
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, zlib.error):
        return ""
    preview = ", ".join(names[:12])
    if len(names) > 12:
        preview += f", ... ({len(names)} files total)"
    return preview


def _read_zip_part(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise DocumentExtractionError(
            f"[error: the document package is missing its {name} part; "
            "it is damaged or not a real document.]"
        ) from exc
    if info.file_size > limit:
        raise DocumentExtractionError(
            f"[error: the {name} part of this document is too large to extract "
            f"({info.file_size} bytes > {limit} byte cap).]"
        )
    with archive.open(info) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise DocumentExtractionError(
            f"[error: the {name} part of this document expands past the "
            f"{limit}-byte extraction cap.]"
        )
    return data


def _xml_root(archive: zipfile.ZipFile, name: str) -> ET.Element:
    return ET.fromstring(_read_zip_part(archive, name, MAX_XML_PART_BYTES))


def _text_lines(text: str) -> str:
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", normalised).strip("\n")


def _docx_text(archive: zipfile.ZipFile) -> str:
    root = _xml_root(archive, "word/document.xml")
    paragraphs: list[str] = []
    for paragraph in root.iter(_W + "p"):
        chunks: list[str] = []
        for node in paragraph.iter():
            tag = node.tag
            if tag == _W + "t":
                if node.text:
                    chunks.append(node.text)
            elif tag == _W + "tab":
                chunks.append("\t")
            elif tag in {_W + "br", _W + "cr"}:
                chunks.append("\n")
            elif tag == _W + "noBreakHyphen":
                chunks.append("-")
        paragraphs.append("".join(chunks))
    return _text_lines("\n".join(paragraphs))


def _pptx_text(archive: zipfile.ZipFile) -> str:
    slide_names = [
        name for name in archive.namelist() if _SLIDE_NAME_RE.match(name)
    ]
    slide_names.sort(key=lambda name: int(_SLIDE_NAME_RE.match(name).group(1)))
    blocks: list[str] = []
    for index, name in enumerate(slide_names, start=1):
        root = _xml_root(archive, name)
        paragraphs: list[str] = []
        for paragraph in root.iter(_A + "p"):
            chunks: list[str] = []
            for node in paragraph.iter():
                if node.tag == _A + "t":
                    if node.text:
                        chunks.append(node.text)
                elif node.tag == _A + "br":
                    chunks.append("\n")
            line = "".join(chunks).strip()
            if line:
                paragraphs.append(line)
        blocks.append(f"--- Slide {index} ---\n" + "\n".join(paragraphs))
    return _text_lines("\n\n".join(blocks))


def _xlsx_text(archive: zipfile.ZipFile) -> str:
    names = archive.namelist()
    name_set = set(names)
    shared_strings: list[str] = []
    if "xl/sharedStrings.xml" in name_set:
        root = _xml_root(archive, "xl/sharedStrings.xml")
        for item in root.iter(_X + "si"):
            shared_strings.append(
                "".join(node.text or "" for node in item.iter(_X + "t"))
            )
    date_styles, time_styles = _xlsx_style_maps(archive, name_set)
    blocks: list[str] = []
    for sheet_name, sheet_path in _xlsx_sheet_paths(archive, names):
        root = _xml_root(archive, sheet_path)
        lines: list[str] = []
        for row in root.iter(_X + "row"):
            cells: list[str] = []
            for cell in row.findall(_X + "c"):
                value = _xlsx_cell_text(
                    cell, shared_strings, date_styles, time_styles
                )
                if value:
                    cells.append(value)
            if cells:
                lines.append("\t".join(cells))
        blocks.append(f"[Sheet {sheet_name}]\n" + "\n".join(lines))
    return _text_lines("\n\n".join(blocks))


def _xlsx_sheet_paths(
    archive: zipfile.ZipFile, names: list[str]
) -> list[tuple[str, str]]:
    sheet_names: list[str] = []
    relationship_ids: list[str] = []
    if "xl/workbook.xml" in names:
        root = _xml_root(archive, "xl/workbook.xml")
        sheets = root.find(_X + "sheets")
        if sheets is not None:
            for sheet in sheets.findall(_X + "sheet"):
                sheet_names.append(str(sheet.get("name") or ""))
                relationship_ids.append(str(sheet.get(_R + "id") or ""))
    relationship_targets: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in names:
        root = _xml_root(archive, "xl/_rels/workbook.xml.rels")
        for relation in root.findall(_PKG_REL + "Relationship"):
            relationship_targets[str(relation.get("Id") or "")] = str(
                relation.get("Target") or ""
            )
    worksheets = sorted(
        (name for name in names if _WORKSHEET_NAME_RE.match(name)),
        key=_natural_key,
    )
    resolved: list[tuple[str, str]] = []
    for index, worksheet in enumerate(worksheets):
        target = _relationship_target(
            relationship_targets.get(relationship_ids[index], "")
            if index < len(relationship_ids)
            else ""
        )
        path = target if target in names else worksheet
        label = (
            sheet_names[index]
            if index < len(sheet_names) and sheet_names[index]
            else path.rsplit("/", 1)[-1]
        )
        resolved.append((label, path))
    return resolved


def _relationship_target(target: str) -> str:
    if not target:
        return ""
    target = target.replace("\\", "/")
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(posixpath.join("xl", target))


def _natural_key(value: str) -> list[object]:
    return [
        int(part) if part.isdigit() else part
        for part in re.split(r"(\d+)", value)
    ]


def _xlsx_style_maps(
    archive: zipfile.ZipFile, names: list[str]
) -> tuple[dict[int, bool], dict[int, bool]]:
    """Return (date_style, time_style) maps keyed by cellXfs index."""
    if "xl/styles.xml" not in names:
        return {}, {}
    root = _xml_root(archive, "xl/styles.xml")
    format_codes: dict[int, str] = {}
    for fmt in root.iter(_X + "numFmt"):
        try:
            fmt_id = int(fmt.get("numFmtId") or "-1")
        except ValueError:
            continue
        format_codes[fmt_id] = str(fmt.get("formatCode") or "")
    date_styles: dict[int, bool] = {}
    time_styles: dict[int, bool] = {}
    cell_xfs = root.find(_X + "cellXfs")
    if cell_xfs is None:
        return {}, {}
    for index, xf in enumerate(cell_xfs.findall(_X + "xf")):
        try:
            fmt_id = int(xf.get("numFmtId") or "0")
        except ValueError:
            fmt_id = 0
        is_date = fmt_id in _BUILTIN_DATE_FORMAT_IDS or _is_date_format_code(
            format_codes.get(fmt_id, "")
        )
        is_time = fmt_id in _BUILTIN_TIME_FORMAT_IDS or _is_time_format_code(
            format_codes.get(fmt_id, "")
        )
        date_styles[index] = is_date
        time_styles[index] = is_time
    return date_styles, time_styles


def _is_date_format_code(code: str) -> bool:
    return bool(code) and bool(
        re.search(r"[ymdhs]", _strip_format_literals(code), re.I)
    )


def _is_time_format_code(code: str) -> bool:
    stripped = _strip_format_literals(code)
    if not stripped:
        return False
    return bool(re.search(r"[hs]", stripped, re.I)) and not re.search(
        r"[yd]", stripped, re.I
    )


def _strip_format_literals(code: str) -> str:
    """Drop [Red]/"literal"/colour sections before looking for date tokens."""
    cleaned = re.sub(r"\[[^\]]*\]", "", code)
    cleaned = re.sub(r'"[^"]*"', "", cleaned)
    return cleaned.split(";", 1)[0]


def _xlsx_cell_text(
    cell: ET.Element,
    shared_strings: list[str],
    date_styles: dict[int, bool],
    time_styles: dict[int, bool],
) -> str:
    cell_type = cell.get("t") or ""
    if cell_type == "inlineStr":
        return _clean_cell_text(
            "".join(node.text or "" for node in cell.iter(_X + "t"))
        )
    value = cell.findtext(_X + "v")
    if value is None:
        return ""
    value = value.strip()
    if cell_type == "s":
        try:
            return _clean_cell_text(shared_strings[int(value)])
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        return {"1": "TRUE", "0": "FALSE"}.get(value, value)
    if cell_type in {"str", "e"}:
        return _clean_cell_text(value)
    try:
        number = float(value)
    except ValueError:
        return _clean_cell_text(value)
    style_index = _cell_style_index(cell)
    if style_index is not None and (
        date_styles.get(style_index) or time_styles.get(style_index)
    ):
        rendered = _excel_serial_text(
            number,
            date=bool(date_styles.get(style_index)),
            time_only=bool(time_styles.get(style_index))
            and not date_styles.get(style_index),
        )
        if rendered:
            return rendered
    return _format_number(number)


def _cell_style_index(cell: ET.Element) -> int | None:
    raw = cell.get("s")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


_EXCEL_EPOCH = datetime(1899, 12, 30)


def _excel_serial_text(number: float, *, date: bool, time_only: bool) -> str:
    """Render an Excel serial date/time as ISO text (best effort, no locale)."""
    if number != number or number < 0:  # NaN or pre-epoch
        return ""
    try:
        moment = _EXCEL_EPOCH + timedelta(days=number)
    except (OverflowError, ValueError):
        return ""
    if moment.year < 1900 or moment.year > 9999:
        return ""
    if time_only or (date and 0 <= number < 1):
        return moment.strftime("%H:%M:%S")
    if moment.time() == datetime.min.time():
        return moment.strftime("%Y-%m-%d")
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _format_number(number: float) -> str:
    if number.is_integer() and abs(number) < 10**15:
        return str(int(number))
    return f"{number:g}"


def _clean_cell_text(value: str) -> str:
    return " ".join(
        value.replace("\r", " ").replace("\n", " ").replace("\t", " ").split()
    )


def _odf_text(archive: zipfile.ZipFile) -> str:
    root = _xml_root(archive, "content.xml")
    blocks: list[str] = []
    for node in root.iter():
        if node.tag in {_ODF_TEXT + "p", _ODF_TEXT + "h"}:
            line = "".join(node.itertext()).strip()
            if line:
                blocks.append(line)
    return _text_lines("\n".join(blocks))
