"""WEB-W11 preview converters: pure artifact→HTML coverage for every kind.

Requirement: ``所有类型的文件都可以预览`` — the preview service must be able to
turn PDF, Office, archive, binary (and text) bytes into a ready, sandboxed,
fully escaped HTML page. These tests exercise the pure converter functions
directly (no Postgres, no Docker, no S3).

The PDF case is the only optional one: it skips — never fakes a pass — when
``pypdfium2`` is not installed in the test environment.
"""

from __future__ import annotations

import gzip
import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_SERVER_SRC = REPO / "packages" / "rxycode-server" / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

from rxycode_server.previews import converters, kinds  # noqa: E402

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures: tiny, valid OOXML / ODF / archive / PDF payloads built in memory
# ---------------------------------------------------------------------------


def _docx_bytes() -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        "<w:r><w:t>Report title</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Body text with a &lt;script&gt;alert(1)&lt;/script&gt; "
        "payload</w:t></w:r></w:p>"
        "<w:tbl>"
        "<w:tr><w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>alpha</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>42</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl>"
        "<w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>bullet item</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("word/document.xml", document)
    return buffer.getvalue()


def _office_docx_bytes(*documents: tuple[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, payload in documents:
            bundle.writestr(name, payload)
    return buffer.getvalue()


def _xlsx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships"><sheets>'
            '<sheet name="Summary" sheetId="1" r:id="rId1"/>'
            '<sheet name="Data" sheetId="2" r:id="rId2"/>'
            "</sheets></workbook>",
        )
        bundle.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.'
            'org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="worksheet" Target="worksheets/sheet2.xml"/>'
            "</Relationships>",
        )
        bundle.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"><si><t>Name</t></si><si><t>Alice</t></si>'
            "<si><t>Score</t></si></sst>",
        )
        bundle.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c>'
            '<c r="B1" t="s"><v>2</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>42</v></c></row>'
            "</sheetData></worksheet>",
        )
        bundle.writestr(
            "xl/worksheets/sheet2.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"><sheetData><row r="1">'
            '<c r="A1" t="inlineStr"><is><t>inline &lt;value&gt;</t></is></c>'
            "</row></sheetData></worksheet>",
        )
    return buffer.getvalue()


def _pptx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(
            "ppt/presentation.xml",
            '<?xml version="1.0"?><p:presentation xmlns:p="http://schemas.'
            'openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships"><p:sldIdLst>'
            '<p:sldId id="256" r:id="rId2"/>'
            '<p:sldId id="257" r:id="rId3"/>'
            "</p:sldIdLst></p:presentation>",
        )
        bundle.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.'
            'org/package/2006/relationships">'
            '<Relationship Id="rId2" Type="slide" Target="slides/slide1.xml"/>'
            '<Relationship Id="rId3" Type="slide" Target="slides/slide2.xml"/>'
            "</Relationships>",
        )
        for index, text in ((1, "First slide title"), (2, "Second slide body")):
            bundle.writestr(
                f"ppt/slides/slide{index}.xml",
                '<?xml version="1.0"?><p:sld xmlns:p="http://schemas.openxmlformats.'
                'org/presentationml/2006/main" xmlns:a="http://schemas.'
                'openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp>'
                f"<p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody>"
                "</p:sp></p:spTree></p:cSld></p:sld>",
            )
    return buffer.getvalue()


