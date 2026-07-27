from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest


def _passed_tree(*, result: str, evidence: list[dict] | None = None):
    from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree

    task = TaskNode(
        id="leaf-1",
        title="verified task",
        description="complete the requested work",
        requirement="return only verified results",
        status=TaskStatus.PASSED,
        result=result,
        evidence=evidence or [],
        is_atomic=True,
    )
    return TaskTree(goal_id=task.id, nodes={task.id: task}), task


def _manifest_for_sources(sources):
    claims = [
        {
            "task_id": source.task_id,
            "source_id": source.source_id,
            "text": source.text,
        }
        for source in sources
    ]
    return {
        "answer": "\n\n".join(claim["text"] for claim in claims),
        "claims": claims,
    }


def test_pure_text_result_is_grounded_without_tool_evidence():
    from RxyCode.RxyCode1_1_0.validation.final_output import (
        build_grounding_sources,
        verify_grounded_synthesis,
    )

    tree, _ = _passed_tree(result="The answer is 42.")
    manifest = _manifest_for_sources(build_grounding_sources(tree))

    issues, metrics = verify_grounded_synthesis(
        tree,
        manifest["answer"],
        manifest,
    )

    assert issues == []
    assert metrics["claim_count"] == metrics["grounded_claim_count"] == 1


def test_dynamic_read_evidence_is_not_required_as_side_effect_grounding():
    from RxyCode.RxyCode1_1_0.validation.final_output import build_grounding_sources

    tree, _ = _passed_tree(
        result="Memory search found the requested context.",
        evidence=[{
            "tool": "memory",
            "risk": "READ",
            "status": "succeeded",
            "executed": True,
            "detail": "memory search complete",
        }],
    )

    sources = build_grounding_sources(tree)
    memory_source = next(
        source for source in sources if source.kind == "tool_evidence"
    )

    assert memory_source.required is False


@pytest.mark.parametrize(
    ("mutation", "expected_issue"),
    [
        (
            "unsupported_claim",
            "Claim 0 is not a verbatim source excerpt",
        ),
        (
            "forged_source",
            "Claim 0 references unknown source_id",
        ),
    ],
)
def test_tampered_or_unsupported_claims_fail_closed(mutation, expected_issue):
    from RxyCode.RxyCode1_1_0.validation.final_output import (
        build_grounding_sources,
        verify_grounded_synthesis,
    )

    tree, _ = _passed_tree(result="Unit tests passed: 12.")
    manifest = _manifest_for_sources(build_grounding_sources(tree))
    if mutation == "unsupported_claim":
        manifest["claims"][0]["text"] = "Production deployment completed."
        manifest["answer"] = manifest["claims"][0]["text"]
    elif mutation == "forged_source":
        manifest["claims"][0]["source_id"] = "src_" + "0" * 64

    issues, _ = verify_grounded_synthesis(
        tree,
        manifest["answer"],
        manifest,
    )

    assert expected_issue in issues


def test_extra_answer_prose_is_repaired_to_canonical():
    """A pure formatting mismatch (valid verbatim claims wrapped in extra
    prose) must be repaired to the canonical grounded answer, not fail the
    whole build.  The repaired answer stays fully grounded because it is the
    concatenation of verbatim source excerpts only."""
    from RxyCode.RxyCode1_1_0.validation.final_output import (
        build_grounding_sources,
        verify_grounded_synthesis,
    )

    tree, _ = _passed_tree(result="Unit tests passed: 12.")
    manifest = _manifest_for_sources(build_grounding_sources(tree))
    # Synthesizer wraps the grounded claims in a chatty prefix/suffix.
    manifest["answer"] = (
        "Here is your result:\n\n" + manifest["answer"] + "\n\nHope that helps!"
    )

    issues, metrics = verify_grounded_synthesis(
        tree,
        manifest["answer"],
        manifest,
    )

    assert issues == [], f"expected no hard issues, got: {issues}"
    assert metrics["repaired_answer"] is not None
    expected_canonical = "\n\n".join(
        claim["text"] for claim in manifest["claims"]
    ).strip()
    assert metrics["repaired_answer"] == expected_canonical


def test_required_side_effect_evidence_cannot_be_hidden_by_optimistic_result():
    from RxyCode.RxyCode1_1_0.validation.final_output import (
        build_grounding_sources,
        verify_grounded_synthesis,
    )

    tree, _ = _passed_tree(
        result="The requested file was updated.",
        evidence=[{
            "tool": "write",
            "status": "succeeded",
            "executed": True,
            "detail": "[wrote 10 bytes to output.txt]",
        }],
    )
    sources = build_grounding_sources(tree)
    result_source = next(source for source in sources if source.kind == "result")
    manifest = _manifest_for_sources([result_source])

    issues, metrics = verify_grounded_synthesis(
        tree,
        manifest["answer"],
        manifest,
    )

    assert any("Side-effect evidence is not represented" in issue for issue in issues)
    assert metrics["required_source_count"] == 1


def test_passed_side_effect_task_without_tool_evidence_fails_final_verification():
    from RxyCode.RxyCode1_1_0.validation.final_output import (
        build_grounding_sources,
        verify_grounded_synthesis,
    )

    tree, task = _passed_tree(result="Created output.txt.")
    task.title = "Create output file"
    task.description = "Write the requested content to output.txt"
    task.requirement = "output.txt exists"
    task.tools_hint = ["write"]
    manifest = _manifest_for_sources(build_grounding_sources(tree))

    issues, _ = verify_grounded_synthesis(
        tree,
        manifest["answer"],
        manifest,
    )

    assert any(
        "Passed side-effect task has no verified WRITE/DANGER evidence" in issue
        for issue in issues
    )


