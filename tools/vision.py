"""vision tool - Read/OCR images, capture screenshots, describe visuals.

Provides image analysis capabilities including OCR text extraction,
screenshot capture, and image metadata. Uses PIL/Pillow for image
processing and pytesseract for OCR when available.
"""

import asyncio
import os
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import current_working_directory, resolve_session_path


def _find_tesseract() -> str | None:
    """Auto-detect Tesseract OCR binary location.
    Checks env vars first, then common install paths."""
    # 1. Check environment variables
    env_path = os.environ.get("TESSERACT_CMD") or os.environ.get("TESSERACT_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    # 2. Check common install locations
    common_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return p
    # 3. Check PATH
    for p in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(p, "tesseract.exe")
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(p, "tesseract")
        if os.path.isfile(candidate):
            return candidate
    return None


class VisionInput(BaseModel):
    operation: str = Field(
        default="describe",
        description=(
            "Operation: 'describe' (file metadata only — size/dimensions, "
            "NOT a multimodal caption, cannot tell portraits), "
            "'ocr' (extract text, 15s cap), "
            "'screenshot' (capture screen)"
        ),
    )
    filePath: str = Field(
        default="",
        description="Absolute or session-relative image path (for describe/ocr)"
    )
    prompt: str = Field(
        default="",
        description="Ignored. This tool does not call a vision LLM.",
    )


def run_vision(operation: str = "describe", filePath: str = "", prompt: str = "") -> str:
    """Run vision operations on images."""
    try:
        if operation == "screenshot":
            return _capture_screenshot()
        
        if not filePath:
            return "[error: filePath is required for this operation]"
        
        p = resolve_session_path(filePath)
        if not p.exists():
            return f"[error: file not found: {filePath}]"
        
        # Verify it is an image file before attempting to open
        _image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.ico'}
        if p.suffix.lower() not in _image_exts:
            return f"[error: '{p.suffix}' is not a supported image format. Supported: {', '.join(sorted(_image_exts))}]"
        
        if operation == "describe":
            return _describe_image(str(p))
        elif operation == "ocr":
            return _ocr_image(str(p))
        else:
            return f"[error: unknown operation '{operation}']"
    except ImportError as e:
        return f"[error: missing dependency - {e}. Install with: pip install Pillow]"
    except Exception as e:
        return f"[error: {e}]"


async def run_vision_async(
    operation: str = "describe", filePath: str = "", prompt: str = ""
) -> str:
    """Cancellable vision operations (C2).

    The screenshot subprocess runs via the controlled shell executor so a
    timeout terminates the capture worker's process tree.  describe/OCR are
    CPU/IO-heavy PIL + pytesseract calls that must not block the event loop,
    so they run on a worker thread via ``asyncio.to_thread``.
    """
    try:
        if operation == "screenshot":
            return await _capture_screenshot_async()
        return await asyncio.to_thread(
            run_vision, operation=operation, filePath=filePath, prompt=prompt
        )
    except ImportError as e:
        return f"[error: missing dependency - {e}. Install with: pip install Pillow]"
    except Exception as e:
        return f"[error: {e}]"


def _describe_image(file_path: str) -> str:
    """Return file metadata only. Does not caption or classify the photo.

    Auto-OCR used to run here and could block for many minutes on large
    screenshots. OCR is ``operation=ocr`` only, with a 15s cap.
    """
    from PIL import Image

    img = Image.open(file_path)
    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].upper()
    size_bytes = os.path.getsize(file_path)
    width, height = img.size
    mode = img.mode
    fmt = img.format or ext

    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

    return "\n".join(
        [
            f"File: {filename}",
            f"Format: {fmt}",
            f"Dimensions: {width}x{height} pixels",
            f"Size: {size_str}",
            f"Color Mode: {mode}",
            "Note: metadata only — this tool cannot tell if the image is a "
            "portrait or describe its contents. Use operation=ocr for text, "
            "or a vision-capable chat model to inspect the picture.",
        ]
    )


def _ocr_image(file_path: str) -> str:
    """Extract text from image using OCR with a hard 15s cap."""
    from PIL import Image

    img = Image.open(file_path)

    try:
        import pytesseract
        _tesseract_cmd = _find_tesseract()
        if _tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd
    except ImportError:
        return "[error: pytesseract not installed. Install with: pip install pytesseract]"

    try:
        text = pytesseract.image_to_string(img, lang="eng+chi_sim", timeout=15)
    except RuntimeError as exc:
        return f"[error: OCR timed out or failed: {exc}]"
    except Exception as exc:
        return f"[error: OCR failed: {exc}]"

    if not str(text).strip():
        return "[no text detected in image]"
    return f"Standard OCR:\n{str(text).strip()}"


