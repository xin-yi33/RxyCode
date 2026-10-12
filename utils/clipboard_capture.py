"""One-shot, bounded OS clipboard capture for the interactive client.

Launch this standalone script with ``python -I -X utf8`` so its ``utils``
directory cannot shadow standard-library modules during startup, for example::

    python -I -X utf8 <project-root>/utils/clipboard_capture.py \
        --output-dir <client-data>/clipboard

The former non-isolated ``python <script>`` launch is deprecated (2026-10-11):
Python puts this script's directory first on ``sys.path``, where the repository's
``utils/queue.py`` can shadow stdlib ``queue`` and abort startup before any
clipboard access. This file intentionally has no project imports and emits one
JSON object on stdout for a normal capture invocation.
"""

from __future__ import annotations

import argparse
import ctypes
import io
import json
import os
import queue
import signal
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

MAX_TEXT_BYTES = 64 * 1024
MAX_FILES = 10
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_EDGE = 2048
CLIPBOARD_RETRIES = 6
CLIPBOARD_RETRY_SECONDS = 0.025
COMMAND_TIMEOUT_SECONDS = 0.9
TEXT_TRUNCATION_MARKER = "\n[clipboard text truncated at 64 KiB]"
_ACTIVE_CHILDREN: set[subprocess.Popen] = set()


def _clipboard_image_error(exc: BaseException, fallback: str) -> str:
    if isinstance(exc, ImportError):
        return "Clipboard image capture requires Pillow; install the declared RxyCode dependencies and retry."
    return str(exc) or fallback


def _result(kind: str, *, text: str = "", attachments: list[dict[str, str]] | None = None,
            error: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "text": text,
        "attachments": attachments or [],
    }
    if error is not None:
        payload["error"] = error
    return payload


def _default_output_dir() -> Path:
    configured = os.environ.get("RXYCODE_DATA_DIR")
    # Mirrors config.settings.DEFAULT_CONFIG_DIR ("~/.RxyCode") without
    # importing the settings module and its project-wide startup dependencies.
    data_root = Path(configured) if configured else Path.home() / ".RxyCode"
    return data_root / "temp" / "clipboard"


def _is_forbidden_path(raw_path: str) -> bool:
    value = raw_path.strip()
    lowered = value.casefold()
    return (
        not value
        or "\x00" in value
        or value.startswith(("\\\\", "//", "\\?\\", "\\.\\"))
        or lowered.startswith(("/dev/", "\\device\\", "\\\\?\\", "\\\\.\\"))
    )


def _validate_clipboard_paths(paths: list[str]) -> list[dict[str, str]]:
    if len(paths) > MAX_FILES:
        raise ValueError(f"clipboard contains more than {MAX_FILES} files")
    validated: list[dict[str, str]] = []
    for raw_path in paths:
        if not isinstance(raw_path, str) or _is_forbidden_path(raw_path):
            raise ValueError("clipboard contains an unsupported or non-local path")
        path = Path(raw_path).expanduser()
        try:
            resolved = path.resolve(strict=True)
            resolved_text = str(resolved)
            if _is_forbidden_path(resolved_text):
                raise ValueError("not a local path")
            info = resolved.stat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("not a regular file")
            # O_NONBLOCK prevents a pathname replacement with a FIFO from
            # hanging the helper. fstat verifies the opened inode, and
            # O_NOFOLLOW closes the final-component symlink race on POSIX.
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            if os.name != "nt":
                flags |= getattr(os, "O_NONBLOCK", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(resolved, flags)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError("not a regular file")
            finally:
                os.close(fd)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"clipboard file is not a readable regular file: {raw_path}") from exc
        validated.append({"path": str(resolved), "name": resolved.name})
    return validated