def _odt_bytes() -> bytes:
    content = (
        '<?xml version="1.0"?><office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">'
        "<office:body><office:text>"
        '<text:h text:outline-level="1">ODT heading</text:h>'
        '<text:p>first paragraph<text:s text:c="3"/>tail</text:p>'
        '<table:table table:name="ODF table"><table:table-row>'
        "<table:table-cell><text:p>c1</text:p></table:table-cell>"
        "<table:table-cell><text:p>c2</text:p></table:table-cell>"
        "</table:table-row></table:table>"
        "</office:text></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        bundle.writestr("content.xml", content)
    return buffer.getvalue()


def _ods_bytes() -> bytes:
    content = (
        '<?xml version="1.0"?><office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">'
        "<office:body><office:spreadsheet>"
        '<table:table table:name="Numbers"><table:table-row>'
        "<table:table-cell><text:p>label</text:p></table:table-cell>"
        '<table:table-cell office:value-type="float" office:value="7.5"/>'
        "</table:table-row></table:table>"
        "</office:spreadsheet></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        bundle.writestr("content.xml", content)
    return buffer.getvalue()


def _odp_bytes() -> bytes:
    content = (
        '<?xml version="1.0"?><office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0">'
        "<office:body><office:presentation>"
        '<draw:page draw:name="Slide 1"><draw:frame><draw:text-box>'
        "<text:p>Slide one body</text:p>"
        "</draw:text-box></draw:frame></draw:page>"
        "</office:presentation></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("mimetype", "application/vnd.oasis.opendocument.presentation")
        bundle.writestr("content.xml", content)
    return buffer.getvalue()


def _zip_bytes(entries: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in (entries or {"dir/readme.txt": b"hello", "b.bin": b"1234"}).items():
            bundle.writestr(name, payload)
    return buffer.getvalue()


def _tar_gz_bytes() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, payload in (("pkg/one.txt", b"0123456789"), ("pkg/two.txt", b"xy")):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mtime = 1_700_000_000
            bundle.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _gzip_bytes() -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(
        filename="notes.txt", fileobj=buffer, mode="wb", mtime=1_700_000_000
    ) as stream:
        stream.write(b"hello gzip" * 100)
    return buffer.getvalue()


def _minimal_pdf(pages: int = 1, size: tuple[int, int] = (300, 200)) -> bytes:
    """A structurally valid PDF with ``pages`` blank-ish pages (no external refs)."""
    page_ids: list[int] = []
    content_ids: list[int] = []
    next_id = 3
    for _ in range(pages):
        page_ids.append(next_id)
        next_id += 1
        content_ids.append(next_id)
        next_id += 1
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
    ]
    for index, (_page_id, content_id) in enumerate(zip(page_ids, content_ids)):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {size[0]} {size[1]}] "
                f"/Contents {content_id} 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
            ).encode()
        )
        stream = f"BT /F1 12 Tf 20 50 Td (Page {index + 1}) Tj ET".encode()
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for index, payload in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n".encode() + payload + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def _pdfium_available() -> bool:
    try:
        import pypdfium2  # noqa: F401
    except Exception:
        return False
    return True


def _text(page: bytes) -> str:
    return page.decode("utf-8")


def _assert_self_contained(page: bytes) -> str:
    """Every produced document must be safe for the sandboxed iframe CSP."""
    text = _text(page)
    assert text.startswith("<!doctype html>")
    lowered = text.lower()
    assert "<script" not in lowered
    assert "<link" not in lowered
    assert "javascript:" not in lowered
    assert "@import" not in lowered
    assert 'src="http' not in lowered
    assert "src='http" not in lowered
    assert "url(http" not in lowered
    return text


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_dispatch_routes_every_convertible_kind() -> None:
    """``convert`` is the single dispatch the preview service relies on."""
    binary = converters.convert(kinds.BINARY, b"\x00\x01", filename="f.bin")
    assert "SHA-256" in _assert_self_contained(binary)

    text = converters.convert(kinds.FRONTEND_STATIC, b"plain <text>", filename="a.md")
    assert "plain &lt;text&gt;" in _assert_self_contained(text)

    office = converters.convert(kinds.OFFICE, _docx_bytes(), filename="a.docx")
    assert "Report title" in _assert_self_contained(office)

    archive = converters.convert(kinds.ARCHIVE, _zip_bytes(), filename="a.zip")
    assert "dir/readme.txt" in _assert_self_contained(archive)

    if _pdfium_available():
        pdf = converters.convert(kinds.PDF, _minimal_pdf(1), filename="a.pdf")
        assert 'src="data:image/png;base64,' in _assert_self_contained(pdf)
    else:  # pragma: no cover - CI without pypdfium2
        with pytest.raises(converters.ConverterError):
            converters.convert(kinds.PDF, _minimal_pdf(1), filename="a.pdf")

    for streamed in (kinds.IMAGE, kinds.MEDIA, "unknown-kind"):
        with pytest.raises(converters.NoConversion):
            converters.convert(streamed, b"payload")


# ---------------------------------------------------------------------------
# Office
# ---------------------------------------------------------------------------


def test_docx_extracts_paragraphs_tables_and_escapes() -> None:
    page = converters.convert_office(_docx_bytes(), filename="report.docx")
    text = _assert_self_contained(page)
    assert "<h2>Report title</h2>" in text
    assert "<table>" in text
    assert "alpha" in text and "42" in text
    assert "bullet item" in text
    # Artifact-controlled text is escaped, never injected.
    assert "&lt;script&gt;" in text
    assert "<script>alert(1)" not in text


