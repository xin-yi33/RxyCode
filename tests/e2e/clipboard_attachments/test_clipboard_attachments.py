"""Real Windows clipboard → OpenTUI → stdio appserver → AgentV2 acceptance."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest


pytestmark = [pytest.mark.serial, pytest.mark.pty, pytest.mark.e2e]

# Import no Windows APIs or native helper modules before this opt-in guard.
if os.name != "nt":
    pytest.skip("real OS clipboard acceptance requires Windows", allow_module_level=True)
if os.environ.get("RXYCODE_CLIPBOARD_E2E") != "1":
    pytest.skip(
        "set RXYCODE_CLIPBOARD_E2E=1 for the serial global-clipboard suite",
        allow_module_level=True,
    )

from .clipboard_broker import ClipboardBroker, ClipboardSuiteMutex  # noqa: E402
from .harness import (  # noqa: E402
    PROJECT_ROOT,
    ConPTYApp,
    _safe_environment,
    _write_config,
    compact_terminal_text,
    create_run,
    preflight_runtime_dependencies,
    summarize_task_store,
    verify_checkout_binding,
)
from .provider import LocalOpenAIProvider, ProviderCase  # noqa: E402


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@pytest.fixture
def _clipboard_suite_mutex():
    with ClipboardSuiteMutex():
        yield


def _capture_and_submit(
    *,
    app: ConPTYApp,
    provider: LocalOpenAIProvider,
    broker: ClipboardBroker,
    case: ProviderCase,
    hotkey: str,
    chip_names: tuple[str, ...],
    prompt: str,
    request_marker: str,
    final_marker: str,
    set_clipboard,
    image_pixel: list[int] | None = None,
    final_claim_marker: str | None = None,
) -> dict[str, Any]:
    provider.set_case(case)
    set_started = time.monotonic()
    set_clipboard()
    set_elapsed_ms = (time.monotonic() - set_started) * 1000

    chip_start = app.chunk_count()
    hotkey_started = time.monotonic()
    app.write(hotkey)
    visible = ""
    for name in chip_names:
        _when, visible = app.wait_for(name, timeout=1.0, after_chunks=chip_start)
    hotkey_to_chip_ms = (time.monotonic() - hotkey_started) * 1000

    before_requests = len(provider.requests)
    app.write(prompt)
    final_start = app.chunk_count()
    entered = time.monotonic()
    response_deadline = entered + 70
    app.write("\r")
    final_seen, _ = app.wait_for(
        final_marker,
        timeout=max(0.0, response_deadline - time.monotonic()),
        after_chunks=final_start,
    )
    visible_claim = None
    if final_claim_marker is not None:
        normalized_claim = compact_terminal_text(final_claim_marker)
        _claim_seen, visible_claim = app.wait_for(
            normalized_claim,
            timeout=max(0.0, response_deadline - time.monotonic()),
            after_chunks=final_start,
            normalize=compact_terminal_text,
        )

    request = provider.wait_for_request(
        lambda row: request_marker in str(row.get("latest_user_text") or ""),
        timeout=max(0.0, response_deadline - time.monotonic()),
        after=before_requests,
    )
    row: dict[str, Any] = {
        "case": case.name,
        "clipboard_set_ms": round(set_elapsed_ms, 2),
        "hotkey_to_chip_ms": round(hotkey_to_chip_ms, 2),
        "hotkey_to_chip_under_1s": hotkey_to_chip_ms <= 1000,
        "hotkey_to_chip_feedback_under_100ms": hotkey_to_chip_ms <= 100,
        "enter_to_final_ms": round((final_seen - entered) * 1000, 2),
        "visible_chip_names": list(chip_names),
        "request_marker_seen": request_marker in str(request.get("latest_user_text") or ""),
        "final_marker_seen": final_marker in app.text_since(final_start),
    }
    assert row["final_marker_seen"], "the provider Final marker was not visible in the TUI"
    if final_claim_marker is not None:
        row["final_claim_seen"] = normalized_claim in compact_terminal_text(visible_claim or "")
        assert row["final_claim_seen"], "the full provider disclaimer was not visible in the TUI"
    if image_pixel is not None:
        observations = request.get("image_observations") or []
        row["image_observations"] = observations
        assert observations, "the provider request did not contain a native image payload"
        assert all(item.get("valid_data_image") for item in observations), observations
        assert all(item.get("format") == "PNG" for item in observations), observations
        assert all(item.get("pixel_0_0_rgb") == image_pixel for item in observations), observations
    return row


def test_real_clipboard_four_core_compound_scenarios(_clipboard_suite_mutex) -> None:
    """Runs one serial session and always restores the user's original clipboard."""
    assert os.environ.get("RXYCODE_CLIPBOARD_E2E") == "1"
    # Resolve/validate all launch dependencies before creating the clipboard
    # broker; a missing Bun/Python executable must fail before any snapshot.
    bun, python = preflight_runtime_dependencies()
    requested_output = os.environ.get("RXYCODE_CLIPBOARD_E2E_OUTPUT", "").strip()
    parent = Path(requested_output) if requested_output else Path(tempfile.gettempdir()) / "rxycode-clipboard-e2e"
    run_dir, run_info = create_run(parent)
    evidence = run_dir / "evidence"
    result: dict[str, Any] = {
        "scope": "real Windows clipboard + OpenTUI ConPTY + stdio appserver + AgentV2",
        "provider_kind": "loopback TLS control provider; not a live model",
        "run_dir": str(run_dir),
        "clipboard_restored": False,
        "synthetic_usage_only": True,
        "runtime_executables": {"bun": str(bun), "python": str(python)},
        "scenarios": [],
    }
    provider = LocalOpenAIProvider(run_dir / "runtime", evidence)
    app: ConPTYApp | None = None
    broker: ClipboardBroker | None = None
    cleanup: dict[str, Any] | None = None
    task_summary: dict[str, Any] | None = None

    try:
        tls_result = provider.verify_tls_client()
        _write_json(evidence / "provider-tls-self-check.json", tls_result)
        env = _safe_environment(provider, run_dir, python=python)
        config_path = _write_config(env, provider)
        provenance = verify_checkout_binding(env, python=python)
        _write_json(evidence / "checkout-provenance.json", provenance)
        result["checkout_provenance"] = provenance
        result["provider_tls"] = tls_result
        result["config_path"] = str(config_path)
        result["skills_roots"] = {
            "user_skill_root": env["RXYCODE_SKILLS_DIR"],
            "all_skill_roots": env["RXYCODE_SKILLS_DIRS"],
            "isolated_empty_root": True,
        }

        workspace = Path(env["RXYCODE_WORKSPACE_ROOT"])
        file_one = workspace / "材料 一号.txt"
        file_two = workspace / "second file.txt"
        file_one.write_text("FILE_CONTENT_VERIFIED_001\nSynthetic clipboard fixture.\n", encoding="utf-8")
        file_two.write_text("SECOND_FILE_FIXTURE_002\n", encoding="utf-8")
        pdf = workspace / "brief reference.pdf"
        video = workspace / "clip reference.mp4"
        pdf.write_bytes(b"%PDF-1.4\nSYNTHETIC_REFERENCE_ONLY\n%%EOF\n")
        # Minimal ISO-BMFF ftyp + binary mdat classification fixture; this is
        # not a complete/playable video and is not a decoding assertion.
        video.write_bytes(
            b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42"
            b"\x00\x00\x00\x0cmdat\x00\xff\xfe\x80"
        )

        app = ConPTYApp(run_dir, env, bun=bun)
        result["pty_pid"] = app.pid
        result["ready_elapsed_s"] = round(time.monotonic() - run_info["created_monotonic"], 3)
        app.wait_for("输入指令或需求...", timeout=60)

        # The STA helper must first retain and hash every original format. If
        # any format cannot be copied/fingerprinted, construction fails here,
        # before the first clipboard write below.
        with ClipboardBroker(evidence) as broker:
            result["clipboard_backup"] = broker.backup

            file_case = ProviderCase(
                name="multi-file-drop-read-tool-final",
                read_marker="E2E_READ_FILE_DROP_001",
                read_path=str(file_one.resolve()),
                file_marker="FILE_CONTENT_VERIFIED_001",
                final_text="E2E_FINAL_FILE_DROP_OK",
            )
            file_row = _capture_and_submit(
                app=app,
                provider=provider,
                broker=broker,
                case=file_case,
                hotkey="\x1bv",
                chip_names=(file_one.name, file_two.name),
                prompt="Read the attached file with the read tool; request marker E2E_READ_FILE_DROP_001",
                request_marker="E2E_READ_FILE_DROP_001",
                final_marker="E2E_FINAL_FILE_DROP_OK",
                set_clipboard=lambda: broker.set_files([file_one, file_two]),
            )
            file_requests = provider.requests
            file_followup = next(
                (
                    row
                    for row in file_requests
                    if any(message.get("role") == "tool" for message in row.get("body", {}).get("messages", []))
                    and "E2E_READ_FILE_DROP_001" in str(row.get("latest_user_text") or "")
                ),
                None,
            )
            assert file_followup is not None, "provider never received the real read tool result"
            assert any(
                decision.get("tool_call") == "read"
                for decision in provider.decision_trace
                if decision.get("case") == file_case.name
            ), "AgentV2 did not route the provider's read call"
            assert any(
                decision.get("tool_result_marker_seen")
                for decision in provider.decision_trace
                if decision.get("case") == file_case.name
            ), "the synthetic file marker did not return through the real read tool result"
            file_row["read_tool_result_round_trip"] = True
            result["scenarios"].append(file_row)

            rgb = bytes([23, 167, 91] * 24 * 32)
            image_case = ProviderCase(
                name="dib-screenshot-to-png-native-image-final",
                read_marker="",
                read_path=str(file_one.resolve()),
                file_marker="",
                final_text="E2E_FINAL_SCREENSHOT_IMAGE_OK",
                require_image=True,
            )
            image_row = _capture_and_submit(
                app=app,
                provider=provider,
                broker=broker,
                case=image_case,
                hotkey="\x1bv",
                chip_names=("剪贴板图片.png",),
                prompt="Inspect this pasted screenshot. Request marker E2E_SCREENSHOT_IMAGE_002",
                request_marker="E2E_SCREENSHOT_IMAGE_002",
                final_marker="E2E_FINAL_SCREENSHOT_IMAGE_OK",
                set_clipboard=lambda: broker.set_image(32, 24, rgb),
                image_pixel=[23, 167, 91],
            )
            result["scenarios"].append(image_row)

            url = "https://example.test/clipboard-e2e?marker=URL_ONCE_003"
            text_case = ProviderCase(
                name="unicode-url-and-bracketed-multiline-single-prompt",
                read_marker="",
                read_path=str(file_one.resolve()),
                file_marker="",
                final_text="E2E_FINAL_PASTED_TEXT_OK",
            )
            provider.set_case(text_case)
            text_set_started = time.monotonic()
            broker.set_text(url)
            text_set_elapsed_ms = (time.monotonic() - text_set_started) * 1000
            text_start = app.chunk_count()
            altv_started = time.monotonic()
            app.write("\x1bv")
            text_clip_visible, _ = app.wait_for(url, timeout=1.0, after_chunks=text_start)
            text_hotkey_to_clip_ms = (text_clip_visible - altv_started) * 1000
            # Exercise bracketed terminal paste without invoking the OS helper
            # a second time. LF is the ConPTY Shift+Enter representation.
            app.write("\x1b[200~FIRST_LINE_E2E_003\nSECOND_LINE_E2E_003\x1b[201~")
            app.write("\n")
            app.write("AFTER_SHIFT_ENTER_E2E_003 E2E_TEXT_PROMPT_003")
            before_text_requests = len(provider.requests)
            text_entered = time.monotonic()
            app.write("\r")
            text_final_at, _ = app.wait_for("E2E_FINAL_PASTED_TEXT_OK", timeout=70)
            text_request = provider.wait_for_request(
                lambda row: "E2E_TEXT_PROMPT_003" in str(row.get("latest_user_text") or ""),
                timeout=70,
                after=before_text_requests,
            )
            text_payload = str(text_request.get("latest_user_text") or "")
            # Inserting the submit marker before Enter makes single-dispatch
            # verifiable even if the TUI's visible transcript scrolls.
            # The provider request itself is the authoritative prompt trace.
            assert text_payload.count(url) == 1, "clipboard URL was duplicated or lost in the submitted prompt"
            assert text_payload.count("FIRST_LINE_E2E_003") == 1
            assert text_payload.count("SECOND_LINE_E2E_003") == 1
            assert text_payload.count("AFTER_SHIFT_ENTER_E2E_003") == 1
            assert text_payload.count("E2E_TEXT_PROMPT_003") == 1
            result["scenarios"].append(
                {
                    "case": text_case.name,
                    "clipboard_set_ms": round(text_set_elapsed_ms, 2),
                    "hotkey_to_clipboard_text_ms": round(text_hotkey_to_clip_ms, 2),
                    "hotkey_to_clipboard_text_under_1s": text_hotkey_to_clip_ms <= 1000,
                    "hotkey_to_clipboard_text_feedback_under_100ms": text_hotkey_to_clip_ms <= 100,
                    "text_markers_once": True,
                    "bracketed_multiline": True,
                    "shift_enter_newline": True,
                    "enter_to_final_ms": round((text_final_at - text_entered) * 1000, 2),
                    "request_marker_seen": True,
                }
            )

            ref_case = ProviderCase(
                name="pdf-video-reference-only-final",
                read_marker="",
                read_path=str(file_one.resolve()),
                file_marker="",
                final_text="E2E_FINAL_REFERENCE_ONLY: only file references were supplied; no native PDF/video content was inspected.",
            )
            ref_row = _capture_and_submit(
                app=app,
                provider=provider,
                broker=broker,
                case=ref_case,
                hotkey="\x1bv",
                chip_names=(pdf.name, video.name),
                prompt="State honestly whether you received file references or extracted PDF/video contents. Request marker E2E_PDF_VIDEO_REFERENCE_004",
                request_marker="E2E_PDF_VIDEO_REFERENCE_004",
                final_marker="E2E_FINAL_REFERENCE_ONLY",
                set_clipboard=lambda: broker.set_files([pdf, video]),
                final_claim_marker="only file references were supplied; no native PDF/video content was inspected.",
            )
            ref_request = provider.wait_for_request(
                lambda row: "E2E_PDF_VIDEO_REFERENCE_004" in str(row.get("latest_user_text") or ""),
                timeout=5,
            )
            ref_latest = str(ref_request.get("latest_user_text") or "")
            assert f"PDF file reference {pdf.name}:" in ref_latest, "PDF bytes were not classified as a PDF reference"
            assert f"Video file reference {video.name}:" in ref_latest, "MP4 ftyp bytes were not classified as a video reference"
            # The provider records image observations from this request's
            # latest user message only; earlier turns are left intact.
            assert not (ref_request.get("image_observations") or []), "PDF/video turn inherited an image observation"
            ref_row["file_references_visible_to_provider"] = [pdf.name, video.name]
            ref_row["inline_image_payloads"] = 0
            ref_row["control_provider_final_disclaims_native_document_understanding"] = ref_row["final_claim_seen"]
            assert ref_row["final_claim_seen"], "the deterministic control-provider disclaimer was not visible in the TUI"
            result["scenarios"].append(ref_row)

            # Provider traces contain only test prompts/fixtures. The user's
            # home path must never appear through a leaked skill-root scan.
            provider_text = json.dumps(provider.request_trace, ensure_ascii=False)
            home_path = str(Path.home())
            assert home_path.casefold() not in provider_text.casefold(), "a real user profile path leaked into provider input"

        result["clipboard_restored"] = broker.restored
        assert broker.restored, "clipboard restoration was not verified"
        result["synthetic_provider_requests"] = len(provider.requests)
        result["provider_request_trace"] = str(provider.save_trace())
        assert result["synthetic_provider_requests"] >= 5, "expected tool round-trip plus four real provider turns"

    finally:
        if broker is not None and not broker.restored:
            try:
                result["clipboard_backup"] = broker.backup
                broker.save_evidence()
                if broker.external_modification:
                    result["clipboard_status"] = "external-modification"
                    result["clipboard_restored"] = False
                    result["clipboard_external_sequence"] = broker.external_sequence
                else:
                    result["clipboard_status"] = "restore-unverified"
                    result["clipboard_restored"] = False
                    # The context manager already made its bounded restore
                    # attempt. Never retry from this outer cleanup path.
                    if broker.process.poll() is None:
                        broker.process.terminate()
                        try:
                            broker.process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            broker.process.kill()
                            broker.process.wait(timeout=2)
            except BaseException as exc:
                result["clipboard_restore_error_type"] = type(exc).__name__
                if broker.process.poll() is None:
                    # Exact STA helper started by this test only.
                    broker.process.terminate()
                    try:
                        broker.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        broker.process.kill()
                        broker.process.wait(timeout=2)
        if app is not None:
            try:
                cleanup = app.close()
                result["process_cleanup"] = cleanup
            except BaseException as exc:
                result["process_cleanup_error_type"] = type(exc).__name__
        try:
            provider.save_trace()
        except BaseException as exc:
            result["provider_trace_error_type"] = type(exc).__name__
        provider.close()
        try:
            task_summary = summarize_task_store(Path(run_dir / "data"), evidence / "task-events.json")
            result["task_summary"] = task_summary
        except BaseException as exc:
            result["task_summary_error_type"] = type(exc).__name__
        result["run_finished_monotonic"] = time.monotonic()
        result["process_cleanup"] = cleanup or result.get("process_cleanup")
        if broker is not None:
            result["clipboard_restored"] = broker.restored
        if broker is not None and broker.restored:
            result["clipboard_status"] = "restored"
        elif broker is not None and broker.external_modification:
            result["clipboard_status"] = "external-modification"
            result["clipboard_restored"] = False
        elif broker is not None:
            result.setdefault("clipboard_status", "restore-unverified")
        _write_json(evidence / "acceptance-summary.json", result)

    assert result["clipboard_restored"] is True, "clipboard must be restored before suite completion"
    assert cleanup is not None and all(item["exited"] for item in cleanup["cleanup"]), "a child process created by this test did not exit"
    assert task_summary and task_summary.get("available"), "real appserver task/event trace was not persisted"
    event_names = {row.get("method") for row in task_summary.get("events", [])}
    assert "event/final" in event_names, "appserver task store contains no final event"
    assert "event/tool_begin" in event_names and "event/tool_end" in event_names, "real tool lifecycle events were not observed"