def _clipboard_image_to_png(image: Any, output_dir: Path) -> dict[str, str]:
    from PIL import Image

    if not isinstance(image, Image.Image):
        raise ValueError("clipboard image format is unsupported")
    width, height = image.size
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise ValueError(f"clipboard image exceeds {MAX_IMAGE_PIXELS} pixels")

    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    encoded = io.BytesIO()
    image.save(encoded, format="PNG", optimize=True)
    payload = encoded.getvalue()
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError(f"clipboard image exceeds {MAX_IMAGE_BYTES} encoded bytes")

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"clipboard-{uuid.uuid4().hex}.png"
    # Exclusive creation avoids clobbering a pre-existing path. This helper
    # only removes a partial file it created itself.
    created = False
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(payload)
    except BaseException:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return {"path": str(path.resolve()), "name": "剪贴板图片.png"}


def _read_windows_text() -> str | None:
    """Read CF_UNICODETEXT with pointer-sized Win32 signatures and hard bounds."""
    if os.name != "nt":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_int
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_int
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_int
    kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.restype = ctypes.c_size_t

    cf_unicode_text = 13
    opened = False
    for attempt in range(CLIPBOARD_RETRIES):
        if user32.OpenClipboard(None):
            opened = True
            break
        if attempt + 1 < CLIPBOARD_RETRIES:
            time.sleep(CLIPBOARD_RETRY_SECONDS)
    if not opened:
        raise OSError("Windows clipboard is busy; retry the paste")

    global_handle = None
    locked = None
    try:
        if not user32.IsClipboardFormatAvailable(cf_unicode_text):
            return None
        global_handle = user32.GetClipboardData(cf_unicode_text)
        if not global_handle:
            raise OSError("Windows clipboard text could not be read")
        size = int(kernel32.GlobalSize(global_handle))
        if size <= 0:
            return ""
        locked = kernel32.GlobalLock(global_handle)
        if not locked:
            raise OSError("Windows clipboard text could not be locked")
        # Include room for a UTF-16 NUL terminator, but never copy the full
        # global allocation when the clipboard contains a large payload.
        bounded_size = min(size, MAX_TEXT_BYTES + 2)
        raw = ctypes.string_at(locked, bounded_size)
        return _decode_windows_clipboard_payload(raw, total_size=size)
    finally:
        if locked:
            kernel32.GlobalUnlock(global_handle)
        user32.CloseClipboard()


def _read_windows_file_list() -> list[str] | None:
    """Read CF_HDROP natively so text/files work even without Pillow."""
    if os.name != "nt":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_int
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_int
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    shell32.DragQueryFileW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_wchar_p,
        ctypes.c_uint,
    ]
    shell32.DragQueryFileW.restype = ctypes.c_uint

    cf_hdrop = 15
    opened = False
    for attempt in range(CLIPBOARD_RETRIES):
        if user32.OpenClipboard(None):
            opened = True
            break
        if attempt + 1 < CLIPBOARD_RETRIES:
            time.sleep(CLIPBOARD_RETRY_SECONDS)
    if not opened:
        raise OSError("Windows clipboard is busy; retry the paste")
    try:
        if not user32.IsClipboardFormatAvailable(cf_hdrop):
            return None
        drop_handle = user32.GetClipboardData(cf_hdrop)
        if not drop_handle:
            raise OSError("Windows clipboard file list could not be read")
        count = int(shell32.DragQueryFileW(drop_handle, 0xFFFFFFFF, None, 0))
        if count > MAX_FILES:
            raise ValueError(f"clipboard contains more than {MAX_FILES} files")
        paths: list[str] = []
        for index in range(count):
            length = int(shell32.DragQueryFileW(drop_handle, index, None, 0))
            if length <= 0:
                raise ValueError("clipboard file list contains an unreadable path")
            buffer = ctypes.create_unicode_buffer(length + 1)
            copied = int(
                shell32.DragQueryFileW(drop_handle, index, buffer, length + 1)
            )
            if copied != length:
                raise ValueError("clipboard file list contains an incomplete path")
            paths.append(buffer.value)
        return paths
    finally:
        user32.CloseClipboard()


