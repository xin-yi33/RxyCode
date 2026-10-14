from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils import clipboard_capture as capture


def test_clipboard_helper_stays_standalone_and_default_data_root_matches_config(monkeypatch, tmp_path):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "Rxy data"))
    assert capture._default_output_dir() == tmp_path / "Rxy data" / "temp" / "clipboard"
    monkeypatch.delenv("RXYCODE_DATA_DIR")
    assert capture._default_output_dir() == Path.home() / ".RxyCode" / "temp" / "clipboard"


def test_clipboard_helper_isolated_subprocess_help_avoids_utils_shadowing():
    project_root = Path(__file__).resolve().parents[2]
    helper_path = project_root / "utils" / "clipboard_capture.py"
    env = os.environ.copy()
    # Simulate the caller environment that exposed utils/queue.py shadowing.
    # Isolated mode must ignore this and the script directory while --help
    # exits before any OS clipboard access.
    env["PYTHONPATH"] = str(project_root / "utils")
    completed = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", str(helper_path), "--help"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--output-dir" in completed.stdout


def test_clipboard_file_validation_is_all_or_none_and_regular_only(tmp_path):
    selected = tmp_path / "picked.txt"
    selected.write_text("not copied", encoding="utf-8")
    result = capture._validate_clipboard_paths([str(selected)])
    assert result == [{"path": str(selected.resolve()), "name": selected.name}]
    with pytest.raises(ValueError, match="regular"):
        capture._validate_clipboard_paths([str(selected), str(tmp_path)])
    with pytest.raises(ValueError, match="unsupported"):
        capture._validate_clipboard_paths([r"\\server\share\secret.txt"])


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO regression")
def test_clipboard_fifo_is_rejected_without_blocking(tmp_path):
    fifo = tmp_path / "clipboard-fifo"
    os.mkfifo(fifo)
    started = time.monotonic()
    with pytest.raises(ValueError, match="regular"):
        capture._validate_clipboard_paths([str(fifo)])
    assert time.monotonic() - started < 0.5


def test_bitmap_clipboard_image_saves_png_with_human_label_and_exclusive_cleanup(
    tmp_path, monkeypatch
):
    Image = pytest.importorskip("PIL.Image")
    picture = Image.new("RGB", (8, 8), "red")
    item = capture._clipboard_image_to_png(picture, tmp_path)
    assert item["name"] == "剪贴板图片.png"
    output = Path(item["path"])
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    fixed_id = "a" * 32
    collision = tmp_path / f"clipboard-{fixed_id}.png"
    collision.write_bytes(b"pre-existing user file")
    monkeypatch.setattr(capture.uuid, "uuid4", lambda: SimpleNamespace(hex=fixed_id))
    with pytest.raises(FileExistsError):
        capture._clipboard_image_to_png(picture, tmp_path)
    assert collision.read_bytes() == b"pre-existing user file"


def test_clipboard_image_pixel_and_encoded_caps(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    monkeypatch.setattr(capture, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ValueError, match="pixels"):
        capture._clipboard_image_to_png(
            Image.new("RGB", (11, 1)), tmp_path
        )


def test_bounded_command_has_a_read_deadline_and_reaps_silent_child(monkeypatch):
    original_popen = subprocess.Popen
    children = []

    def tracked_popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(capture.subprocess, "Popen", tracked_popen)
    started = time.monotonic()
    data, code = capture._run_bounded(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        1024,
        timeout=0.15,
    )
    elapsed = time.monotonic() - started
    assert data == b""
    assert code == -3
    assert elapsed < 1.0
    assert children and children[0].poll() is not None
    assert children[0].stdout is not None and children[0].stdout.closed
    assert not capture._ACTIVE_CHILDREN
    assert not any(
        thread.name == "clipboard-pipe-reader" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_truncated_utf8_drops_only_an_incomplete_tail_and_keeps_marker():
    raw = ("中" * (capture.MAX_TEXT_BYTES // 3)).encode("utf-8")
    decoded = capture._decode_bounded_utf8(raw[:-1], truncated=True)
    text = capture._bound_utf8_text(decoded, truncated=True)
    assert text.endswith(capture.TEXT_TRUNCATION_MARKER)
    assert len(text.encode("utf-8")) <= capture.MAX_TEXT_BYTES
    with pytest.raises(UnicodeDecodeError):
        capture._decode_bounded_utf8(b"ok\xffbad", truncated=True)


def test_windows_utf16_clipboard_truncation_handles_chinese_and_split_emoji():
    text = "中🙂" * (capture.MAX_TEXT_BYTES // 2)
    raw = text.encode("utf-16-le")
    decoded = capture._decode_windows_clipboard_payload(
        raw[: capture.MAX_TEXT_BYTES + 2], total_size=len(raw) + 2
    )
    assert decoded.endswith(capture.TEXT_TRUNCATION_MARKER)
    assert "中🙂" in decoded
    assert len(decoded.encode("utf-8")) <= capture.MAX_TEXT_BYTES
    assert not (0xD800 <= ord(decoded[-len(capture.TEXT_TRUNCATION_MARKER) - 1]) <= 0xDBFF)


def test_main_emits_exactly_one_json_object(monkeypatch, capsys):
    monkeypatch.setattr(
        capture,
        "capture_clipboard",
        lambda _output_dir: {"kind": "text", "text": "粘贴", "attachments": []},
    )
    assert capture.main(["--output-dir", "unused"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert json.loads(out) == {"kind": "text", "text": "粘贴", "attachments": []}


def test_windows_file_list_and_text_fallback_do_not_require_pillow(monkeypatch, tmp_path):
    import builtins

    path = tmp_path / "copied.txt"
    path.write_text("copied", encoding="utf-8")
    monkeypatch.setattr(capture, "_read_windows_file_list", lambda: [str(path)])
    result = capture._capture_windows_clipboard(tmp_path / "out")
    assert result["kind"] == "attachments"
    assert result["attachments"] == [{"path": str(path.resolve()), "name": path.name}]

    monkeypatch.setattr(capture, "_read_windows_file_list", lambda: None)
    monkeypatch.setattr(capture, "_windows_clipboard_has_image", lambda: False)
    monkeypatch.setattr(capture, "_read_windows_text", lambda: "文本仍可用")
    original_import = builtins.__import__

    def import_without_pillow(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("simulated Pillow absence")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_pillow)
    text_result = capture._capture_windows_clipboard(tmp_path / "out")
    assert text_result == {"kind": "text", "text": "文本仍可用", "attachments": []}


def test_windows_clipboard_image_without_pillow_has_explicit_guidance(monkeypatch, tmp_path):
    import builtins

    monkeypatch.setattr(capture, "_read_windows_file_list", lambda: None)
    monkeypatch.setattr(capture, "_windows_clipboard_has_image", lambda: True)
    original_import = builtins.__import__

    def import_without_pillow(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("simulated Pillow absence")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_pillow)
    result = capture._capture_windows_clipboard(tmp_path)
    assert result["kind"] == "error"
    assert "Pillow is unavailable" in result["error"]
