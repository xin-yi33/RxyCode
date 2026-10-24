"""WEB-W11 preview kinds: every worker-registered deliverable declares one.

The web app only renders a preview button when the artifact manifest's
``preview_kind`` is non-null; the worker used to set it only for ``.html`` /
``.htm``, so images, PDFs, Office documents, text, media and archives could
never be previewed even though the requirement is "所有类型的文件都可以预览".

The worker now delegates every registration to the Lead-owned taxonomy
(``rxycode_server.previews.kinds.preview_kind_for``) so the manifest and the
preview conversion job can never disagree about what a file is, and no
registered deliverable is left with a null kind.

No Docker/Postgres/S3: the mapping table drives the real worker helper and the
wiring test monkeypatches ``store_artifact``.
"""

from __future__ import annotations

import mimetypes
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-server" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO,
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def _worker_content_type(relative_path: str) -> str:
    """The exact content type ``_register_run_artifacts`` feeds the classifier."""
    return mimetypes.guess_type(relative_path)[0] or "application/octet-stream"


#: (filename, expected kind, content-type override; ``None`` = derive the way
#: the worker does with ``mimetypes``). One row per deliverable family the
#: preview pipeline must cover.
_CASES = (
    ("report.html", "frontend_static", None),
    ("notes.md", "frontend_static", None),
    ("app.py", "frontend_static", None),
    ("shot.PNG", "image", None),
    ("logo.svg", "image", None),
    ("doc.pdf", "pdf", None),
    ("报告.docx", "office", None),
    ("sheet.xlsx", "office", None),
    ("deck.pptx", "office", None),
    ("case.odt", "office", None),
    ("clip.mp4", "media", None),
    ("voice.mp3", "media", None),
    ("bundle.zip", "archive", None),
    ("pkg.tar.gz", "archive", None),
    ("firmware.bin", "binary", None),
    ("artifact-without-extension", "binary", "application/octet-stream"),
)
_IDS = (
    "html",
    "markdown",
    "source-code",
    "png-uppercase-ext",
    "svg",
    "pdf",
    "docx-unicode-name",
    "xlsx",
    "pptx",
    "odt",
    "mp4-video",
    "mp3-audio",
    "zip",
    "tar-gz",
    "bin",
    "no-extension-octet-stream",
)


@pytest.mark.unit
@pytest.mark.parametrize(("filename", "expected", "content_type"), _CASES, ids=_IDS)
def test_worker_declares_a_kind_for_every_deliverable(
    filename: str, expected: str, content_type: str | None
) -> None:
    """Every manifest kind is non-null and comes from the shared taxonomy."""
    from rxycode_server.previews.kinds import ALL_KINDS
    from rxycode_worker.drain import _artifact_preview_kind

    ctype = content_type if content_type is not None else _worker_content_type(filename)
    kind = _artifact_preview_kind(filename, ctype)
    assert kind == expected
    assert kind in ALL_KINDS  # never None, never an off-taxonomy value


@pytest.mark.unit
def test_worker_helper_is_the_shared_classifier() -> None:
    """The worker must not re-derive kinds: output equals preview_kind_for."""
    from rxycode_server.previews.kinds import preview_kind_for
    from rxycode_worker.drain import _artifact_preview_kind

    names = (
        *(case[0] for case in _CASES),
        "Makefile",
        "data.csv",
        "config.yaml",
        "README",
        "archive.7z",
        "legacy.doc",
    )
    content_types = (None, "application/octet-stream", "image/png", "text/plain")
    for name in names:
        for ctype in content_types:
            assert _artifact_preview_kind(name, ctype) == preview_kind_for(name, ctype)


@pytest.mark.unit
def test_classifier_failure_never_breaks_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing/broken classifier degrades to ``binary``, never raises/None."""
    from rxycode_server.previews.kinds import ALL_KINDS
    from rxycode_worker.drain import _ARTIFACT_PREVIEW_KIND_FALLBACK, _artifact_preview_kind

    # ``None`` in sys.modules makes the lazy ``from ... import`` raise
    # ImportError, simulating a deployment without the server sources.
    monkeypatch.setitem(sys.modules, "rxycode_server.previews.kinds", None)
    kind = _artifact_preview_kind("report.html", "text/html")
    assert kind == "binary"
    assert kind in ALL_KINDS
    assert _ARTIFACT_PREVIEW_KIND_FALLBACK == "binary"


@pytest.mark.unit
def test_register_run_artifacts_persists_preview_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wiring: registration passes a real kind for html and png (no S3/DB)."""
    import rxycode_server.artifacts.service as artifacts_service
    from rxycode_server.previews.kinds import ALL_KINDS
    from rxycode_worker.drain import _register_run_artifacts

    captured: list[dict[str, object]] = []

    def fake_store_artifact(database_url: str, **kwargs: object) -> dict[str, object]:
        captured.append({"database_url": database_url, **kwargs})
        return {"artifact_id": f"artifact-{len(captured)}"}

    monkeypatch.setattr(artifacts_service, "store_artifact", fake_store_artifact)
    for name in (
        "RXYCODE_S3_ENDPOINT",
        "RXYCODE_S3_BUCKET",
        "RXYCODE_S3_ACCESS_KEY",
        "RXYCODE_S3_SECRET_KEY",
    ):
        monkeypatch.setenv(name, "test-value")

    deliverables = {
        "report.html": b"<h1>report</h1>",
        "shot.PNG": b"\x89PNG\r\n\x1a\n",
        "notes.md": b"# notes\n",
    }
    for name, payload in deliverables.items():
        (tmp_path / name).write_bytes(payload)

    cfg = SimpleNamespace(database_url="postgresql+psycopg://unused/unused")
    registered = _register_run_artifacts(cfg, "tenant-1", "run-1", tmp_path, {})

    assert registered == len(deliverables)
    kinds = {str(row["filename"]): row["preview_kind"] for row in captured}
    assert kinds == {
        "report.html": "frontend_static",
        "shot.PNG": "image",
        "notes.md": "frontend_static",
    }
    # Every registered deliverable carries a manifest kind (the web app's
    # preview-button precondition) and a printable content type.
    assert all(kind in ALL_KINDS for kind in kinds.values())
    assert all(row["content_type"] for row in captured)
    assert {row["relative_path"] for row in captured} == set(deliverables)
