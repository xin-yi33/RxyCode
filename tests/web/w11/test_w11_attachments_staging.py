"""Worker attachment staging: Unicode filenames survive, unsafe parts do not.

The cloud run in evidence listed imports/<id>/____-_3_ HDFS___________.docx:
the worker's ASCII-only filename sanitizer destroyed the user's Chinese
filename. These tests pin the parent staging step and the child import step
together (the staged manifest is the handoff between them).
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

DOCX_NAME = "实验报告-第3章 HDFS分布式文件系统_阮心一.docx"


def _docx_bytes(text: str = "实验报告正文") -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>" + text + "</w:t></w:r></w:p></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def _item(attachment_id: str, filename: str, payload: bytes) -> dict[str, object]:
    return {
        "attachment_id": attachment_id,
        "filename": filename,
        "object_key": f"tenants/t1/attachments/{attachment_id}/{filename}",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


class _FakeBlobStore:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    def open_read(self, object_key: str):
        return io.BytesIO(self._blobs[object_key])


@pytest.fixture
def blob_blobs(monkeypatch) -> dict[str, bytes]:
    """Patch the attachment blob store used inside _stage_attachments."""
    blobs: dict[str, bytes] = {}
    import rxycode_server.attachments.store as store_module

    monkeypatch.setattr(store_module, "blob_config_from_env", lambda: object())
    monkeypatch.setattr(
        store_module, "open_store", lambda _config: _FakeBlobStore(blobs)
    )
    return blobs


def _stage(tmp_path: Path, items: list[dict[str, object]], blobs: dict[str, bytes]):
    from rxycode_worker.drain import _stage_attachments

    for item in items:
        blobs.setdefault(str(item["object_key"]), _docx_bytes())
    att_dir = tmp_path / "att"
    records = _stage_attachments(att_dir, items)
    return att_dir, records


class TestSafeAttachmentFilename:
    def test_preserves_chinese_and_spaces(self):
        from rxycode_worker.drain import _safe_attachment_filename

        assert _safe_attachment_filename(DOCX_NAME) == DOCX_NAME

    def test_neutralizes_path_separators_and_control_chars(self):
        from rxycode_worker.drain import _safe_attachment_filename

        safe = _safe_attachment_filename("../../etc/passwd\x01.txt")
        assert "/" not in safe
        assert "\\" not in safe
        assert "\x01" not in safe
        assert safe.endswith(".txt")

    def test_dotdot_and_empty_fall_back(self):
        from rxycode_worker.drain import _safe_attachment_filename

        assert _safe_attachment_filename("..") == "attachment.bin"
        assert _safe_attachment_filename("") == "attachment.bin"
        assert _safe_attachment_filename("   ") == "attachment.bin"

    def test_windows_reserved_and_forbidden_chars(self):
        from rxycode_worker.drain import _safe_attachment_filename

        assert _safe_attachment_filename('a:b*c?d"e<f>g|h.txt') == "a_b_c_d_e_f_g_h.txt"
        assert _safe_attachment_filename("CON.txt").startswith("_CON")

    def test_long_names_keep_the_extension(self):
        from rxycode_worker.drain import _safe_attachment_filename

        safe = _safe_attachment_filename("长" * 400 + ".docx")
        assert len(safe) <= 180
        assert safe.endswith(".docx")

    def test_nfc_normalization(self):
        from rxycode_worker.drain import _safe_attachment_filename

        assert _safe_attachment_filename("e\u0301tude.docx") == "étude.docx"


class TestStageAttachments:
    def test_unicode_filename_reaches_the_staging_dir(self, tmp_path, blob_blobs):
        attachment_id = "6adb79d5" * 4
        item = _item(attachment_id, DOCX_NAME, _docx_bytes())
        att_dir, records = _stage(tmp_path, [item], blob_blobs)

        assert records[0]["status"] == "imported"
        assert records[0]["filename"] == DOCX_NAME
        staged = att_dir / attachment_id / DOCX_NAME
        assert staged.is_file()
        manifest = json.loads(
            (att_dir / "attachments.json").read_text(encoding="utf-8")
        )
        entry = manifest["attachments"][0]
        assert entry["filename"] == DOCX_NAME
        assert entry["stored_name"] == DOCX_NAME

    def test_path_traversal_stays_inside_the_staging_dir(self, tmp_path, blob_blobs):
        attachment_id = "b" * 32
        item = _item(attachment_id, "../../../etc/passwd\x01.txt", _docx_bytes())
        att_dir, records = _stage(tmp_path, [item], blob_blobs)

        assert records[0]["status"] == "imported"
        staged_files = [path for path in (tmp_path / "att").rglob("*") if path.is_file()]
        for path in staged_files:
            assert path.resolve().is_relative_to(att_dir.resolve())
        manifest = json.loads(
            (att_dir / "attachments.json").read_text(encoding="utf-8")
        )
        saved_name = manifest["attachments"][0]["stored_name"]
        assert "/" not in saved_name and "\\" not in saved_name
        assert (att_dir / attachment_id / saved_name).is_file()

    def test_duplicate_name_is_collision_safe(self, tmp_path, blob_blobs):
        attachment_id = "c" * 32
        first = _item(attachment_id, "报告.docx", _docx_bytes("一"))
        second = _item(attachment_id, "报告.docx", _docx_bytes("二"))
        first["object_key"] = "blob/first"
        second["object_key"] = "blob/second"
        blob_blobs["blob/first"] = _docx_bytes("一")
        blob_blobs["blob/second"] = _docx_bytes("二")
        att_dir, _records = _stage(tmp_path, [first, second], blob_blobs)

        names = sorted(
            path.name for path in (att_dir / attachment_id).iterdir() if path.is_file()
        )
        assert names == ["报告 (2).docx", "报告.docx"]
        manifest = json.loads(
            (att_dir / "attachments.json").read_text(encoding="utf-8")
        )
        assert [entry["stored_name"] for entry in manifest["attachments"]] == [
            "报告.docx",
            "报告 (2).docx",
        ]

    def test_attachment_id_with_separators_cannot_escape(self, tmp_path, blob_blobs):
        item = _item("../../escape", "note.txt", _docx_bytes())
        att_dir, _records = _stage(tmp_path, [item], blob_blobs)
        for path in (tmp_path / "att").rglob("*"):
            assert path.resolve().is_relative_to(att_dir.resolve())


class TestImportPromptAttachments:
    def test_child_import_keeps_unicode_path(self, tmp_path, blob_blobs):
        from rxycode_worker.drain import _import_prompt_attachments

        attachment_id = "d" * 32
        item = _item(attachment_id, DOCX_NAME, _docx_bytes())
        att_dir, _records = _stage(tmp_path, [item], blob_blobs)
        workdir = tmp_path / "work"
        workdir.mkdir()

        imported = _import_prompt_attachments(workdir, str(att_dir))

        assert len(imported) == 1
        destination = Path(imported[0]["path"])
        assert destination.is_file()
        assert destination.parent == workdir / "imports" / attachment_id
        assert destination.name == DOCX_NAME
        assert imported[0]["name"] == DOCX_NAME

    def test_legacy_manifest_without_stored_name_still_imports(
        self, tmp_path, blob_blobs
    ):
        from rxycode_worker.drain import _import_prompt_attachments

        attachment_id = "e" * 32
        att_dir = tmp_path / "att"
        staged_dir = att_dir / attachment_id
        staged_dir.mkdir(parents=True)
        (staged_dir / DOCX_NAME).write_bytes(_docx_bytes())
        (att_dir / "attachments.json").write_text(
            json.dumps(
                {"attachments": [{"attachment_id": attachment_id, "filename": DOCX_NAME}]}
            ),
            encoding="utf-8",
        )
        workdir = tmp_path / "work"
        workdir.mkdir()

        imported = _import_prompt_attachments(workdir, str(att_dir))

        assert Path(imported[0]["path"]).name == DOCX_NAME
        assert Path(imported[0]["path"]).is_file()

    def test_staged_docx_is_immediately_readable_by_the_read_tool(
        self, tmp_path, blob_blobs
    ):
        # The exact failed cloud pipeline: Unicode filename -> staged staging
        # dir -> child imports/ -> read tool extracts the docx text.
        from rxycode_worker.drain import _import_prompt_attachments

        from RxyCode.RxyCode1_1_0.tools.read import read_file

        attachment_id = "a1" * 16
        payload = _docx_bytes("HDFS 分布式文件系统正文")
        item = _item(attachment_id, DOCX_NAME, payload)
        # _stage() fills a missing blob with the default body; pin the exact
        # payload so the manifest sha256 and the staged bytes agree.
        blob_blobs[str(item["object_key"])] = payload
        att_dir, _records = _stage(tmp_path, [item], blob_blobs)
        workdir = tmp_path / "work"
        workdir.mkdir()

        imported = _import_prompt_attachments(workdir, str(att_dir))
        result = read_file(imported[0]["path"])

        assert DOCX_NAME in imported[0]["path"]
        assert "HDFS 分布式文件系统正文" in result
        assert "�" not in result

    def test_missing_staged_file_raises(self, tmp_path, blob_blobs):
        from rxycode_worker.drain import _import_prompt_attachments

        attachment_id = "f" * 32
        att_dir = tmp_path / "att"
        (att_dir / attachment_id).mkdir(parents=True)
        (att_dir / "attachments.json").write_text(
            json.dumps(
                {"attachments": [{"attachment_id": attachment_id, "filename": DOCX_NAME}]}
            ),
            encoding="utf-8",
        )
        with pytest.raises(FileNotFoundError):
            _import_prompt_attachments(tmp_path, str(att_dir))