def _windows_clipboard_has_image() -> bool:
    if os.name != "nt":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_int
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_int
    opened = False
    for attempt in range(CLIPBOARD_RETRIES):
        if user32.OpenClipboard(None):
            opened = True
            break
        if attempt + 1 < CLIPBOARD_RETRIES:
            time.sleep(CLIPBOARD_RETRY_SECONDS)
    if not opened:
        raise OSError("Windows clipboard is busy; retry the paste")
    try:
        return any(
            user32.IsClipboardFormatAvailable(fmt)
            for fmt in (2, 8, 17)  # CF_BITMAP, CF_DIB, CF_DIBV5
        )
    finally:
        user32.CloseClipboard()


def _decode_windows_clipboard_payload(raw: bytes, *, total_size: int) -> str:
    if len(raw) % 2:
        raw = raw[:-1]
    terminator = next(
        (index for index in range(0, len(raw) - 1, 2) if raw[index:index + 2] == b"\0\0"),
        None,
    )
    content_length = len(raw) if terminator is None else terminator
    truncated = content_length > MAX_TEXT_BYTES or (
        terminator is None and total_size > len(raw)
    )
    raw = raw[: min(content_length, MAX_TEXT_BYTES)]
    # UTF-16 non-BMP characters use a surrogate pair. Drop only a trailing
    # high surrogate if the byte cap split the pair; interior errors stay fatal.
    if truncated and len(raw) >= 2:
        last_unit = int.from_bytes(raw[-2:], "little")
        if 0xD800 <= last_unit <= 0xDBFF:
            raw = raw[:-2]
    return _bound_utf8_text(raw.decode("utf-16-le", errors="strict"), truncated)


def _decode_bounded_utf8(raw: bytes, truncated: bool) -> str:
    if not truncated:
        return raw.decode("utf-8", errors="strict")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        if exc.reason != "unexpected end of data" or exc.end != len(raw):
            raise
        return raw[:exc.start].decode("utf-8", errors="strict")


def _bound_utf8_text(text: str, truncated: bool) -> str:
    if not truncated:
        return text
    budget = MAX_TEXT_BYTES - len(TEXT_TRUNCATION_MARKER.encode("utf-8"))
    while text and len(text.encode("utf-8")) > budget:
        text = text[:-1]
    return text + TEXT_TRUNCATION_MARKER


def _terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def _run_bounded(
    command: list[str], limit: int, *, timeout: float = COMMAND_TIMEOUT_SECONDS
) -> tuple[bytes, int]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    _ACTIVE_CHILDREN.add(process)
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    output: queue.Queue[tuple[bytes | None, BaseException | None]] = queue.Queue(maxsize=1)

    def _read_limited() -> None:
        try:
            output.put((process.stdout.read(limit + 1), None))
        except BaseException as exc:
            output.put((None, exc))

    reader = threading.Thread(target=_read_limited, name="clipboard-pipe-reader", daemon=True)
    reader.start()
    try:
        try:
            data, read_error = output.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            _terminate_process(process)
            reader.join(timeout=1.0)
            return b"", -3
        if read_error is not None:
            _terminate_process(process)
            raise OSError("clipboard command output could not be read") from read_error
        assert data is not None
        if len(data) > limit:
            _terminate_process(process)
            return data[:limit], -2
        try:
            code = process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _terminate_process(process)
            return data, -3
        return data, code
    finally:
        if process.poll() is None:
            _terminate_process(process)
        reader.join(timeout=1.0)
        process.stdout.close()
        _ACTIVE_CHILDREN.discard(process)


