"""Bounded, streaming capture for subprocess stdout and stderr."""

from __future__ import annotations

import codecs
import hashlib
import locale
import os
import re
import uuid
from collections import deque
from pathlib import Path
from typing import BinaryIO

from ..config.settings import get_data_dir
from ..core.session_runtime import current_session_id


# Keep each read finite and apply synchronous file writes in the reader task.
# A slow disk therefore back-pressures the pipe reader instead of queueing
# unbounded write work in the event loop.
CAPTURE_READ_CHUNK_BYTES = 64 * 1024
CAPTURE_PREVIEW_BYTES_PER_STREAM = 48 * 1024
# Match bash's existing presentation cap: at most 30000 raw bytes remain
# inline, and the first byte beyond it triggers a full artifact spill.
CAPTURE_SPILL_THRESHOLD_BYTES = 30_000
CAPTURE_ARTIFACT_PREFIX = "Full output saved to:"
CAPTURE_FAILURE_HINT = "[output capture failed; retained preview may be incomplete]"

# Mirrors the marker vocabulary used by tools.secret_text.redact_secrets.
# If any marker occurs in a truncated stream, its tail is omitted: the key
# might have fallen before the byte-window while its value remains in it.
_REDACTION_MARKER_BYTES = tuple(
    marker.encode("ascii")
    for marker in (
        "bearer",
        "authorization",
        "api_key",
        "api-key",
        "apikey",
        "password",
        "passwd",
        "secret",
        "token",
    )
)
_REDACTION_MARKER_OVERLAP = max(map(len, _REDACTION_MARKER_BYTES)) - 1

_SAFE_SESSION_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _session_component(session_id: str) -> str:
    if _SAFE_SESSION_COMPONENT.fullmatch(session_id) and session_id not in {".", ".."}:
        return session_id
    return hashlib.sha256(session_id.encode("utf-8", errors="replace")).hexdigest()


def _open_capture_artifact(path: Path) -> BinaryIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("xb")


class _WorkspaceSpillRejected(OSError):
    """The configured artifact location overlaps an active workspace."""


