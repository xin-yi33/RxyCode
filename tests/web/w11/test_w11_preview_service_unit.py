"""WEB-W11 preview service: job classification and conversion dispatch.

The preview job and the artifact manifest must never disagree about what a
file is: the service classifies with the shared taxonomy
(:func:`rxycode_server.previews.kinds.preview_kind_for`), then dispatches to the
pure converters. These tests cover those two seams without Postgres/S3 (a live
job is exercised by ``test_w11_c09_unit``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_SERVER_SRC = REPO / "packages" / "rxycode-server" / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

from rxycode_server.persistence.models import Artifact  # noqa: E402
from rxycode_server.previews import converters, kinds, service  # noqa: E402

pytestmark = pytest.mark.unit


def _artifact(filename: str, content_type: str = "", relative_path: str = "") -> Artifact:
    """An unsaved model row — enough for the pure classification helpers."""
    return Artifact(
        filename=filename,
        relative_path=relative_path,
        content_type=content_type,
        object_key=f"tenants/t/runs/r/{filename or 'file'}",
        sha256="0" * 64,
        size=0,
        run_id="run-1",
        availability="available",
    )


_CASES = (
    (("report.html", "text/html"), kinds.FRONTEND_STATIC),
    (("notes.md", "text/markdown"), kinds.FRONTEND_STATIC),
    (("app.py", "text/x-python"), kinds.FRONTEND_STATIC),
    (("shot.PNG", "image/png"), kinds.IMAGE),
    (("doc.pdf", "application/pdf"), kinds.PDF),
    (
        (
            "报告.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        kinds.OFFICE,
    ),
    (
        ("sheet.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        kinds.OFFICE,
    ),
    (
        ("deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        kinds.OFFICE,
    ),
    (("case.odt", "application/vnd.oasis.opendocument.text"), kinds.OFFICE),
    (("clip.mp4", "video/mp4"), kinds.MEDIA),
    (("voice.mp3", "audio/mpeg"), kinds.MEDIA),
    (("bundle.zip", "application/zip"), kinds.ARCHIVE),
    (("pkg.tar.gz", "application/gzip"), kinds.ARCHIVE),
    (("firmware.bin", "application/octet-stream"), kinds.BINARY),
    (("legacy.doc", "application/msword"), kinds.BINARY),
    (("artifact-without-extension", "application/octet-stream"), kinds.BINARY),
)


@pytest.mark.parametrize(("name", "content_type"), [case[0] for case in _CASES])
def test_job_kind_is_the_shared_taxonomy(name: str, content_type: str) -> None:
    artifact = _artifact(name, content_type)
    kind = service._classify(artifact)
    assert kind == kinds.preview_kind_for(name, content_type)
    assert kind in kinds.ALL_KINDS


def test_relative_path_is_the_filename_fallback() -> None:
    artifact = _artifact("", "application/octet-stream", relative_path="nested/photo.jpeg")
    assert service._classify(artifact) == kinds.IMAGE


def test_streamed_kinds_are_images_and_media_only() -> None:
    assert set(service._STREAMED_KINDS) == {kinds.IMAGE, kinds.MEDIA}


def test_build_document_serves_html_as_is_but_escapes_text() -> None:
    html_source = b"<html><body><h1>hi</h1></body></html>"
    html_artifact = _artifact("page.html", "text/html")
    assert (
        service._build_document(
            artifact=html_artifact, kind=kinds.FRONTEND_STATIC, source=html_source
        )
        == html_source
    )

    text_artifact = _artifact("notes.md", "text/markdown")
    text_page = service._build_document(
        artifact=text_artifact, kind=kinds.FRONTEND_STATIC, source=b"<b>not markup</b>"
    )
    assert b"&lt;b&gt;not markup&lt;/b&gt;" in text_page
    assert b"<b>not markup</b>" not in text_page


def test_build_document_dispatches_binary_and_archive() -> None:
    binary_page = service._build_document(
        artifact=_artifact("firmware.bin", "application/octet-stream"),
        kind=kinds.BINARY,
        source=b"\x00\x01\x02",
    )
    assert b"SHA-256" in binary_page

    archive_page = service._build_document(
        artifact=_artifact("bundle.zip", "application/zip"),
        kind=kinds.ARCHIVE,
        source=_zip_bytes(),
    )
    assert b"readme.txt" in archive_page


def test_build_document_reports_converter_errors() -> None:
    with pytest.raises(converters.ConverterError):
        service._build_document(
            artifact=_artifact("broken.pdf", "application/pdf"),
            kind=kinds.PDF,
            source=b"not a pdf",
        )


def test_read_source_enforces_the_converted_source_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeBody:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self, _size: int) -> bytes:
            return self._payload

    class _FakeClient:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def get_object(self, Bucket, Key):  # noqa: N803 - boto3 signature
            return {"Body": _FakeBody(self._payload)}

    artifact = _artifact("big.bin", "application/octet-stream")
    monkeypatch.setattr(service, "_client", lambda *args, **kwargs: _FakeClient(b"x" * 10))
    assert (
        service._read_source(
            artifact=artifact,
            s3_endpoint="e",
            bucket="b",
            access_key="k",
            secret_key="s",
        )
        == b"x" * 10
    )

    monkeypatch.setattr(
        service,
        "_client",
        lambda *args, **kwargs: _FakeClient(b"x" * (service._MAX_SOURCE_BYTES + 1)),
    )
    assert (
        service._read_source(
            artifact=artifact,
            s3_endpoint="e",
            bucket="b",
            access_key="k",
            secret_key="s",
        )
        is None
    )


def _zip_bytes() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("readme.txt", "hello")
    return buffer.getvalue()
