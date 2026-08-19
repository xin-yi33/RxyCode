"""GX3 inline review comments. Persist on the review record, never in git."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .review import ReviewError, ReviewService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ReviewCommentService:
    """open → resolved | open → stale → resolved. stale never deleted, never reopened."""

    def __init__(self, reviews: ReviewService) -> None:
        self._reviews = reviews
        self._comments: dict[str, dict[str, Any]] = {}

    def add(
        self,
        *,
        review_id: str,
        file: str,
        line: int,
        hunk_hash: str,
        body: str,
    ) -> dict[str, Any]:
        review = self._reviews._reviews.get(review_id)
        if review is None:
            raise ReviewError("REVIEW_DIFF_UNAVAILABLE", f"unknown review: {review_id}")
        if int(line) < 1:
            raise ReviewError("REVIEW_SCOPE_INVALID", "invalid line")
        if not str(body or "").strip():
            raise ReviewError("REVIEW_SCOPE_INVALID", "body required")
        file_key = str(file).replace("\\", "/")
        files = [str(item).replace("\\", "/") for item in (review.get("files") or [])]
        if files and file_key not in files:
            raise ReviewError("REVIEW_SCOPE_INVALID", "file not in review scope")
        record = {
            "comment_id": "cmt_" + uuid.uuid4().hex[:10],
            "review_id": review_id,
            "file": file_key,
            "line": int(line),
            "hunk_hash": str(hunk_hash or ""),
            "body": str(body),
            "status": "open",
            "finding_id": None,
            "created_at": _now(),
        }
        findings = review.get("findings") or []
        match = next(
            (
                item
                for item in findings
                if str(item.get("file") or "").replace("\\", "/") == file_key
                and int(item.get("line") or 0) == int(line)
            ),
            None,
        )
        if match:
            record["finding_id"] = match.get("finding_id")
        self._comments[record["comment_id"]] = record
        return dict(record)

    def resolve(self, comment_id: str) -> dict[str, Any]:
        record = self._comments.get(str(comment_id or ""))
        if record is None:
            raise ReviewError("REVIEW_DIFF_UNAVAILABLE", f"unknown comment: {comment_id}")
        if record["status"] == "resolved":
            return dict(record)
        record["status"] = "resolved"
        record["resolved_at"] = _now()
        return dict(record)

    def mark_stale(self, comment_id: str) -> dict[str, Any]:
        record = self._comments.get(str(comment_id or ""))
        if record is None:
            raise ReviewError("REVIEW_DIFF_UNAVAILABLE", f"unknown comment: {comment_id}")
        if record["status"] == "resolved":
            return dict(record)
        record["status"] = "stale"
        return dict(record)

    def refresh_stale(self, review_id: str, current_hunk_hashes: dict[str, str]) -> None:
        for record in self._comments.values():
            if record["review_id"] != review_id or record["status"] != "open":
                continue
            key = f"{record['file']}:{record['line']}"
            expected = record.get("hunk_hash") or ""
            actual = current_hunk_hashes.get(key, "")
            if expected and actual and expected != actual:
                record["status"] = "stale"

    def list_for_review(self, review_id: str) -> list[dict[str, Any]]:
        return [dict(item) for item in self._comments.values() if item["review_id"] == review_id]