def test_xlsx_extracts_sheets_shared_and_inline_cells() -> None:
    page = converters.convert_office(
        _xlsx_bytes(),
        filename="sheet.xlsx",
        content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )
    text = _assert_self_contained(page)
    assert "<h2>Summary</h2>" in text and "<h2>Data</h2>" in text
    assert "Alice" in text and "42" in text
    assert "inline &lt;value&gt;" in text


def test_pptx_extracts_slide_text_in_order() -> None:
    page = converters.convert_office(_pptx_bytes(), filename="deck.pptx")
    text = _assert_self_contained(page)
    first = text.index("First slide title")
    second = text.index("Second slide body")
    assert first < second
    assert "第 2 张幻灯片" in text


def test_odf_extracts_paragraphs_and_tables() -> None:
    page = converters.convert_office(_odt_bytes(), filename="case.odt")
    text = _assert_self_contained(page)
    assert "<h2>ODT heading</h2>" in text
    assert "first paragraph   tail" in text  # text:s text:c=3 -> three spaces
    assert "ODF table" in text and "c1" in text and "c2" in text


def test_ods_and_odp_extract_tables_and_slide_text() -> None:
    ods = _assert_self_contained(converters.convert_office(_ods_bytes(), filename="numbers.ods"))
    assert "<h2>Numbers</h2>" in ods
    assert "label" in ods and "7.5" in ods  # numeric cell falls back to office:value
    assert "<table>" in ods

    odp = _assert_self_contained(converters.convert_office(_odp_bytes(), filename="slides.odp"))
    assert "第 1 页" in odp
    assert "Slide one body" in odp


def test_unreadable_office_container_falls_back_to_metadata_page() -> None:
    """Never raise for a corrupt OOXML/ODF container — show the honest page."""
    page = converters.convert_office(b"this is not a zip", filename="broken.docx")
    text = _assert_self_contained(page)
    assert "SHA-256" in text
    assert "Office" in text  # fallback note mentions the failed container

    zip_without_office_parts = _office_docx_bytes(("mimetype", "application/zip"))
    page = converters.convert_office(zip_without_office_parts, filename="odd.docx")
    assert "SHA-256" in _assert_self_contained(page)


def test_xlsx_row_cap_is_reported_honestly() -> None:
    sheet = (
        '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main"><sheetData>'
        + "".join(
            f'<row r="{index}"><c r="A{index}"><v>{index}</v></c></row>' for index in range(1, 251)
        )
        + "</sheetData></worksheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"><sheets><sheet name="Big" sheetId="1"/>'
            "</sheets></workbook>",
        )
        bundle.writestr("xl/worksheets/sheet1.xml", sheet)
    text = _assert_self_contained(converters.convert_office(buffer.getvalue(), filename="big.xlsx"))
    assert "超过" in text and "200" in text


# ---------------------------------------------------------------------------
# Archives
# ---------------------------------------------------------------------------


def test_zip_listing_shows_member_names_and_sizes() -> None:
    page = converters.convert_archive(_zip_bytes(), filename="bundle.zip")
    text = _assert_self_contained(page)
    assert "dir/readme.txt" in text and "b.bin" in text
    assert "5 B" in text and "4 B" in text
    assert "<table>" in text


def test_tar_listing_shows_member_names_and_sizes() -> None:
    page = converters.convert_archive(_tar_gz_bytes(), filename="pkg.tar.gz")
    text = _assert_self_contained(page)
    assert "pkg/one.txt" in text and "pkg/two.txt" in text
    assert "10 B" in text and "2 B" in text


def test_gzip_single_member_reports_name_and_decompressed_size() -> None:
    page = converters.convert_archive(_gzip_bytes(), filename="notes.txt.gz")
    text = _assert_self_contained(page)
    assert "notes.txt" in text
    assert "1000 B" in text  # 1000 bytes decompressed


def test_archive_entry_cap_is_reported() -> None:
    entries = {f"member-{index}.txt": b"x" for index in range(301)}
    page = converters.convert_archive(_zip_bytes(entries), filename="many.zip")
    text = _assert_self_contained(page)
    assert "member-0.txt" in text
    assert "member-300.txt" not in text
    assert "300" in text  # "仅显示前 300 个"