def _interactive_desktop_available() -> bool:
    """Return False when Windows is on the lock/secure desktop.

    ``mss`` capture blocks forever on a locked or disconnected session
    (Win32 GetDC/BitBlt never returns), and in-process timeouts cannot
    interrupt native calls.  This cheap precheck gives an instant, clear
    error instead of waiting for the capture timeout.
    """
    if os.name != "nt":
        return True
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # DESKTOP_READOBJECTS = 0x0001
        desktop = user32.OpenInputDesktop(0, False, 0x0001)
        if not desktop:
            return False
        user32.CloseDesktop(desktop)
        return True
    except Exception:
        # Never fail the capture path because the precheck itself failed.
        return True


def _capture_screenshot() -> str:
    """Capture a screenshot and return info about it.

    The actual capture runs in a subprocess with a hard timeout: native
    capture calls can block forever on a locked/RDP-disconnected session,
    and in-process timeout threads cannot interrupt them.  The OS can kill
    the worker process, so the agent itself never hangs.

    Set ``RXYCODE_DISABLE_SCREEN_CAPTURE=1`` to forbid capture entirely
    (used by tests and headless deployments).
    """
    if os.environ.get("RXYCODE_DISABLE_SCREEN_CAPTURE"):
        return (
            "[error: screen capture disabled via "
            "RXYCODE_DISABLE_SCREEN_CAPTURE]"
        )

    if not _interactive_desktop_available():
        return (
            "[error: no interactive desktop available (locked screen or "
            "disconnected session) - screen capture would block]"
        )

    import subprocess
    import sys

    timeout_s = float(os.environ.get("RXYCODE_SCREEN_CAPTURE_TIMEOUT", "5"))
    output_dir = current_working_directory()
    # Prefer the installed-package path; fall back to the repo-root layout
    # (``python -m tools.vision_capture``) when running from a checkout.
    candidates = (
        [sys.executable, "-m", "RxyCode.RxyCode1_1_0.tools.vision_capture",
         str(output_dir)],
        [sys.executable, "-m", "tools.vision_capture", str(output_dir)],
    )
    try:
        proc = subprocess.run(
            candidates[0],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if proc.returncode and "No module named" in proc.stderr:
            proc = subprocess.run(
                candidates[1],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
    except subprocess.TimeoutExpired:
        return (
            f"[error: screen capture timed out after {timeout_s:.0f}s "
            "(session locked or display unavailable)]"
        )
    except FileNotFoundError:
        return "[error: python interpreter not found for capture worker]"

    if proc.returncode != 0:
        detail = (proc.stderr or "unknown error").strip()[:300]
        return f"[error: screen capture failed (exit {proc.returncode}): {detail}]"

    return proc.stdout.strip()


def _capture_candidates() -> tuple[list[str], list[str]]:
    """Candidate capture-worker argv lists (installed-package, repo-root)."""
    import sys

    output_dir = current_working_directory()
    return (
        [sys.executable, "-m", "RxyCode.RxyCode1_1_0.tools.vision_capture",
         str(output_dir)],
        [sys.executable, "-m", "tools.vision_capture", str(output_dir)],
    )


async def _capture_screenshot_async() -> str:
    """Capture a screenshot via the controlled shell executor so the capture
    worker's process tree is terminated on timeout (C2)."""
    if os.environ.get("RXYCODE_DISABLE_SCREEN_CAPTURE"):
        return (
            "[error: screen capture disabled via "
            "RXYCODE_DISABLE_SCREEN_CAPTURE]"
        )
    if not _interactive_desktop_available():
        return (
            "[error: no interactive desktop available (locked screen or "
            "disconnected session) - screen capture would block]"
        )

    from ..utils.shell import shell_executor

    timeout_s = float(os.environ.get("RXYCODE_SCREEN_CAPTURE_TIMEOUT", "5"))
    first, second = _capture_candidates()
    result = await shell_executor.execute_argv_async(first, timeout=timeout_s)
    if not result["success"] and "No module named" in (result["stderr"] or ""):
        result = await shell_executor.execute_argv_async(
            second, timeout=timeout_s
        )
    if result.get("error_type") == "timeout":
        return (
            f"[error: screen capture timed out after {timeout_s:.0f}s "
            "(session locked or display unavailable)]"
        )
    if not result["success"]:
        detail = (result["stderr"] or "unknown error").strip()[:300]
        return (
            f"[error: screen capture failed "
            f"(exit {result['exit_code']}): {detail}]"
        )
    return (result["stdout"] or "").strip()


vision_tool = StructuredTool(
    name="vision",
    description=(
        "Inspect an image file's metadata (size, dimensions) or OCR its text. "
        "describe does NOT see people/portraits and does not call a vision LLM. "
        "ocr extracts text (15s cap). screenshot captures the screen."
    ),
    func=run_vision,
    coroutine=run_vision_async,
    args_schema=VisionInput,
)