def _linux_clipboard(output_dir: Path) -> dict[str, Any]:
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        list_command = ["wl-paste", "--list-types"]
        read_command = lambda mime: ["wl-paste", "--no-newline", "--type", mime]
    elif os.environ.get("DISPLAY") and shutil.which("xclip"):
        list_command = ["xclip", "-selection", "clipboard", "-o", "-target", "TARGETS"]
        read_command = lambda mime: ["xclip", "-selection", "clipboard", "-o", "-target", mime]
    else:
        return _result(
            "error",
            error="No graphical clipboard is available (headless sessions are unsupported); install wl-clipboard or xclip in a desktop session.",
        )
    try:
        type_bytes, code = _run_bounded(list_command, MAX_TEXT_BYTES)
    except (OSError, subprocess.SubprocessError) as exc:
        return _result("error", error=f"clipboard command failed: {exc}")
    if code != 0:
        return _result("error", error="clipboard command could not inspect the active clipboard")
    types = {item.strip() for item in type_bytes.decode("utf-8", "replace").splitlines()}

    if "image/png" in types:
        try:
            raw, code = _run_bounded(read_command("image/png"), MAX_IMAGE_BYTES)
            if code == -2:
                raise ValueError(f"clipboard image exceeds {MAX_IMAGE_BYTES} encoded bytes")
            if code != 0:
                raise ValueError("clipboard image could not be read")
            from PIL import Image

            with Image.open(io.BytesIO(raw)) as image:
                image.load()
                item = _clipboard_image_to_png(image, output_dir)
            return _result("attachments", attachments=[item])
        except Exception as exc:
            return _result(
                "error",
                error=_clipboard_image_error(exc, "clipboard image could not be read"),
            )

    if "text/uri-list" in types:
        try:
            raw, code = _run_bounded(read_command("text/uri-list"), MAX_TEXT_BYTES)
            if code == -2:
                raise ValueError("clipboard file list exceeds the supported size")
            if code != 0:
                raise ValueError("clipboard file list could not be read")
            paths = []
            for row in raw.decode("utf-8", "strict").splitlines():
                row = row.strip()
                if not row or row.startswith("#"):
                    continue
                parsed = urlparse(row)
                if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
                    raise ValueError("clipboard contains a non-local file URI")
                paths.append(unquote(parsed.path))
            return _result("attachments", attachments=_validate_clipboard_paths(paths))
        except Exception as exc:
            return _result("error", error=str(exc) or "clipboard file list could not be read")

    text_mime = next((item for item in ("text/plain;charset=utf-8", "text/plain", "UTF8_STRING") if item in types), None)
    if text_mime:
        try:
            raw, code = _run_bounded(read_command(text_mime), MAX_TEXT_BYTES)
            if code == -3:
                raise ValueError("clipboard read timed out")
            if code not in (0, -2):
                raise ValueError("clipboard text could not be read")
            text = _bound_utf8_text(_decode_bounded_utf8(raw, code == -2), code == -2)
            return _result("text", text=text)
        except Exception as exc:
            return _result("error", error=str(exc) or "clipboard text could not be read")
    return _result("empty")


def _mac_clipboard(output_dir: Path) -> dict[str, Any]:
    osascript = shutil.which("osascript")
    pbpaste = shutil.which("pbpaste")
    if osascript is None or pbpaste is None:
        missing = "osascript" if osascript is None else "pbpaste"
        return _result("error", error=f"{missing} is unavailable; macOS clipboard capture requires the system clipboard commands")

    # Pillow's macOS ImageGrab implementation uses osascript internally but
    # waits without a deadline. Use the same native PNG clipboard format with
    # our bounded reader, then let Pillow validate/decode/normalize the image.
    try:
        raw, code = _run_bounded(
            [osascript, "-e", "get the clipboard as «class PNGf»"],
            MAX_IMAGE_BYTES * 2 + 64,
        )
        if code == -2:
            return _result("error", error=f"clipboard image exceeds {MAX_IMAGE_BYTES} encoded bytes")
        if code == 0:
            import binascii
            from PIL import Image

            apple_data = raw.strip()
            hex_payload = apple_data[11:-3]
            png_bytes = binascii.unhexlify(hex_payload)
            if len(png_bytes) > MAX_IMAGE_BYTES:
                return _result("error", error=f"clipboard image exceeds {MAX_IMAGE_BYTES} encoded bytes")
            with Image.open(io.BytesIO(png_bytes)) as image:
                image.load()
                return _result(
                    "attachments",
                    attachments=[_clipboard_image_to_png(image, output_dir)],
                )
    except Exception as exc:
        return _result(
            "error",
            error=_clipboard_image_error(exc, "macOS clipboard image could not be read"),
        )

    try:
        raw, code = _run_bounded([pbpaste], MAX_TEXT_BYTES)
        if code == -3:
            return _result("error", error="macOS clipboard read timed out")
        if code not in (0, -2):
            return _result("error", error="macOS clipboard text could not be read")
        text = _bound_utf8_text(_decode_bounded_utf8(raw, code == -2), code == -2)
        if text:
            return _result("text", text=text)
        # Finder file promises and other non-text clipboard formats aren't
        # returned by pbpaste. Ask the system whether anything is present so
        # unsupported file objects aren't presented as a successful empty paste.
        info, info_code = _run_bounded(
            [osascript, "-e", "clipboard info"], MAX_TEXT_BYTES
        )
        if info_code == -3:
            return _result("error", error="macOS clipboard inspection timed out")
        if info_code == 0 and info.strip():
            return _result(
                "error",
                error="macOS clipboard contains a non-text item (Finder file objects are not supported by this helper)",
            )
        return _result("empty")
    except Exception as exc:
        return _result("error", error=str(exc) or "macOS clipboard capture failed")