def test_7z_and_corrupt_archives_fall_back_to_metadata() -> None:
    seven_zip = b"7z\xbc\xaf\x27\x1c" + b"\x00" * 32
    text = _assert_self_contained(converters.convert_archive(seven_zip, filename="bundle.7z"))
    assert "SHA-256" in text and "7z/rar" in text

    corrupt = converters.convert_archive(b"PK\x03\x04garbage", filename="bad.zip")
    assert "SHA-256" in _assert_self_contained(corrupt)


# ---------------------------------------------------------------------------
# Binary
# ---------------------------------------------------------------------------


def test_binary_page_has_metadata_hexdump_and_caps_at_4kb() -> None:
    payload = b"<\x00\x01\x02&" + b"A" * (5000 - 5)
    page = converters.convert_binary(
        payload, filename="firmware.bin", content_type="application/octet-stream"
    )
    text = _assert_self_contained(page)
    assert "firmware.bin" in text
    assert "application/octet-stream" in text
    assert str(len(payload)) in text
    assert "SHA-256" in text
    # Hexdump with offsets, ASCII column escaped.
    assert "00000000" in text
    assert "00000ff0" in text  # last 16-byte row of the 4KB window
    assert "00001000" not in text  # nothing past the 4KB cap
    assert "3c 00 01 02 26" in text
    assert "&lt;" in text  # ASCII column text is escaped
    assert "<\x00" not in text  # no raw bytes / markup injected


def test_empty_binary_still_gets_a_page() -> None:
    text = _assert_self_contained(converters.convert_binary(b"", filename="empty.bin"))
    assert "文件为空" in text


# ---------------------------------------------------------------------------
# PDF (optional renderer: skip honestly when pypdfium2 is missing)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _pdfium_available(), reason="pypdfium2 is not installed")
def test_pdf_renders_pages_as_data_uri_images() -> None:
    page = converters.convert_pdf(_minimal_pdf(3), filename="doc.pdf")
    text = _assert_self_contained(page)
    assert "doc.pdf · 3 pages" in text
    assert text.count('src="data:image/png;base64,') == 3
    assert 'alt="第 1 页"' in text


@pytest.mark.skipif(not _pdfium_available(), reason="pypdfium2 is not installed")
def test_pdf_page_cap_truncates_with_honest_note() -> None:
    page = converters.convert_pdf(_minimal_pdf(31), filename="big.pdf")
    text = _assert_self_contained(page)
    assert text.count('src="data:image/png;base64,') == converters._PDF_MAX_PAGES
    assert "仅渲染前 30 / 31 页" in text


@pytest.mark.skipif(not _pdfium_available(), reason="pypdfium2 is not installed")
def test_pdf_image_budget_truncates_with_honest_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When page images blow the size budget, the page is truncated honestly."""
    pdfium = pytest.importorskip("pypdfium2")
    payload = _minimal_pdf(3)
    document = pdfium.PdfDocument(payload)
    try:
        page = document[0]
        try:
            first_page = converters._pdf_page_png(page, converters._pdf_page_scale(page, 2.0))
        finally:
            page.close()
    finally:
        document.close()
    # One page fits; the second would exceed the budget at the only allowed
    # scale, so the converter must stop after page 1 with an honest note.
    monkeypatch.setattr(converters, "_PDF_RENDER_SCALES", (2.0,))
    monkeypatch.setattr(converters, "_PDF_IMAGE_BUDGET", len(first_page) + 100)
    text = _assert_self_contained(converters.convert_pdf(payload, filename="three.pdf"))
    assert text.count('src="data:image/png;base64,') == 1
    assert "仅渲染前 1 / 3 页" in text


def test_corrupt_pdf_raises_converter_error() -> None:
    """A failed conversion is an honest exception, never a hang or bad page."""
    with pytest.raises(converters.ConverterError):
        converters.convert_pdf(b"definitely not a pdf")


# ---------------------------------------------------------------------------
# Text / frontend_static
# ---------------------------------------------------------------------------


def test_text_page_escapes_artifact_content() -> None:
    page = converters.convert_text(b"line <two> & 'quotes'\n", filename="note.txt")
    text = _assert_self_contained(page)
    assert "line &lt;two&gt; &amp; &#x27;quotes&#x27;" in text
    assert "line <two>" not in text
