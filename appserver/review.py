"""PhaseG-B8 review, checkpoint, and git hunk actions. Review never writes the tree."""

from __future__ import annotations

import hashlib
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workspace import assert_inside_workspace, canonicalize

SCOPE_ALIASES = {
    "working_tree": "working_tree",
    "base": "base_branch",
    "base_branch": "base_branch",
    "branch": "base_branch",
    "head": "commit",
    "commit": "commit",
    "files": "files",
    "paths": "files",
    "unstaged": "unstaged",
    "staged": "staged",
    "last_turn": "last_turn",
}
SCOPES = frozenset(SCOPE_ALIASES)
GX3_SCOPES = ("unstaged", "staged", "commit", "branch", "last_turn")
SEVERITIES = ("P0", "P1", "P2", "P3", "info")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


class ReviewError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def is_git_repo(workspace: Path) -> bool:
    root = canonicalize(workspace)
    marker = root / ".git"
    if marker.exists():
        return True
    probe = _git(root, "rev-parse", "--is-inside-work-tree")
    return probe.returncode == 0 and probe.stdout.strip() == "true"


def tree_hash(workspace: Path) -> str:
    root = canonicalize(workspace)
    if is_git_repo(root):
        return current_diff(root, scope="working_tree", base_ref=None, head_ref=None, paths=None)["hash"]
    parts: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        parts.append(rel + ":" + hashlib.sha256(path.read_bytes()).hexdigest())
    return _sha256("\n".join(parts))


def _file_content_hash(root: Path, rel: str) -> str:
    target = assert_inside_workspace(root, root / rel)
    if not target.is_file():
        raise ReviewError("REVIEW_SCOPE_INVALID", f"file not found: {rel}")
    return "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()


def _files_from_diff(diff_text: str) -> list[str]:
    files: list[str] = []
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            files.append(line.split(" b/", 1)[-1])
    return files


def current_diff(
    workspace: Path,
    *,
    scope: str,
    base_ref: str | None,
    head_ref: str | None,
    paths: list[str] | None,
) -> dict[str, Any]:
    root = canonicalize(workspace)
    if not is_git_repo(root):
        raise ReviewError("REVIEW_DIFF_UNAVAILABLE", "not a git repository")
    path_args = []
    for item in paths or []:
        resolved = assert_inside_workspace(root, root / item)
        path_args.append(str(resolved.relative_to(root)).replace("\\", "/"))
    scope = SCOPE_ALIASES.get(scope, scope)
    if scope == "working_tree":
        tracked = _git(root, "diff", "--no-color", "HEAD", *(["--", *path_args] if path_args else []))
        if tracked.returncode != 0:
            tracked = _git(root, "diff", "--no-color", *(["--", *path_args] if path_args else []))
        untracked = _git(root, "ls-files", "--others", "--exclude-standard")
        parts = [tracked.stdout]
        files = []
        wanted = {item.replace("\\", "/") for item in path_args}
        for rel in [line for line in untracked.stdout.splitlines() if line.strip()]:
            norm = rel.replace("\\", "/")
            if wanted and norm not in wanted and not any(norm.startswith(item.rstrip("/") + "/") for item in wanted):
                continue
            target = root / rel
            if not target.is_file():
                continue
            data = target.read_bytes()
            if b"\0" in data[:8000] or len(data) > 200_000:
                parts.append(f"diff --git a/{rel} b/{rel}\nnew file (binary or large)\n")
            else:
                text = data.decode("utf-8", errors="replace")
                lines = text.splitlines()
                parts.append(
                    f"diff --git a/{rel} b/{rel}\n--- /dev/null\n+++ b/{rel}\n"
                    f"@@ -0,0 +1,{max(len(lines), 1)} @@\n"
                    + "".join(f"+{line}\n" for line in lines)
                )
            files.append(rel)
        status = _git(root, "status", "--porcelain")
        for line in status.stdout.splitlines():
            name = line[3:].strip().replace("\\", "/")
            if wanted and name not in wanted and not any(name.startswith(item.rstrip("/") + "/") for item in wanted):
                continue
            if name and name not in files:
                files.append(name)
        blob = "\n".join(part.rstrip() for part in parts if part).strip() + "\n"
        return {"diff": blob, "files": files, "untracked": True, "hash": _sha256(blob)}
    if scope == "unstaged":
        result = _git(root, "diff", "--no-color", *(["--", *path_args] if path_args else []))
        files = _files_from_diff(result.stdout)
        blob = result.stdout
        return {"diff": blob, "files": files, "untracked": False, "hash": _sha256(blob)}
    if scope == "staged":
        result = _git(root, "diff", "--cached", "--no-color", *(["--", *path_args] if path_args else []))
        files = _files_from_diff(result.stdout)
        blob = result.stdout
        return {"diff": blob, "files": files, "untracked": False, "hash": _sha256(blob)}
    if scope == "last_turn":
        return {"diff": "", "files": [], "untracked": False, "hash": _sha256(""), "empty_reason": "no_turn_diff"}
    if scope == "base_branch":
        ref = base_ref or "HEAD"
        result = _git(root, "diff", "--no-color", ref, *(["--", *path_args] if path_args else []))
    elif scope == "commit":
        ref = head_ref or "HEAD"
        result = _git(root, "show", "--no-color", "--format=", ref, *(["--", *path_args] if path_args else []))
    elif scope == "files":
        if not path_args:
            raise ReviewError("REVIEW_SCOPE_INVALID", "files scope requires paths")
        result = _git(root, "diff", "--no-color", "--", *path_args)
    else:
        raise ReviewError("REVIEW_SCOPE_INVALID", f"unknown scope: {scope}")
    files = []
    for line in result.stdout.splitlines():
        if line.startswith("diff --git "):
            files.append(line.split(" b/", 1)[-1])
    blob = result.stdout
    return {"diff": blob, "files": files, "untracked": False, "hash": _sha256(blob)}


