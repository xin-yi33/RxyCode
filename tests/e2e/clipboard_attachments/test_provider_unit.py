"""Local provider capture regressions without starting the clipboard suite."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import threading

import pytest
from PIL import Image

from .harness import ConPTYApp, compact_terminal_text
from .provider import LocalOpenAIProvider, ProviderCase


pytestmark = pytest.mark.unit


class _FakePTY:
    @staticmethod
    def isalive() -> bool:
        return True


class _WaitObservedCondition(threading.Condition):
    def __init__(self) -> None:
        super().__init__()
        self.wait_started = threading.Event()

    def wait(self, timeout: float | None = None) -> bool:
        self.wait_started.set()
        return super().wait(timeout)


def _fake_terminal_app(
    chunks: list[str], condition: threading.Condition | None = None
) -> ConPTYApp:
    app = object.__new__(ConPTYApp)
    app._condition = condition or threading.Condition()
    app._chunks = [{"monotonic": float(index), "text": chunk} for index, chunk in enumerate(chunks)]
    app.pty = _FakePTY()
    return app


def test_terminal_wait_accepts_full_claim_after_final_across_csi_cursor_chunks() -> None:
    final_marker = "E2E_FINAL_REFERENCE_ONLY"
    claim = "only file references were supplied; no native PDF/video content was inspected."
    condition = _WaitObservedCondition()
    app = _fake_terminal_app([final_marker + ": ", "only"], condition)
    later_chunks = [
        "\x1b[1Cfile\x1b[1Creferences\x1b[1Cwere\x1b[1Csupplied;",
        "\x1b[1Cno\x1b[1Cnative\x1b[1CPDF/video\x1b[1Ccontent\x1b[1Cwas\x1b[1Cinspected.",
    ]
    append_errors: list[str] = []

    def append_claim_after_wait_starts() -> None:
        if not condition.wait_started.wait(timeout=1):
            append_errors.append("wait_for never waited for the later claim chunks")
            return
        with condition:
            app._chunks.extend(
                {"monotonic": 10 + index, "text": chunk}
                for index, chunk in enumerate(later_chunks)
            )
            condition.notify_all()

    final_seen, _ = app.wait_for(final_marker, timeout=0.2)
    writer = threading.Thread(target=append_claim_after_wait_starts)
    writer.start()
    try:
        claim_seen, visible = app.wait_for(
            compact_terminal_text(claim),
            timeout=1,
            normalize=compact_terminal_text,
        )
    finally:
        writer.join(timeout=1)

    assert not writer.is_alive()
    assert not append_errors
    assert claim_seen >= final_seen
    assert compact_terminal_text(claim) in compact_terminal_text(visible)


def test_terminal_wait_rejects_claim_missing_a_word() -> None:
    claim = "only file references were supplied; no native PDF/video content was inspected."
    app = _fake_terminal_app(
        [
            "E2E_FINAL_REFERENCE_ONLY: only file references were supplied; "
            "no native PDF/video was inspected."
        ]
    )

    with pytest.raises(TimeoutError, match="did not show"):
        app.wait_for(
            compact_terminal_text(claim),
            timeout=0.01,
            normalize=compact_terminal_text,
        )


def test_wait_for_request_returns_decoded_image_observations_without_persisting_image_data() -> None:
    # Exercise only the provider's in-memory capture path: no server, subprocess,
    # OS clipboard, or real E2E opt-in is involved.
    provider = object.__new__(LocalOpenAIProvider)
    provider._condition = threading.Condition()
    provider._case = ProviderCase(
        name="local-image-capture",
        read_marker="",
        read_path="",
        file_marker="",
        final_text="LOCAL_IMAGE_CAPTURE_OK",
        require_image=True,
    )
    provider._requests = []
    provider._request_trace = []
    provider._decision_trace = []

    image = Image.new("RGB", (2, 3), (12, 34, 56))
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG")
    encoded_image = base64.b64encode(image_bytes.getvalue()).decode("ascii")
    marker = "LOCAL_PROVIDER_IMAGE_CAPTURE_001"
    body = {
        "model": "synthetic-local-model",
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": marker},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded_image}"},
                    },
                ],
            }
        ],
    }

    decision = provider._capture_and_decide(body)
    request = provider.wait_for_request(
        lambda row: marker in str(row.get("latest_user_text") or ""),
        timeout=0.1,
    )

    observations = request.get("image_observations")
    assert decision["text"] == "LOCAL_IMAGE_CAPTURE_OK"
    assert observations == [
        {
            "valid_data_image": True,
            "mime": "image/png",
            "format": "PNG",
            "size": [2, 3],
            "pixel_0_0_rgb": [12, 34, 56],
            "sha256": hashlib.sha256(image_bytes.getvalue()).hexdigest(),
            "bytes": len(image_bytes.getvalue()),
        }
    ]
    assert encoded_image not in json.dumps(provider.request_trace, ensure_ascii=False)
