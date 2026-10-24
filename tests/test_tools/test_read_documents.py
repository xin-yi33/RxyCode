"""Read tool: binary-document detection and plain-text extraction.

Covers the cloud failure where a .docx upload reached the workspace but
tools/read.py decoded the ZIP bytes as UTF-8 replacement characters, so the
model could not read the user's document. Extraction is stdlib-only
(zipfile + xml.etree) because the worker image has no python-docx/openpyxl.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DRAW_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _paragraph(text: str) -> str:
    return (
        '<w:p><w:r><w:t xml:space="preserve">' + _escape(text) + "</w:t></w:r></w:p>"
    )


def _write_docx(path: Path, paragraphs, table=None) -> Path:
    body = "".join(_paragraph(text) for text in paragraphs)
    if table:
        rows = "".join(
            "<w:tr>"
            + "".join(
                "<w:tc>" + _paragraph(cell) + "</w:tc>" for cell in row
            )
            + "</w:tr>"
            for row in table
        )
        body += "<w:tbl>" + rows + "</w:tbl>"
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body>{body}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
    return path


def _write_xlsx(path: Path, sheet_name: str, rows) -> Path:
    shared: list[str] = []

    def cell(value) -> str:
        if isinstance(value, tuple) and value and value[0] == "date":
            return f'<c s="1"><v>{value[1]}</v></c>'
        if isinstance(value, str):
            shared.append(value)
            return f'<c t="s"><v>{len(shared) - 1}</v></c>'
        if isinstance(value, bool):
            return f'<c t="b"><v>{1 if value else 0}</v></c>'
        if isinstance(value, (int, float)):
            return f"<c><v>{value}</v></c>"
        return f'<c t="inlineStr"><is><t>{_escape(value)}</t></is></c>'

    sheet_rows = "".join(
        f'<row r="{index}">' + "".join(cell(value) for value in row) + "</row>"
        for index, row in enumerate(rows, 1)
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{SHEET_NS}"><sheetData>{sheet_rows}</sheetData></worksheet>'
    )
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="{SHEET_NS}" count="{len(shared)}" uniqueCount="{len(shared)}">'
        + "".join("<si><t>" + _escape(text) + "</t></si>" for text in shared)
        + "</sst>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{SHEET_NS}" xmlns:r="{REL_NS}"><sheets>'
        f'<sheet name="{_escape(sheet_name)}" sheetId="1" r:id="rId1"/>'
        "</sheets></workbook>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PKG_REL_NS}">'
        '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{SHEET_NS}"><cellXfs count="2">'
        '<xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/>'
        "</cellXfs></styleSheet>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/styles.xml", styles_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return path


def _write_pptx(path: Path, slides) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ppt/presentation.xml", "<presentation/>")
        for index, lines in enumerate(slides, 1):
            paragraphs = "".join(
                "<a:p><a:r><a:t>" + _escape(line) + "</a:t></a:r></a:p>"
                for line in lines
            )
            slide = (
                f'<a:root xmlns:a="{DRAW_NS}">{paragraphs}</a:root>'
            )
            archive.writestr(f"ppt/slides/slide{index}.xml", slide)
    return path


def _read(path: Path, offset: int = 1, limit: int = 800) -> str:
    from RxyCode.RxyCode1_1_0.tools.read import read_file

    return read_file(str(path), offset, limit)


class TestDocxExtraction:
    def test_reads_chinese_report_text(self, tmp_path):
        path = _write_docx(
            tmp_path / "实验报告-第3章 HDFS分布式文件系统_阮心一.docx",
            [
                "实验报告",
                "第3章 HDFS分布式文件系统",
                "作者：阮心一",
            ],
        )
        result = _read(path)
        assert "实验报告" in result
        assert "第3章 HDFS分布式文件系统" in result
        assert "阮心一" in result
        # Never mojibake: no replacement chars and no ZIP header text.
        assert "\ufffd" not in result
        assert not result.startswith("PK")
        assert "PK\x03\x04" not in result

    def test_header_names_the_document(self, tmp_path):
        path = _write_docx(tmp_path / "报告.docx", ["正文"])
        result = _read(path)
        assert "报告.docx" in result.splitlines()[0]
        assert "docx" in result.splitlines()[0]

    def test_table_cell_text_is_extracted(self, tmp_path):
        path = _write_docx(
            tmp_path / "table.docx",
            ["下表是节点状态"],
            table=[["节点", "状态"], ["DataNode1", "正常"]],
        )
        result = _read(path)
        assert "DataNode1" in result
        assert "正常" in result

    def test_offset_and_limit_page_the_extracted_text(self, tmp_path):
        paragraphs = [f"段落{i}" for i in range(1, 51)]
        path = _write_docx(tmp_path / "long.docx", paragraphs)
        result = _read(path, offset=3, limit=5)
        assert "3: 段落3" in result
        assert "7: 段落7" in result
        assert "8: 段落8" not in result
        assert "2: 段落2" not in result

    def test_empty_document_is_explicit(self, tmp_path):
        path = _write_docx(tmp_path / "empty.docx", [])
        result = _read(path)
        assert "no extractable text" in result

    def test_read_tool_invoke_returns_extracted_text(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.read import read_tool

        path = _write_docx(tmp_path / "invoke.docx", ["工具调用文本"])
        result = read_tool.invoke({"filePath": str(path)})
        assert "工具调用文本" in result


class TestXlsxExtraction:
    def test_shared_strings_and_numbers(self, tmp_path):
        path = _write_xlsx(
            tmp_path / "数据表.xlsx",
            "节点",
            [["名称", "副本数"], ["DataNode1", 3], ["DataNode2", 2.5]],
        )
        result = _read(path)
        assert "名称" in result
        assert "DataNode1" in result
        assert "3" in result
        assert "2.5" in result
        assert "PK" not in result

    def test_date_serial_rendered_as_iso_date(self, tmp_path):
        # 45292 == 2024-01-01 in the Excel 1900 date system.
        path = _write_xlsx(
            tmp_path / "日期.xlsx",
            "日期",
            [["开始日期"], [("date", 45292)]],
        )
        result = _read(path)
        assert "2024-01-01" in result


class TestPptxExtraction:
    def test_slides_are_labelled(self, tmp_path):
        path = _write_pptx(
            tmp_path / "汇报.pptx",
            [["第一页标题", "要点一"], ["第二页标题"]],
        )
        result = _read(path)
        assert "第一页标题" in result
        assert "第二页标题" in result
        assert "Slide 2" in result


class TestUnsupportedBinaries:
    def test_pdf_returns_actionable_guidance(self, tmp_path):
        path = tmp_path / "报告.pdf"
        path.write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n")
        result = _read(path)
        assert "PDF" in result
        assert "no PDF text extractor" in result
        assert "\ufffd" not in result
        assert "docx" in result

    def test_legacy_doc_ole_guidance(self, tmp_path):
        path = tmp_path / "旧文档.doc"
        path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
        result = _read(path)
        assert "legacy binary Office" in result
        assert ".docx" in result

    def test_zip_archive_lists_entries_and_extraction_hint(self, tmp_path):
        path = tmp_path / "打包.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("notes.txt", "hello")
            archive.writestr("readme.md", "hi")
        result = _read(path)
        assert "ZIP archive" in result
        assert "notes.txt" in result
        assert "zipfile -e" in result

    def test_image_refers_to_vision_tool(self, tmp_path):
        path = tmp_path / "截图.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        result = _read(path)
        assert "image" in result
        assert "vision tool" in result

    def test_corrupt_docx_explains_bad_package(self, tmp_path):
        path = tmp_path / "损坏.docx"
        path.write_text("this is not a zip package", encoding="utf-8")
        result = _read(path)
        assert ".docx extension" in result
        assert "fresh copy" in result

    def test_unknown_binary_is_not_mojibake(self, tmp_path):
        path = tmp_path / "blob.bin"
        path.write_bytes(bytes(range(256)) * 4)
        result = _read(path)
        assert "binary file" in result
        assert "bytes" in result
        assert "\ufffd" not in result


class TestTextBehaviorUnchanged:
    def test_plain_text_keeps_line_numbers_and_no_header(self, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("第一行\nsecond\n", encoding="utf-8")
        result = _read(path)
        assert result == "1: 第一行\n2: second"

    def test_utf16_with_bom_decodes_instead_of_binary_error(self, tmp_path):
        path = tmp_path / "utf16.txt"
        path.write_bytes("你好\n世界\n".encode("utf-16"))
        result = _read(path)
        assert "1: 你好" in result
        assert "2: 世界" in result