def _findings_from_diff(diff_text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    current_file = ""
    line_no = 0
    seen_files: set[str] = set()
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            current_file = raw.split(" b/", 1)[-1]
            line_no = 0
            if current_file and current_file not in seen_files:
                seen_files.add(current_file)
                findings.append(
                    {
                        "finding_id": uuid.uuid4().hex[:12],
                        "severity": "info",
                        "file": current_file,
                        "start_line": 1,
                        "end_line": 1,
                        "title": "file changed",
                        "body": f"{current_file} changed in this review scope",
                        "evidence": current_file,
                        "recommendation": "Confirm the change is intended.",
                        "status": "open",
                    }
                )
            continue
        match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", raw)
        if match:
            line_no = int(match.group(1)) - 1
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            line_no = max(line_no + 1, 1)
            text = raw[1:]
            severity = None
            title = ""
            if re.search(r"(?i)(api[_-]?key|secret|password|authorization)\s*[:=]", text):
                severity, title = "P0", "possible secret in diff"
            elif re.search(r"\b(rm\s+-rf|os\.remove|unlink)\b", text):
                severity, title = "P1", "destructive file operation"
            elif "except" in text and "pass" in text:
                severity, title = "P2", "swallowed exception"
            elif "TODO" in text or "FIXME" in text:
                severity, title = "info", "unresolved marker"
            if severity:
                findings.append(
                    {
                        "finding_id": uuid.uuid4().hex[:12],
                        "severity": severity,
                        "file": current_file,
                        "start_line": line_no,
                        "end_line": line_no,
                        "title": title,
                        "body": text.strip()[:400],
                        "evidence": text.strip()[:400],
                        "recommendation": "Review or remove before merge.",
                        "status": "open",
                    }
                )
        elif raw.startswith(" ") or raw.startswith("-"):
            if raw.startswith(" "):
                line_no += 1
    return findings


def _parse_hunks(diff_text: str) -> list[dict[str, Any]]:
    hunks: list[dict[str, Any]] = []
    current_file = ""
    buf: list[str] = []
    header = ""
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if header and buf:
                hunks.append({"file": current_file, "header": header, "lines": buf})
            current_file = line.split(" b/", 1)[-1].strip()
            buf, header = [], ""
            continue
        if line.startswith("@@"):
            if header and buf:
                hunks.append({"file": current_file, "header": header, "lines": buf})
            header = line.rstrip("\n")
            buf = []
            continue
        if header:
            buf.append(line)
    if header and buf:
        hunks.append({"file": current_file, "header": header, "lines": buf})
    return hunks


def revert_hunk(workspace: Path, relpath: str, hunk_index: int) -> None:
    root = canonicalize(workspace)
    assert_inside_workspace(root, root / relpath)
    diff = _git(root, "diff", "--no-color", "--", relpath).stdout
    if not diff.strip():
        raise ReviewError("REVIEW_SCOPE_INVALID", "no hunks to revert")
    header: list[str] = []
    hunks: list[list[str]] = []
    current: list[str] = []
    in_hunk = False
    for line in diff.splitlines(keepends=True):
        if line.startswith("@@"):
            if in_hunk and current:
                hunks.append(current)
            current = [line]
            in_hunk = True
        elif in_hunk:
            current.append(line)
        else:
            header.append(line)
    if current:
        hunks.append(current)
    if hunk_index < 0 or hunk_index >= len(hunks):
        raise ReviewError("REVIEW_SCOPE_INVALID", "hunk index out of range")
    patch = "".join(header + hunks[hunk_index])
    tmp = root / f".rxycode-hunk-{uuid.uuid4().hex[:8]}.patch"
    tmp.write_text(patch, encoding="utf-8", newline="\n")
    try:
        result = _git(root, "apply", "-R", "--whitespace=nowarn", tmp.name)
        if result.returncode != 0:
            raise ReviewError("REVIEW_DIFF_UNAVAILABLE", result.stderr.strip() or "hunk revert failed")
    finally:
        tmp.unlink(missing_ok=True)


class ReviewService:
    def __init__(self) -> None:
        self._reviews: dict[str, dict[str, Any]] = {}
        self._by_request: dict[str, str] = {}
        self._running: set[str] = set()
        self._checkpoints: dict[str, dict[str, Any]] = {}
        self._comments: list[dict[str, Any]] = []
        self._seq = 0
        self._start_results: dict[str, dict[str, Any]] = {}

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _envelope(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": {
                "event_id": uuid.uuid4().hex,
                "sequence": self._next_seq(),
                "created_at": _now(),
                **payload,
            },
        }

    def start(
        self,
        *,
        request_id: str,
        session_id: str,
        workspace: Path,
        scope: str = "working_tree",
        base_ref: str | None = None,
        head_ref: str | None = None,
        paths: list[str] | None = None,
        turn_id: str | None = None,
        thread_id: str | None = None,
        criteria: list[str] | None = None,
        reviewer: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if request_id and request_id in self._start_results:
            return dict(self._start_results[request_id]), []
        scope = SCOPE_ALIASES.get(scope, scope)
        if scope not in {"working_tree", "base_branch", "commit", "files", "unstaged", "staged", "last_turn"}:
            raise ReviewError("REVIEW_SCOPE_INVALID", f"unknown scope: {scope}")
        if session_id in self._running:
            raise ReviewError("REVIEW_ALREADY_RUNNING", "a review is already running")
        events: list[dict[str, Any]] = []
        self._running.add(session_id)
        try:
            snapshot = current_diff(
                workspace, scope=scope, base_ref=base_ref, head_ref=head_ref, paths=paths
            )
            review_id = "rev_" + uuid.uuid4().hex[:10]
            findings = _findings_from_diff(snapshot["diff"])
            file_hashes: dict[str, str] = {}
            line_counts: dict[str, int] = {}
            for rel in snapshot["files"]:
                target = canonicalize(workspace) / rel
                if target.is_file():
                    data = target.read_bytes()
                    key = rel.replace("\\", "/")
                    file_hashes[key] = "sha256:" + hashlib.sha256(data).hexdigest()
                    line_counts[key] = len(data.decode("utf-8", errors="replace").splitlines())
            status = "has_findings" if any(item["severity"] != "info" for item in findings) else (
                "passed" if snapshot["diff"].strip() else "passed"
            )
            if findings and any(item["severity"] != "info" for item in findings):
                status = "has_findings"
            review = {
                "request_id": request_id,
                "review_id": review_id,
                "session_id": session_id,
                "thread_id": thread_id or session_id,
                "turn_id": turn_id,
                "scope": scope,
                "base_ref": base_ref,
                "head_ref": head_ref,
                "paths": list(paths or []),
                "criteria": list(criteria or []),
                "reviewer": reviewer or {"kind": "heuristic", "agent_id": "b8-reviewer"},
                "diff_hash": snapshot["hash"],
                "diff": snapshot["diff"],
                "files": snapshot["files"],
                "file_hashes": file_hashes,
                "line_counts": line_counts,
                "findings": findings,
                "status": status,
                "created_at": _now(),
                "workspace": str(canonicalize(workspace)),
            }
            review["events"] = []
            self._reviews[review_id] = review
            if request_id:
                self._by_request[request_id] = review_id
            events.append(
                self._envelope(
                    "review/started",
                    {"session_id": session_id, "review_id": review_id, "diff_hash": snapshot["hash"]},
                )
            )
            review["events"] = events
            events.append(
                self._envelope(
                    "review/progress",
                    {"session_id": session_id, "review_id": review_id, "status": "scanning"},
                )
            )
            for finding in findings:
                events.append(
                    self._envelope(
                        "review/finding",
                        {"session_id": session_id, "review_id": review_id, "finding": finding},
                    )
                )
            events.append(
                self._envelope(
                    "review/completed",
                    {
                        "session_id": session_id,
                        "review_id": review_id,
                        "status": status,
                        "diff_hash": snapshot["hash"],
                    },
                )
            )
            summary = {
                "request_id": request_id,
                "review_id": review_id,
                "status": "pending" if status == "has_findings" else status,
                "diff_hash": snapshot["hash"],
            }
            if request_id:
                self._start_results[request_id] = summary
            return summary, events
        except ReviewError as exc:
            events.append(
                self._envelope(
                    "review/failed",
                    {"session_id": session_id, "error_code": exc.code, "message": exc.message},
                )
            )
            raise
        finally:
            self._running.discard(session_id)

    def read(self, review_id: str, *, after_sequence: int | None = None) -> dict[str, Any]:
        review = self._reviews.get(review_id)
        if review is None:
            raise ReviewError("REVIEW_DIFF_UNAVAILABLE", f"unknown review: {review_id}")
        self.refresh_hashes(Path(review["workspace"]))
        payload = dict(self._reviews[review_id])
        events = list(payload.get("events") or [])
        if after_sequence is not None:
            filtered = []
            for item in events:
                params = item.get("params") if isinstance(item, dict) else None
                seq = 0
                if isinstance(params, dict):
                    seq = int(params.get("sequence") or 0)
                if seq > after_sequence:
                    filtered.append(item)
            events = filtered
        payload["events"] = events
        sequences = [
            int((item.get("params") or {}).get("sequence") or 0)
            for item in list(self._reviews[review_id].get("events") or [])
            if isinstance(item, dict)
        ]
        payload["next_cursor"] = max(sequences) if sequences else 0
        return payload

    def refresh_hashes(self, workspace: Path | None = None) -> list[str]:
        stale_ids: list[str] = []
        for review in self._reviews.values():
            if review["status"] in {"stale", "failed", "cancelled"}:
                continue
            root = Path(review["workspace"])
            if workspace is not None and canonicalize(workspace) != canonicalize(root):
                continue
            try:
                snapshot = current_diff(
                    root,
                    scope=str(review["scope"]),
                    base_ref=review.get("base_ref"),
                    head_ref=review.get("head_ref"),
                    paths=review.get("paths"),
                )
            except ReviewError:
                continue
            if snapshot["hash"] != review["diff_hash"]:
                review["status"] = "stale"
                for finding in review["findings"]:
                    if finding["status"] == "open":
                        evidence = str(finding.get("evidence") or "")
                        file_path = root / str(finding.get("file") or "")
                        if not file_path.is_file():
                            finding["status"] = "fixed"
                        elif evidence and evidence not in file_path.read_text(
                            encoding="utf-8", errors="replace"
                        ):
                            finding["status"] = "fixed"
                        else:
                            finding["status"] = "stale"
                stale_ids.append(str(review["review_id"]))
        return stale_ids

    def comment(
        self,
        *,
        review_id: str,
        finding_id: str | None,
        file: str,
        start_line: int,
        end_line: int,
        body: str,
        file_hash: str | None = None,
    ) -> dict[str, Any]:
        review = self._reviews.get(review_id)
        if review is None:
            raise ReviewError("REVIEW_DIFF_UNAVAILABLE", f"unknown review: {review_id}")
        if not finding_id:
            raise ReviewError("REVIEW_SCOPE_INVALID", "finding_id required")
        match = next((item for item in review["findings"] if item.get("finding_id") == finding_id), None)
        if match is None:
            raise ReviewError("REVIEW_SCOPE_INVALID", "finding does not belong to review")
        if match.get("file") and file and match["file"] != file:
            raise ReviewError("REVIEW_SCOPE_INVALID", "finding file mismatch")
        if review.get("files") and file not in review["files"]:
            raise ReviewError("REVIEW_SCOPE_INVALID", "file not in review scope")
        if start_line < 1 or end_line < start_line:
            raise ReviewError("REVIEW_SCOPE_INVALID", "invalid line range")
        line_limit = int((review.get("line_counts") or {}).get(file) or 0)
        if line_limit and end_line > line_limit:
            raise ReviewError("REVIEW_SCOPE_INVALID", "line range outside file")
        expected_hash = (review.get("file_hashes") or {}).get(file)
        if not expected_hash:
            raise ReviewError("REVIEW_SCOPE_INVALID", "no review-time file hash")
        if file_hash and file_hash != expected_hash:
            raise ReviewError("REVIEW_SCOPE_INVALID", "file_hash does not match review-time hash")
        record = {
            "comment_id": uuid.uuid4().hex[:12],
            "review_id": review_id,
            "finding_id": finding_id,
            "file": file,
            "file_hash": expected_hash,
            "start_line": start_line,
            "end_line": end_line,
            "body": body,
            "created_at": _now(),
        }
        self._comments.append(record)
        return dict(record)

    def comments(self, review_id: str) -> list[dict[str, Any]]:
        return [dict(item) for item in self._comments if item["review_id"] == review_id]

    def create_checkpoint(
        self,
        *,
        session_id: str,
        workspace: Path,
        reason: str = "write",
        turn_id: str | None = None,
        name: str | None = None,
        user_prompt: str | None = None,
        items_seq: int | None = None,
    ) -> dict[str, Any]:
        root = canonicalize(workspace)
        files: dict[str, str] = {}
        if is_git_repo(root):
            snapshot = current_diff(root, scope="working_tree", base_ref=None, head_ref=None, paths=None)
            names = snapshot["files"]
            diff_hash = snapshot["hash"]
        else:
            names = [str(path.relative_to(root)).replace("\\", "/") for path in root.rglob("*") if path.is_file()]
            diff_hash = tree_hash(root)
        for rel in names:
            target = root / rel
            if not target.is_file():
                continue
            data = target.read_bytes()
            if b"\0" in data[:8000] or len(data) > 400_000:
                continue
            files[rel.replace("\\", "/")] = data.decode("utf-8", errors="replace")
        seq = 1 + sum(1 for item in self._checkpoints.values() if item["session_id"] == session_id)
        record = {
            "checkpoint_id": "cp_" + uuid.uuid4().hex[:12],
            "session_id": session_id,
            "turn_id": turn_id,
            "workspace": str(root),
            "diff_hash": diff_hash,
            "files": files,
            "file_list": sorted(files),
            "reason": reason,
            "name": name,
            "user_prompt": user_prompt,
            "seq": seq,
            "items_seq": items_seq,
            "created_at": _now(),
        }
        self._checkpoints[record["checkpoint_id"]] = record
        return {key: value for key, value in record.items() if key != "files"} | {
            "file_count": len(files)
        }

    def list_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        rows = [
            {key: value for key, value in item.items() if key != "files"} | {"file_count": len(item["files"])}
            for item in self._checkpoints.values()
            if item["session_id"] == session_id
        ]
        return sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def read_checkpoint(self, checkpoint_id: str, *, session_id: str | None = None, include_files: bool = False) -> dict[str, Any]:
        item = self._checkpoints.get(checkpoint_id)
        if item is None:
            raise ReviewError("REVIEW_DIFF_UNAVAILABLE", f"unknown checkpoint: {checkpoint_id}")
        if not session_id:
            raise ReviewError("REVIEW_SCOPE_INVALID", "session_id required")
        if session_id != item["session_id"]:
            raise ReviewError("REVIEW_SCOPE_INVALID", "checkpoint does not belong to session")
        if include_files:
            return dict(item)
        return {key: value for key, value in item.items() if key != "files"} | {
            "file_count": len(item["files"])
        }

    def restore_checkpoint(self, checkpoint_id: str, *, session_id: str | None = None) -> dict[str, Any]:
        item = self._checkpoints.get(checkpoint_id)
        if item is None:
            raise ReviewError("REVIEW_DIFF_UNAVAILABLE", f"unknown checkpoint: {checkpoint_id}")
        if not session_id:
            raise ReviewError("REVIEW_SCOPE_INVALID", "session_id required")
        if session_id != item["session_id"]:
            raise ReviewError("REVIEW_SCOPE_INVALID", "checkpoint does not belong to session")
        root = Path(item["workspace"])

        before = tree_hash(root)
        if is_git_repo(root):
            current = current_diff(root, scope="working_tree", base_ref=None, head_ref=None, paths=None)
            for name in current["files"]:
                if name in item["files"]:
                    continue
                target = assert_inside_workspace(root, root / name)
                listed = _git(root, "ls-files", "--", name)
                if listed.stdout.strip():
                    _git(root, "checkout", "--", name)
                elif target.is_file():
                    target.unlink()
        else:
            current_names = {
                str(path.relative_to(root)).replace("\\", "/")
                for path in root.rglob("*")
                if path.is_file()
            }
            for name in current_names - set(item["files"]):
                target = assert_inside_workspace(root, root / name)
                if target.is_file():
                    target.unlink()
        for rel, content in item["files"].items():
            target = assert_inside_workspace(root, root / rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        scope_files = set(item["file_list"])
        stale: list[str] = []
        root_key = str(canonicalize(root))
        for review in self._reviews.values():
            if review["status"] in {"failed", "cancelled"}:
                continue
            if str(canonicalize(review["workspace"])) != root_key:
                continue
            overlap = (
                not scope_files
                or not review.get("files")
                or bool(set(review.get("files") or []) & scope_files)
            )
            if not overlap:
                continue
            review["status"] = "stale"
            for finding in review["findings"]:
                if finding["status"] == "open":
                    finding["status"] = "stale"
            stale.append(str(review["review_id"]))
        after = tree_hash(root)
        return {
            "checkpoint_id": checkpoint_id,
            "diff_hash": after,
            "previous_diff_hash": before,
            "stale_reviews": stale,
            "file_list": list(item["file_list"]),
        }

    def git_change(
        self,
        workspace: Path,
        *,
        action: str,
        paths: list[str],
        hunk_index: int | None = None,
        permission_store: Any = None,
        actor: str = "user",
        approval_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if permission_store is None:
            raise ReviewError("PERMISSION_DENIED", "git write requires permission")
        verdict = permission_store.evaluate(
            action=f"git_{action}",
            actor=actor,
            approval_id=approval_id,
            scope=str(canonicalize(workspace)),
            workspace=str(canonicalize(workspace)),
            session_id=session_id,
        )
        if verdict != "allow":
            raise ReviewError("PERMISSION_DENIED", "git write denied")
        root = canonicalize(workspace)
        if not is_git_repo(root):
            raise ReviewError("REVIEW_DIFF_UNAVAILABLE", "not a git repository")
        if not paths:
            raise ReviewError("REVIEW_SCOPE_INVALID", "paths required")
        resolved = [str(assert_inside_workspace(root, root / path).relative_to(root)).replace("\\", "/") for path in paths]
        if action == "stage":
            result = _git(root, "add", "--", *resolved)
        elif action == "unstage":
            result = _git(root, "restore", "--staged", "--", *resolved)
        elif action == "revert":
            if hunk_index is not None:
                revert_hunk(root, resolved[0], hunk_index)
                result = _git(root, "status", "--porcelain")
            else:
                result = _git(root, "checkout", "--", *resolved)
        else:
            raise ReviewError("REVIEW_SCOPE_INVALID", f"unknown git action: {action}")
        if result.returncode != 0 and action != "revert":
            raise ReviewError("REVIEW_DIFF_UNAVAILABLE", result.stderr.strip() or "git failed")
        stale = self.refresh_hashes(root)
        snapshot = current_diff(root, scope="working_tree", base_ref=None, head_ref=None, paths=None)
        return {"ok": True, "action": action, "paths": resolved, "diff_hash": snapshot["hash"], "stale_reviews": stale}
