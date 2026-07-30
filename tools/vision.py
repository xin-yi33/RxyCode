"""vision tool - Read/OCR images, capture screenshots, describe visuals.

Provides image analysis capabilities including OCR text extraction,
screenshot capture, and image metadata. Uses PIL/Pillow for image
processing and pytesseract for OCR when available.
"""

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
        description="Operation: 'describe' (get image info), 'ocr' (extract text), 'screenshot' (capture screen)"
    )
    filePath: str = Field(
        default="",
        description="Absolute or session-relative image path (for describe/ocr)"
    )
    prompt: str = Field(
        default="What do you see in this image?",
        description="Optional prompt for describing the image"
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


def _describe_image(file_path: str) -> str:
    """Get image metadata and return formatted description."""
    from PIL import Image
    
    img = Image.open(file_path)
    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].upper()
    size_bytes = os.path.getsize(file_path)
    width, height = img.size
    mode = img.mode
    fmt = img.format or ext
    
    # Size in human-readable format
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
    
    result = [
        f"File: {filename}",
        f"Format: {fmt}",
        f"Dimensions: {width}x{height} pixels",
        f"Size: {size_str}",
        f"Color Mode: {mode}",
    ]
    
    # Try OCR by default if image has text-like content
    try:
        import pytesseract
        _tesseract_cmd = _find_tesseract()
        if _tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd
        text = pytesseract.image_to_string(img)
        if text.strip():
            result.append(f"\nExtracted Text (OCR):\n{text.strip()}")
    except ImportError:
        pass
    except Exception:
        pass
    
    return "\n".join(result)


def _ocr_image(file_path: str) -> str:
    """Extract text from image using OCR."""
    from PIL import Image
    
    img = Image.open(file_path)
    
    try:
        import pytesseract
        _tesseract_cmd = _find_tesseract()
        if _tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd
    except ImportError:
        return "[error: pytesseract not installed. Install with: pip install pytesseract]"
    
    # Try multiple OCR configurations for better results
    results = []
    
    # Standard OCR
    text = pytesseract.image_to_string(img, lang='eng+chi_sim')
    if text.strip():
        results.append("Standard OCR:")
        results.append(text.strip())
    
    # Try with preprocessing for better accuracy
    try:
        # Convert to grayscale and enhance contrast
        gray = img.convert('L')
        text_gray = pytesseract.image_to_string(gray, lang='eng+chi_sim')
        if text_gray.strip() and text_gray.strip() != text.strip():
            results.append("\nEnhanced OCR:")
            results.append(text_gray.strip())
    except Exception:
        pass
    
    if not results:
        return "[no text detected in image]"
    
    # Try to get bounding box info
    try:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        word_count = sum(1 for t in data['text'] if t.strip())
        if word_count > 0:
            results.append(f"\nDetected {word_count} words/text blocks")
    except Exception:
        pass
    
    return "\n".join(results)


def _capture_screenshot() -> str:
    """Capture a screenshot and return info about it."""
    try:
        import mss
    except ImportError:
        return "[error: mss not installed. Install with: pip install mss pillow]"
    
    with mss.mss() as sct:
        monitors = sct.monitors
        output_dir = current_working_directory()
        screenshots = []
        
        # Capture all monitors
        for idx, monitor in enumerate(monitors[1:], 1):  # skip monitor 0 (all-in-one)
            filename = f"screenshot_monitor_{idx}.png"
            filepath = output_dir / filename
            sct.shot(mon=idx, output=str(filepath))
            
            from PIL import Image
            with Image.open(filepath) as img:
                w, h = img.size
            size_kb = os.path.getsize(filepath) / 1024
            screenshots.append(f"  Monitor {idx}: {w}x{h}px, {size_kb:.0f}KB -> {filepath}")
        
        result = [f"Captured {len(screenshots)} screenshot(s):"]
        result.extend(screenshots)
        result.append(f"\nSaved to: {output_dir}")
        return "\n".join(result)


vision_tool = StructuredTool(
    name="vision",
    description="Read/analyze images, extract text (OCR), and capture screenshots. "
                "Use 'describe' for image metadata, 'ocr' for text extraction, "
                "'screenshot' to capture the screen.",
    func=run_vision,
    args_schema=VisionInput,
)