def _install_shutdown_cleanup() -> None:
    def _cleanup(signum, _frame):
        for child in tuple(_ACTIVE_CHILDREN):
            _terminate_process(child)
        raise SystemExit(128 + int(signum))

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _cleanup)
        except (OSError, ValueError):
            pass


def capture_clipboard(output_dir: str | Path | None = None) -> dict[str, Any]:
    destination = Path(output_dir).expanduser() if output_dir else _default_output_dir()
    if os.name == "nt":
        try:
            file_paths = _read_windows_file_list()
            if file_paths is not None:
                return _result(
                    "attachments",
                    attachments=_validate_clipboard_paths(file_paths),
                )
        except Exception as exc:
            return _result("error", error=str(exc) or "Windows clipboard file list failed")

        try:
            from PIL import Image, ImageGrab

            clipboard_object = None
            for attempt in range(CLIPBOARD_RETRIES):
                try:
                    clipboard_object = ImageGrab.grabclipboard()
                    break
                except OSError:
                    if attempt + 1 == CLIPBOARD_RETRIES:
                        raise
                    time.sleep(CLIPBOARD_RETRY_SECONDS)
            if isinstance(clipboard_object, list):
                attachments = _validate_clipboard_paths(clipboard_object)
                return _result("attachments", attachments=attachments)
            if isinstance(clipboard_object, Image.Image):
                return _result(
                    "attachments",
                    attachments=[_clipboard_image_to_png(clipboard_object, destination)],
                )
        except ImportError:
            try:
                if _windows_clipboard_has_image():
                    return _result(
                        "error",
                        error="Clipboard contains image data but Pillow is unavailable; install the declared RxyCode dependencies and retry.",
                    )
            except Exception as exc:
                return _result("error", error=str(exc) or "Windows clipboard inspection failed")
        except Exception as exc:
            return _result("error", error=str(exc) or "Windows clipboard capture failed")

        try:
            text = _read_windows_text()
            if text is not None:
                return _result("text", text=text)
            return _result("empty")
        except Exception as exc:
            return _result("error", error=str(exc) or "Windows clipboard text capture failed")

    if sys.platform.startswith("linux"):
        return _linux_clipboard(destination)

    if sys.platform == "darwin":
        return _mac_clipboard(destination)

    return _result("error", error=f"clipboard capture is unsupported on {sys.platform}")


def main(argv: list[str] | None = None) -> int:
    if os.name != "nt" and os.getpid() != os.getpgrp():
        # The frontend can terminate this helper and all clipboard-command
        # descendants as one process group on POSIX (kill(-child.pid, ...)).
        os.setsid()
    _install_shutdown_cleanup()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args(argv)
    try:
        result = capture_clipboard(args.output_dir)
    except Exception as exc:  # keep stdout a single machine-readable response
        result = _result("error", error=str(exc) or "clipboard capture failed")
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 1 if result["kind"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
