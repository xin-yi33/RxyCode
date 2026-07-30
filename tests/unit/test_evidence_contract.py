import hashlib
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.execution.evidence import (
    build_tool_evidence,
    deterministic_issues,
)


def test_written_html_captures_hash_and_validity(tmp_path: Path):
    artifact = tmp_path / "calculator.html"
    content = "<html><body><output>0</output></body></html>"
    artifact.write_text(content, encoding="utf-8")

    evidence = build_tool_evidence(
        "write",
        {"filePath": str(artifact), "content": content},
        "[wrote 45 bytes]",
        executed=True,
        approval="auto",
    )

    assert evidence.passed is True
    assert evidence.artifacts[0].exists is True
    assert evidence.artifacts[0].valid is True
    assert len(evidence.artifacts[0].sha256 or "") == 64
    assert deterministic_issues([evidence]) == []


def test_preexisting_file_with_wrong_content_is_not_write_evidence(tmp_path: Path):
    artifact = tmp_path / "result.txt"
    artifact.write_text("old content", encoding="utf-8")

    evidence = build_tool_evidence(
        "write",
        {"filePath": str(artifact), "content": "requested content"},
        "[wrote 17 bytes]",
        executed=True,
        approval="auto",
    )

    assert evidence.status == "failed"
    assert evidence.artifacts[0].valid is False


def test_syntax_error_result_is_failed_even_when_content_matches(tmp_path: Path):
    artifact = tmp_path / "broken.py"
    content = "def broken(\n"
    artifact.write_text(content, encoding="utf-8")

    evidence = build_tool_evidence(
        "write",
        {"filePath": str(artifact), "content": content},
        "[wrote 12 bytes]\n[syntax check: SYNTAX_ERROR: line 1: '(' was never closed]",
        executed=True,
        approval="auto",
    )

    assert evidence.status == "failed"


def test_edit_requires_requested_replacement_in_artifact(tmp_path: Path):
    artifact = tmp_path / "module.py"
    artifact.write_text("value = 'old'\n", encoding="utf-8")

    evidence = build_tool_evidence(
        "edit",
        {
            "filePath": str(artifact),
            "oldString": "'old'",
            "newString": "'new'",
        },
        f"[edited {artifact}]",
        executed=True,
        approval="auto",
    )

    assert evidence.status == "failed"


def test_nonzero_command_is_never_successful_evidence():
    evidence = build_tool_evidence(
        "bash",
        {"command": "pytest"},
        "1 failed\n[exit code: 1]",
        executed=True,
        approval="auto",
    )

    assert evidence.status == "failed"
    assert deterministic_issues([evidence]) == [
        "Tool bash did not complete: failed"
    ]


def test_download_captures_published_artifact_hash(tmp_path: Path):
    artifact = tmp_path / "archive.bin"
    artifact.write_bytes(b"verified download")

    evidence = build_tool_evidence(
        "download_file",
        {"save_path": str(artifact)},
        f"Successfully downloaded file!\n  Saved to: {artifact}\n  Size: 17 bytes",
        executed=True,
        approval="auto",
    )

    assert evidence.passed is True
    assert evidence.artifacts[0].exists is True
    assert evidence.artifacts[0].size == 17
    assert evidence.artifacts[0].sha256 == hashlib.sha256(
        b"verified download"
    ).hexdigest()


def test_download_without_published_artifact_fails_closed():
    evidence = build_tool_evidence(
        "download_file",
        {"save_path": "missing.bin"},
        "Successfully downloaded file!",
        executed=True,
        approval="auto",
    )

    assert evidence.status == "failed"
    assert evidence.artifacts == []


@pytest.mark.parametrize(
    "result",
    [
        "[error: task T404 not found]",
        "[error: skill 'missing' not found in any skill directory]",
        "[error: memory #404 not found]",
        "[error: history directory not found]",
        "[error: workflow missing not found]",
        "[agent error] delegated agent crashed",
        # Legacy persisted/tool-plugin results remain fail-closed.
        "[task T404 not found]",
        "[not found: memory #404]",
    ],
)
def test_known_tool_failure_sentinels_are_never_successful(result):
    evidence = build_tool_evidence(
        "task",
        {"operation": "get"},
        result,
        executed=True,
        approval="auto",
    )

    assert evidence.status == "failed"
    assert evidence.passed is False


@pytest.mark.parametrize(
    "result",
    [
        "[no tasks]",
        "[no matches found]",
        "[no matching memory entries]",
        "No issues found in module.py.",
    ],
)
def test_successful_empty_queries_are_not_misclassified(result):
    evidence = build_tool_evidence(
        "grep",
        {"pattern": "absent"},
        result,
        executed=True,
        approval="auto",
    )

    assert evidence.status == "succeeded"
    assert evidence.passed is True
