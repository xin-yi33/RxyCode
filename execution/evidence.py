"""Deterministic evidence captured at the tool execution boundary."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import re
from typing import Any

from pydantic import BaseModel, Field

from ..core.session_runtime import resolve_session_path, resolve_write_path


_HTML_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


class _HTMLStructureParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.seen_html = False
        self.seen_body = False
        self.invalid = False

    def handle_starttag(self, tag, attrs):
        lowered = tag.lower()
        self.seen_html |= lowered == "html"
        self.seen_body |= lowered == "body"
        if lowered not in _HTML_VOID_ELEMENTS:
            self.stack.append(lowered)

    def handle_startendtag(self, tag, attrs):
        lowered = tag.lower()
        self.seen_html |= lowered == "html"
        self.seen_body |= lowered == "body"

    def handle_endtag(self, tag):
        lowered = tag.lower()
        if not self.stack or self.stack[-1] != lowered:
            self.invalid = True
            return
        self.stack.pop()


def _valid_html(text: str) -> bool:
    parser = _HTMLStructureParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return False
    return (
        parser.seen_html
        and parser.seen_body
        and not parser.invalid
        and not parser.stack
    )


class ArtifactEvidence(BaseModel):
    path: str
    exists: bool
    size: int | None = None
    sha256: str | None = None
    media_type: str | None = None
    valid: bool | None = None


class ToolEvidence(BaseModel):
    tool: str
    status: str
    executed: bool
    risk: str | None = None
    approval: str = ""
    exit_code: int | None = None
    artifacts: list[ArtifactEvidence] = Field(default_factory=list)
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "succeeded" and self.executed


def build_tool_evidence(
    tool: str,
    args: Any,
    result: str,
    *,
    executed: bool,
    approval: str = "",
    risk: Any | None = None,
) -> ToolEvidence:
    text = str(result)
    lowered = text.strip().lower()
    exit_match = re.search(r"\[exit code:\s*(-?\d+)\]", lowered)
    exit_code = int(exit_match.group(1)) if exit_match else None

    failure_prefixes = (
        "[error",
        "[agent error",
        "error:",
        "download failed",
        "failed to ",
        "[workflow error",
        "[workflow timeout",
        "[blocked",
        "[rejected",
        "[cancelled",
        "[timeout",
    )
    legacy_not_found = bool(re.match(
        r"^\[(?:(?:task|skill|workflow)\b.*\bnot found|"
        r"not found:.*|history directory not found)\]$",
        lowered,
    ))
    if not executed:
        status = "dry_run" if lowered.startswith("[dry-run]") else "rejected"
    elif lowered.startswith(failure_prefixes) or legacy_not_found:
        status = "failed"
    elif "[syntax check: syntax_error:" in lowered or "[syntax check: bracket_mismatch:" in lowered:
        status = "failed"
    elif exit_code is not None and exit_code != 0:
        status = "failed"
    else:
        status = "succeeded"

    artifacts: list[ArtifactEvidence] = []
    if tool.lower() in {"write", "edit", "patch"} and isinstance(args, dict):
        raw_path = next((args.get(key) for key in ("filePath", "path", "file_path") if args.get(key)), None)
        if isinstance(raw_path, str):
            path = resolve_write_path(raw_path)
            exists = path.is_file()
            artifact = ArtifactEvidence(path=str(path), exists=exists)
            if exists:
                data = path.read_bytes()
                artifact.size = len(data)
                artifact.sha256 = hashlib.sha256(data).hexdigest()
                try:
                    decoded = data.decode("utf-8")
                except UnicodeDecodeError:
                    decoded = None

                if tool.lower() == "write" and "content" in args:
                    expected = str(args.get("content", ""))
                    # Normalize BOM + newlines so Windows CRLF / UTF-8 BOM
                    # writers do not false-fail artifact validation.
                    def _norm(s: str) -> str:
                        if s.startswith("\ufeff"):
                            s = s[1:]
                        return s.replace("\r\n", "\n").replace("\r", "\n")

                    artifact.valid = (
                        decoded is not None and _norm(decoded) == _norm(expected)
                    )
                elif tool.lower() == "edit" and "newString" in args:
                    replacement = str(args.get("newString", ""))
                    old = str(args.get("oldString", ""))
                    if decoded is None:
                        artifact.valid = False
                    elif replacement:
                        artifact.valid = replacement in decoded
                    else:
                        artifact.valid = old not in decoded
                elif tool.lower() == "patch" and isinstance(args.get("diff"), str):
                    added_lines = [
                        line[1:]
                        for line in args["diff"].splitlines()
                        if line.startswith("+") and not line.startswith("+++")
                    ]
                    artifact.valid = decoded is not None and all(
                        line in decoded.splitlines() for line in added_lines
                    )

                if path.suffix.lower() in {".html", ".htm"}:
                    artifact.media_type = "text/html"
                    if decoded is None:
                        artifact.valid = False
                    else:
                        html_valid = _valid_html(decoded)
                        artifact.valid = html_valid and artifact.valid is not False
            artifacts.append(artifact)
            if not exists or artifact.valid is False:
                status = "failed"
    elif tool.lower() in {"download_file", "file_download"} and status == "succeeded":
        saved_match = re.search(r"(?im)^\s*saved to:\s*(.+?)\s*$", text)
        if saved_match is None:
            status = "failed"
        else:
            path = resolve_session_path(saved_match.group(1).strip())
            exists = path.is_file()
            artifact = ArtifactEvidence(
                path=str(path),
                exists=exists,
                valid=exists,
            )
            if exists:
                digest = hashlib.sha256()
                try:
                    with path.open("rb") as artifact_file:
                        for chunk in iter(
                            lambda: artifact_file.read(1024 * 1024),
                            b"",
                        ):
                            digest.update(chunk)
                    artifact.size = path.stat().st_size
                    artifact.sha256 = digest.hexdigest()
                except OSError:
                    artifact.exists = False
                    artifact.valid = False
            artifacts.append(artifact)
            if not artifact.exists:
                status = "failed"

    return ToolEvidence(
        tool=tool,
        status=status,
        executed=executed,
        risk=(
            str(getattr(risk, "name", risk)).strip().upper()
            if risk is not None
            else None
        ),
        approval=approval,
        exit_code=exit_code,
        artifacts=artifacts,
        detail=text[:500],
    )


def deterministic_issues(evidence: list[dict[str, Any] | ToolEvidence]) -> list[str]:
    records = [
        item if isinstance(item, ToolEvidence) else ToolEvidence.model_validate(item)
        for item in evidence
    ]
    # When the same artifact path is written more than once (iterative
    # refinement / retries), only the LAST write to that path is
    # authoritative. Earlier writes are superseded by the final content, so
    # their (now stale) content mismatch with the on-disk file must not be
    # reported as failures. The single-record semantics tested elsewhere
    # (a write whose file content genuinely differs from what was requested)
    # are preserved because a lone write is, by definition, the last one.
    last_write_index: dict[str, int] = {}
    for idx, rec in enumerate(records):
        if rec.tool and rec.tool.lower() in {"write", "edit", "patch"}:
            for art in rec.artifacts:
                last_write_index[art.path] = idx

    issues: list[str] = []
    for idx, record in enumerate(records):
        superseded = (
            record.tool is not None
            and record.tool.lower() in {"write", "edit", "patch"}
            and any(
                art.path in last_write_index and last_write_index[art.path] != idx
                for art in record.artifacts
            )
        )
        if superseded:
            continue
        if not record.passed:
            issues.append(f"Tool {record.tool} did not complete: {record.status}")
        for artifact in record.artifacts:
            if not artifact.exists:
                issues.append(f"Expected artifact does not exist: {artifact.path}")
            elif artifact.valid is False:
                issues.append(f"Artifact failed format validation: {artifact.path}")
    return issues
