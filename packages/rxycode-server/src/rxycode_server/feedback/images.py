"""Feedback screenshot sanitization — the only bytes that survive are pixels.

The wire format is never trusted: the stored content type comes from a magic-
byte sniff plus a full Pillow decode, and the blob we persist is a fresh
decode->re-encode round trip. That drops EXIF/IPTC/XMP/ICC metadata, embedded
JPEG thumbnails (a real GPS leak), and any polyglot tail sitting after the
image end marker — there is nothing in the output buffer but re-encoded
pixels.
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_EDGE = 4096

# Pillow's own bomb guard — keep it consistent with our explicit budget.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class ImageRejected(Exception):
    """``code`` is the public error code; ``status`` the HTTP status."""

    def __init__(self, status: int, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.status = status
        self.code = code


def _sniff(head: bytes) -> str:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return ""


@dataclass(frozen=True)
class SanitizedImage:
    content_type: str  # "image/png" | "image/jpeg"
    width: int
    height: int
    blob: bytes
    sha256: str


def sanitize_image(raw: bytes) -> SanitizedImage:
    """Fail-closed bytes->pixels->bytes pipeline.

    Accepts PNG/JPEG/WebP on the wire. Output is PNG when the source had
    alpha or was PNG/WebP, JPEG otherwise — stored ``content_type`` is
    therefore always ``image/png`` or ``image/jpeg``.
    """
    if not raw:
        raise ImageRejected(415, "FEEDBACK_IMAGE_TYPE", "empty body")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ImageRejected(413, "FEEDBACK_IMAGE_TOO_LARGE")

    source_kind = _sniff(raw[:16])
    if not source_kind:
        raise ImageRejected(415, "FEEDBACK_IMAGE_TYPE", "unrecognized image bytes")

    try:
        with warnings.catch_warnings():
            # 0.5×–2× 预算之间的「警告」窗口在 Pillow 里照常放行并分配 ——
            # 升级成错误，与硬上限同等待遇。
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(raw))
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRejected(413, "FEEDBACK_IMAGE_TOO_LARGE", "pixel budget exceeded") from None
    except Exception:
        raise ImageRejected(415, "FEEDBACK_IMAGE_TYPE", "corrupt or truncated image") from None

    # 头部声明的尺寸在 load() 分配内存之前先拦。
    width, height = image.size
    if width < 1 or height < 1:
        raise ImageRejected(415, "FEEDBACK_IMAGE_TYPE", "empty image")
    if width * height > MAX_IMAGE_PIXELS:
        raise ImageRejected(413, "FEEDBACK_IMAGE_TOO_LARGE", "pixel budget exceeded")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image.load()  # force full decode — truncated/polyglot tails fail here
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRejected(413, "FEEDBACK_IMAGE_TOO_LARGE", "pixel budget exceeded") from None
    except Exception:
        raise ImageRejected(415, "FEEDBACK_IMAGE_TYPE", "corrupt or truncated image") from None

    width, height = image.size
    if width * height > MAX_IMAGE_PIXELS:
        raise ImageRejected(413, "FEEDBACK_IMAGE_TOO_LARGE", "pixel budget exceeded")

    try:
        if max(width, height) > MAX_EDGE:
            scale = MAX_EDGE / max(width, height)
            image = image.resize(
                (max(1, round(width * scale)), max(1, round(height * scale))),
                Image.Resampling.LANCZOS,
            )
            width, height = image.size

        has_alpha = image.mode in ("RGBA", "LA", "PA") or (
            image.mode == "P" and "transparency" in image.info
        )
        buffer = io.BytesIO()
        if has_alpha or source_kind in ("png", "webp"):
            out = image.convert("RGBA") if has_alpha else image.convert("RGB")
            out.info = {}  # convert() 会带上源的 icc_profile/exif/文本块
            out.save(buffer, "PNG", optimize=True)
            content_type = "image/png"
        else:
            out = image.convert("RGB")
            out.info = {}
            out.save(buffer, "JPEG", quality=85)
            content_type = "image/jpeg"
    except Exception:
        # 16-bit PNG（I;16）等 mode 转换/编码失败按无效图片处理 ——
        # 上传路径不能漏 500。
        raise ImageRejected(415, "FEEDBACK_IMAGE_TYPE", "unsupported image mode") from None
    blob = buffer.getvalue()
    return SanitizedImage(
        content_type=content_type,
        width=width,
        height=height,
        blob=blob,
        sha256=hashlib.sha256(blob).hexdigest(),
    )