def test_explicit_write_effect_fails_final_verification_even_for_vague_prose():
    from RxyCode.RxyCode1_1_0.validation.final_output import (
        build_grounding_sources,
        verify_grounded_synthesis,
    )

    tree, task = _passed_tree(result="Done.")
    task.effect = "write"
    manifest = _manifest_for_sources(build_grounding_sources(tree))

    issues, _ = verify_grounded_synthesis(
        tree,
        manifest["answer"],
        manifest,
    )

    assert any("no verified WRITE/DANGER evidence" in issue for issue in issues)


def test_all_required_side_effect_sources_can_be_verified():
    from RxyCode.RxyCode1_1_0.validation.final_output import (
        build_grounding_sources,
        verify_grounded_synthesis,
    )

    tree, _ = _passed_tree(
        result="The requested file was updated.",
        evidence=[{
            "tool": "write",
            "status": "succeeded",
            "executed": True,
            "detail": "[wrote 10 bytes to output.txt]",
        }],
    )
    manifest = _manifest_for_sources(build_grounding_sources(tree))

    issues, metrics = verify_grounded_synthesis(
        tree,
        manifest["answer"],
        manifest,
    )

    assert issues == []
    assert metrics["required_source_count"] == 1


def test_artifact_hash_is_rechecked_at_final_boundary(tmp_path):
    from RxyCode.RxyCode1_1_0.validation.final_output import (
        build_grounding_sources,
        verify_grounded_synthesis,
    )

    artifact = tmp_path / "answer.txt"
    artifact.write_text("verified", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    tree, _ = _passed_tree(
        result="The artifact was created.",
        evidence=[{
            "tool": "write",
            "status": "succeeded",
            "executed": True,
            "detail": f"[wrote 8 bytes to {artifact}]",
            "artifacts": [{
                "path": str(artifact),
                "exists": True,
                "size": 8,
                "sha256": digest,
                "valid": True,
            }],
        }],
    )
    manifest = _manifest_for_sources(build_grounding_sources(tree))
    artifact.write_text("tampered", encoding="utf-8")

    issues, _ = verify_grounded_synthesis(
        tree,
        manifest["answer"],
        manifest,
    )

    assert any("changed after execution" in issue for issue in issues)


@pytest.mark.asyncio
async def test_graph_final_verifier_rejects_manifest_claim_tampering():
    from RxyCode.RxyCode1_1_0.core.graph import final_verifier_node
    from RxyCode.RxyCode1_1_0.validation.final_output import (
        build_grounding_sources,
    )

    tree, _ = _passed_tree(result="Static analysis passed.")
    manifest = _manifest_for_sources(build_grounding_sources(tree))
    manifest["claims"][0]["text"] = "All production changes were deployed."
    manifest["answer"] = manifest["claims"][0]["text"]
    memory = AsyncMock()
    state = {
        "task_tree": tree,
        "session_id": "session-1",
        "final_response": manifest["answer"],
        "final_verification": {
            "synthesis_manifest": manifest,
            "synthesis_error": None,
        },
        "_memory": memory,
    }

    update = await final_verifier_node(state)

    assert update["final_verification"]["passed"] is False
    assert "构建流程未完成" in update["final_response"] or "校验" in update["final_response"]
    assert "Synthesizer" not in update["final_response"]
    assert "manifest" not in update["final_response"].lower()
    memory.store_execution.assert_not_awaited()
    memory.store_plan_experience.assert_not_awaited()


@pytest.mark.asyncio
async def test_graph_final_verifier_persists_only_verified_plan_success(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "memory:\n  experience_cross_session: false\n",
        encoding="utf-8",
    )
    from RxyCode.RxyCode1_1_0.core.graph import final_verifier_node
    from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager
    from RxyCode.RxyCode1_1_0.validation.final_output import (
        build_grounding_sources,
    )

    tree, _ = _passed_tree(result="Database migration verification passed.")
    manifest = _manifest_for_sources(build_grounding_sources(tree))
    memory = MemoryManager(session_id="verified-session")
    state = {
        "task_tree": tree,
        "session_id": "verified-session",
        "final_response": manifest["answer"],
        "final_verification": {
            "synthesis_manifest": manifest,
            "synthesis_error": None,
        },
        "_memory": memory,
    }

    update = await final_verifier_node(state)

    assert update["final_verification"]["passed"] is True
    records = memory.experience.search(
        "Database migration verification",
        kind="plan_outcome",
        outcome="success",
        session="verified-session",
    )
    assert len(records) == 1
    assert '"failure_type":"none"' in records[0].text
    assert '"outcome":"success"' in records[0].text


@pytest.mark.asyncio
async def test_graph_rejects_unstructured_synthesizer_output_after_repair():
    from RxyCode.RxyCode1_1_0.core.graph import (
        final_verifier_node,
        synthesizer_node,
    )

    tree, _ = _passed_tree(result="Verified analytical answer.")
    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="Everything completed successfully.")
    )
    memory = AsyncMock()
    state = {
        "task_tree": tree,
        "session_id": "session-1",
        "user_input": "perform the requested task",
        "_llm": llm,
        "_memory": memory,
        "_tui": None,
    }

    synthesis_update = await synthesizer_node(state)
    state.update(synthesis_update)
    final_update = await final_verifier_node(state)

    assert llm.ainvoke.await_count == 2
    assert synthesis_update["phase"] == "verifying"
    assert synthesis_update["final_verification"]["synthesis_manifest"] is None
    assert final_update["final_verification"]["passed"] is False
    assert "构建流程未完成" in final_update["final_response"] or "校验" in final_update["final_response"]
    assert "Synthesizer" not in final_update["final_response"]
    memory.store_execution.assert_not_awaited()
    memory.store_plan_experience.assert_not_awaited()