class _StreamCapture:
    def __init__(self, name: str) -> None:
        self.name = name
        self.total_bytes = 0
        self.digest = hashlib.sha256()
        self.inline = bytearray()
        self._preview = bytearray()
        self._head: bytes | None = None
        self._tail = bytearray()
        self._preview_truncated = False
        self._marker_overlap = b""
        self._redaction_marker_seen = False
        self._utf8_decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self.utf8_valid = True
        self.artifact_path: Path | None = None
        self._file: BinaryIO | None = None
        self.artifact_complete = False
        self.capture_error: str | None = None
        self.eof = False
        self.line_count = 0
        self.head_lines: list[str] = []
        self.tail_lines: deque[str] = deque(maxlen=50)
        self._line_decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._pending_head = ""
        self._pending_tail = ""
        self._pending_len = 0

    def add(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        self.digest.update(chunk)
        self._observe_redaction_markers(chunk)
        self._validate_utf8(chunk)
        self._add_preview(chunk)
        self._note_lines(chunk)

    def _observe_redaction_markers(self, chunk: bytes) -> None:
        if self._redaction_marker_seen:
            return
        combined = (self._marker_overlap + chunk).lower()
        if any(marker in combined for marker in _REDACTION_MARKER_BYTES):
            self._redaction_marker_seen = True
            self._marker_overlap = b""
            return
        self._marker_overlap = combined[-_REDACTION_MARKER_OVERLAP:]

    def _validate_utf8(self, chunk: bytes) -> None:
        if not self.utf8_valid:
            return
        try:
            self._utf8_decoder.decode(chunk, final=False)
        except UnicodeDecodeError:
            self.utf8_valid = False
            self._utf8_decoder = None

    def _add_preview(self, chunk: bytes) -> None:
        limit = CAPTURE_PREVIEW_BYTES_PER_STREAM
        half = limit // 2
        if not self._preview_truncated:
            if len(self._preview) + len(chunk) <= limit:
                self._preview.extend(chunk)
                return
            combined = self._preview + chunk
            self._head = bytes(combined[:half])
            self._tail = bytearray(combined[-half:])
            self._preview.clear()
            self._preview_truncated = True
            return

        if len(chunk) >= half:
            self._tail[:] = chunk[-half:]
            return
        overflow = len(self._tail) + len(chunk) - half
        if overflow > 0:
            del self._tail[:overflow]
        self._tail.extend(chunk)

    def end(
        self,
        *,
        read_ok: bool = True,
        read_error: BaseException | None = None,
    ) -> None:
        if self.eof:
            return
        self.eof = True
        if self.utf8_valid:
            try:
                self._utf8_decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                self.utf8_valid = False
            self._utf8_decoder = None
        self._note_lines(b"", final=True)
        if self._pending_len:
            self._commit_line()
        if not read_ok:
            self._fail("pipe read failed", read_error or OSError())
            return
        self._close_artifact()

    def _note_lines(self, chunk: bytes, *, final: bool = False) -> None:
        text = self._line_decoder.decode(chunk, final=final)
        if not text:
            return
        pieces = text.split("\n")
        for index, piece in enumerate(pieces):
            self._append_pending(piece)
            if index < len(pieces) - 1:
                self._commit_line()

    def _append_pending(self, piece: str) -> None:
        if not piece:
            return
        self._pending_len += len(piece)
        if len(self._pending_head) < 200:
            room = 200 - len(self._pending_head)
            self._pending_head += piece[:room]
            piece = piece[room:]
        if piece:
            self._pending_tail = (self._pending_tail + piece)[-200:]

    def _commit_line(self) -> None:
        self.line_count += 1
        head = self._pending_head
        tail = self._pending_tail if self._pending_len > 200 and self._pending_tail else head
        if len(self.head_lines) < 50:
            self.head_lines.append(head)
        self.tail_lines.append(tail)
        self._pending_head = ""
        self._pending_tail = ""
        self._pending_len = 0

    def preview_text(self) -> str:
        encoding = "utf-8" if self.utf8_valid else (locale.getpreferredencoding(False) or "utf-8")
        if not self._preview_truncated:
            data = bytes(self._preview)
            return data.decode(encoding, errors="replace" if encoding != "utf-8" else "strict")

        head = self._decode_utf8_edge(self._head or b"", is_head=True) if self.utf8_valid else (
            (self._head or b"").decode(encoding, errors="replace")
        )
        if self._redaction_marker_seen:
            omitted = max(0, self.total_bytes - len(self._head or b""))
            return (
                f"{head}\n[stream output truncated; {omitted} bytes omitted; "
                "tail omitted for secret safety]"
            )
        tail_bytes = bytes(self._tail)
        tail = self._decode_utf8_edge(tail_bytes, is_head=False) if self.utf8_valid else (
            tail_bytes.decode(encoding, errors="replace")
        )
        omitted = max(0, self.total_bytes - len(self._head or b"") - len(tail_bytes))
        return f"{head}\n[stream output truncated; {omitted} bytes omitted]\n{tail}"

    @staticmethod
    def _decode_utf8_edge(data: bytes, *, is_head: bool) -> str:
        # The complete stream was validated as UTF-8; only the preview cut can
        # split a code point. Drop at most three boundary bytes, never replace
        # a valid character with mojibake.
        for trim in range(4):
            candidate = data[:-trim] if is_head and trim else (data[trim:] if trim else data)
            try:
                return candidate.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                continue
        return ""

    def fail(self, operation: str, exc: BaseException) -> None:
        self._fail(operation, exc)

    def _fail(self, operation: str, exc: BaseException) -> None:
        if self.capture_error is None:
            self.capture_error = f"{self.name} {operation} ({type(exc).__name__})"
        self.artifact_complete = False
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        if self.artifact_path is not None:
            try:
                self.artifact_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.artifact_path = None
        self.inline.clear()

    def _close_artifact(self) -> None:
        if self._file is None:
            return
        file = self._file
        self._file = None
        try:
            file.flush()
            file.close()
        except OSError as exc:
            self._file = file
            self._fail("spill write failed", exc)
            return
        self.artifact_complete = self.artifact_path is not None and self.capture_error is None

    def abort(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        if self.artifact_path is not None:
            try:
                self.artifact_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.artifact_path = None
        self.artifact_complete = False


class BoundedOutputCapture:
    """Capture two subprocess pipes with memory independent of output size."""

    def __init__(self, *, forbidden_roots: tuple[Path, ...] = ()) -> None:
        self.stdout = _StreamCapture("stdout")
        self.stderr = _StreamCapture("stderr")
        self.total_bytes = 0
        self.spilled = False
        self._spill_dir: Path | None = None
        self._spill_dir_error: OSError | None = None
        self._forbidden_roots = tuple(root.resolve() for root in forbidden_roots)
        self._finished = False

    def feed(self, stream_name: str, chunk: bytes) -> None:
        if stream_name not in {"stdout", "stderr"}:
            raise ValueError(f"unsupported output stream: {stream_name}")
        if self._finished:
            raise RuntimeError("output capture is already finished")
        if not chunk:
            return
        stream = self.stdout if stream_name == "stdout" else self.stderr
        stream.add(chunk)
        self.total_bytes += len(chunk)

        if not self.spilled and self.total_bytes > CAPTURE_SPILL_THRESHOLD_BYTES:
            self.spilled = True
            self._migrate_inline_data()

        if self.spilled:
            self._write_chunk(stream, chunk)
        else:
            stream.inline.extend(chunk)

    def _migrate_inline_data(self) -> None:
        for stream in (self.stdout, self.stderr):
            if stream.inline:
                self._ensure_artifact(stream)
            if stream.eof:
                stream._close_artifact()

    def _ensure_artifact(self, stream: _StreamCapture) -> bool:
        if stream.capture_error is not None:
            return False
        if stream._file is None:
            try:
                if self._spill_dir_error is not None:
                    raise self._spill_dir_error
                if self._spill_dir is None:
                    session = _session_component(str(current_session_id() or "default"))
                    candidate = (get_data_dir() / "spill" / session).resolve()
                    if any(self._is_within(root, candidate) for root in self._forbidden_roots):
                        raise _WorkspaceSpillRejected(
                            "spill directory overlaps the active workspace"
                        )
                    self._spill_dir = candidate
                # Keep the established spill-path shape so the orchestrator
                # recognizes only real generated artifacts as trusted links.
                path = self._spill_dir / f"{uuid.uuid4().hex}.txt"
                stream._file = _open_capture_artifact(path)
                stream.artifact_path = path
            except OSError as exc:
                if self._spill_dir is None:
                    self._spill_dir_error = exc
                operation = (
                    "spill directory overlaps the active workspace"
                    if isinstance(exc, _WorkspaceSpillRejected)
                    else "spill write failed"
                )
                stream._fail(operation, exc)
                return False

        if stream.inline:
            try:
                stream._file.write(stream.inline)
                stream.inline.clear()
            except OSError as exc:
                stream._fail("spill write failed", exc)
                return False
        return True

    @staticmethod
    def _is_within(root: Path, candidate: Path) -> bool:
        try:
            common = os.path.commonpath((str(root), str(candidate)))
            return os.path.normcase(common) == os.path.normcase(str(root))
        except (OSError, ValueError):
            return False

    def _write_chunk(self, stream: _StreamCapture, chunk: bytes) -> None:
        if not self._ensure_artifact(stream):
            return
        try:
            assert stream._file is not None
            stream._file.write(chunk)
        except OSError as exc:
            stream._fail("spill write failed", exc)

    def end_stream(self, stream_name: str, *, read_ok: bool = True) -> None:
        stream = self.stdout if stream_name == "stdout" else self.stderr
        if not read_ok:
            stream.end(read_ok=False)
        else:
            stream.end()

    def read_error(self, stream_name: str, exc: BaseException) -> None:
        stream = self.stdout if stream_name == "stdout" else self.stderr
        stream.end(read_ok=False, read_error=exc)

    def finish(self) -> dict[str, object]:
        if self._finished:
            raise RuntimeError("output capture is already finished")
        self._finished = True
        self.stdout.end()
        self.stderr.end()
        streams = (self.stdout, self.stderr)
        errors = [stream.capture_error for stream in streams if stream.capture_error]
        if errors:
            # A path labelled "Full output saved to:" must never imply that
            # both captured streams are complete when either one failed.
            for stream in streams:
                stream.abort()
        fingerprint_material = (
            f"stdout:{self.stdout.total_bytes}:{self.stdout.digest.hexdigest()}\0"
            f"stderr:{self.stderr.total_bytes}:{self.stderr.digest.hexdigest()}"
        )
        return {
            "stdout": self.stdout.preview_text(),
            "stderr": self.stderr.preview_text(),
            "stdout_bytes": self.stdout.total_bytes,
            "stderr_bytes": self.stderr.total_bytes,
            "stdout_sha256": self.stdout.digest.hexdigest(),
            "stderr_sha256": self.stderr.digest.hexdigest(),
            "stdout_truncated": self.stdout._preview_truncated,
            "stderr_truncated": self.stderr._preview_truncated,
            "stdout_line_count": self.stdout.line_count,
            "stderr_line_count": self.stderr.line_count,
            "stdout_head_lines": list(self.stdout.head_lines),
            "stderr_head_lines": list(self.stderr.head_lines),
            "stdout_tail_lines": list(self.stdout.tail_lines),
            "stderr_tail_lines": list(self.stderr.tail_lines),
            "stdout_redaction_hold": (
                self.stdout._redaction_marker_seen and self.stdout._preview_truncated
            ),
            "stderr_redaction_hold": (
                self.stderr._redaction_marker_seen and self.stderr._preview_truncated
            ),
            "stdout_artifact": (
                str(self.stdout.artifact_path)
                if self.stdout.artifact_complete and self.stdout.artifact_path is not None
                else None
            ),
            "stderr_artifact": (
                str(self.stderr.artifact_path)
                if self.stderr.artifact_complete and self.stderr.artifact_path is not None
                else None
            ),
            "capture_fingerprint": hashlib.sha256(
                fingerprint_material.encode("ascii")
            ).hexdigest(),
            "capture_error": "; ".join(errors) if errors else None,
        }

    def abort(self) -> None:
        self.stdout.abort()
        self.stderr.abort()


def write_text_artifact(text: str) -> Path:
    """Save a complete tool result the capture has not already spilled."""
    session = _session_component(str(current_session_id() or "default"))
    directory = (get_data_dir() / "spill" / session).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def append_capture_hints(output: str, result: dict[str, object]) -> str:
    """Append local artifact paths or capture failure to a caller's preview.

    The paths always use the established generated-spill prefix so the tool
    orchestrator can validate and preserve them. This never opens an artifact.
    """
    hints = [
        f"{CAPTURE_ARTIFACT_PREFIX} {path}"
        for path in (result.get("stdout_artifact"), result.get("stderr_artifact"))
        if path
    ]
    if result.get("capture_error"):
        hints.append(CAPTURE_FAILURE_HINT)
    if not hints:
        return output
    suffix = "\n".join(hints)
    return f"{output}\n{suffix}" if output else suffix
