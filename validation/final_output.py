"""Deterministic claim-to-evidence grounding for synthesized answers.

The synthesizer is allowed to select excerpts, but it is not trusted to
invent or paraphrase facts.  Every displayed claim must be an exact excerpt
from a validated leaf result or from a successful tool-boundary evidence
record.  The final answer is then the canonical concatenation of those
claims, so prose outside the manifest cannot bypass verification.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
from RxyCode.RxyCode1_1_0.core.state import TaskStatus, TaskTree
from RxyCode.RxyCode1_1_0.execution.evidence import ToolEvidence
from RxyCode.RxyCode1_1_0.validation.side_effects import (
    evidence_risk_level,
    is_supporting_effect,
)


MAX_RESULT_SOURCE_CHARS = 2000


class GroundingSource(BaseModel):
    """One immutable source exposed to the output synthesizer."""

    source_id: str
    task_id: str
    kind: Literal["result", "tool_evidence"]
    text: str
    required: bool = False


class GroundedClaim(BaseModel):
    """A verbatim final-answer claim bound to one source and leaf task."""

    task_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=MAX_RESULT_SOURCE_CHARS)

    @field_validator("task_id", "source_id", "text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class GroundedSynthesis(BaseModel):
    """Structured output contract produced by the synthesis model."""

    answer: str = ""
    claims: list[GroundedClaim] = Field(default_factory=list, max_length=128)

    @field_validator("answer")
    @classmethod
    def strip_answer(cls, value: str) -> str:
        return value.strip()


def canonical_answer(claims: list[GroundedClaim]) -> str:
    """Render the only final-answer form accepted by the verifier."""
    return "\n\n".join(claim.text for claim in claims).strip()


def _source_id(task_id: str, kind: str, index: int, text: str) -> str:
    payload = json.dumps(
        [task_id, kind, index, text],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"src_{digest}"


def build_grounding_sources(tree: TaskTree) -> list[GroundingSource]:
    """Build stable sources from passed leaves and successful tool evidence."""
    sources: list[GroundingSource] = []
    for task in tree.get_leaf_nodes():
        if task.status != TaskStatus.PASSED:
            continue
        # Verification/check tasks (effect=read/verify/check/...) are
        # confirmations, not deliverables; exclude them from the grounded-claim
        # deliverable contract so a successful "verify file integrity" task does
        # not have to be cited verbatim as if it produced an artifact.
        if is_supporting_effect(task.effect):
            continue

        result = str(task.result or "").strip()[:MAX_RESULT_SOURCE_CHARS]
        if result:
            sources.append(
                GroundingSource(
                    source_id=_source_id(task.id, "result", 0, result),
                    task_id=task.id,
                    kind="result",
                    text=result,
                )
            )

        for index, raw_record in enumerate(task.evidence):
            try:
                record = ToolEvidence.model_validate(raw_record)
            except Exception:
                continue
            if not record.passed:
                continue
            detail = record.detail.strip() or (
                f"[verified successful tool execution: {record.tool}]"
            )
            evidence_risk = evidence_risk_level(record)
            sources.append(
                GroundingSource(
                    source_id=_source_id(
                        task.id,
                        "tool_evidence",
                        index,
                        detail,
                    ),
                    task_id=task.id,
                    kind="tool_evidence",
                    text=detail,
                    # Invalid dynamic risk is not trusted to downgrade a source.
                    required=(
                        evidence_risk is None or evidence_risk >= RiskLevel.WRITE
                    ),
                )
            )
    return sources


def _live_artifact_issues(tree: TaskTree) -> list[str]:
    """Re-check persisted artifact facts immediately before final output."""
    issues: list[str] = []
    for task in tree.get_leaf_nodes():
        if task.status != TaskStatus.PASSED:
            continue
        for raw_record in task.evidence:
            try:
                record = ToolEvidence.model_validate(raw_record)
            except Exception as exc:
                issues.append(
                    f"Malformed tool evidence for task {task.id}: "
                    f"{type(exc).__name__}"
                )
                continue
            for artifact in record.artifacts:
                path = Path(artifact.path)
                if not path.is_file():
                    issues.append(f"Verified artifact disappeared: {artifact.path}")
                    continue
                try:
                    current_size = path.stat().st_size
                except OSError as exc:
                    issues.append(
                        f"Verified artifact cannot be inspected: {artifact.path} "
                        f"({type(exc).__name__})"
                    )
                    continue
                if artifact.size is not None and current_size != artifact.size:
                    issues.append(
                        f"Verified artifact size changed after execution: {artifact.path}"
                    )
                if artifact.sha256:
                    try:
                        digest = hashlib.sha256()
                        with path.open("rb") as artifact_file:
                            for chunk in iter(
                                lambda: artifact_file.read(1024 * 1024),
                                b"",
                            ):
                                digest.update(chunk)
                        current_hash = digest.hexdigest()
                    except OSError as exc:
                        issues.append(
                            f"Verified artifact cannot be read: {artifact.path} "
                            f"({type(exc).__name__})"
                        )
                        continue
                    if current_hash != artifact.sha256:
                        issues.append(
                            f"Verified artifact changed after execution: {artifact.path}"
                        )
    return issues


def verify_grounded_synthesis(
    tree: TaskTree,
    final_response: str,
    manifest: GroundedSynthesis | dict | None,
) -> tuple[list[str], dict[str, int]]:
    """Return deterministic grounding issues and manifest coverage metrics."""
    issues: list[str] = []
    repaired_answer: str | None = None
    try:
        synthesis = (
            manifest
            if isinstance(manifest, GroundedSynthesis)
            else GroundedSynthesis.model_validate(manifest)
        )
    except Exception as exc:
        return (
            [f"Missing or invalid synthesis manifest: {type(exc).__name__}"],
            {"claim_count": 0, "grounded_claim_count": 0},
        )

    sources = build_grounding_sources(tree)
    from RxyCode.RxyCode1_1_0.validation.side_effects import (
        has_verified_side_effect,
        task_requires_side_effect_evidence,
    )

    for task in tree.get_leaf_nodes():
        if task.status != TaskStatus.PASSED:
            continue
        if task_requires_side_effect_evidence(
            title=task.title,
            description=task.description,
            requirement=task.requirement,
            result=task.result or "",
            tools_hint=task.tools_hint,
            effect=task.effect,
        ) and not has_verified_side_effect(task.evidence):
            issues.append(
                "Passed side-effect task has no verified WRITE/DANGER evidence: "
                f"{task.id}"
            )
    source_by_id = {source.source_id: source for source in sources}
    passed_leaf_ids = {
        task.id
        for task in tree.get_leaf_nodes()
        if task.status == TaskStatus.PASSED
        and not is_supporting_effect(task.effect)
    }
    cited_task_ids: set[str] = set()
    cited_source_ids: set[str] = set()
    grounded_count = 0
    seen_claims: set[tuple[str, str]] = set()

    if not synthesis.claims:
        issues.append("Synthesizer produced no grounded claims")

    for index, claim in enumerate(synthesis.claims):
        key = (claim.source_id, claim.text)
        if key in seen_claims:
            issues.append(f"Duplicate grounded claim at index {index}")
            continue
        seen_claims.add(key)

        source = source_by_id.get(claim.source_id)
        if source is None:
            issues.append(f"Claim {index} references unknown source_id")
            continue
        if claim.task_id != source.task_id:
            issues.append(f"Claim {index} task_id does not match its source")
            continue
        if claim.task_id not in passed_leaf_ids:
            issues.append(f"Claim {index} references a task that is not passed")
            continue
        if claim.text not in source.text:
            issues.append(f"Claim {index} is not a verbatim source excerpt")
            continue
        cited_task_ids.add(claim.task_id)
        cited_source_ids.add(claim.source_id)
        grounded_count += 1

    expected_answer = canonical_answer(synthesis.claims)
    # A *pure formatting* mismatch (the synthesizer wraps valid, verbatim,
    # fully-cited claims in extra prose) is NOT a grounding failure.  The
    # canonical concatenation is itself built only from verified source excerpts,
    # so it is fully grounded.  Repair the final answer to that canonical form
    # instead of failing the whole build and discarding a real deliverable.
    # The hard anti-hallucination guarantees (claims are verbatim excerpts of
    # passed-leaf sources, every passed leaf is cited, required side-effects are
    # represented, artifacts are present) are enforced by the checks above and
    # remain the fail-closed criteria.
    format_mismatch = synthesis.answer != expected_answer
    response_mismatch = str(final_response or "").strip() != synthesis.answer
    if format_mismatch or response_mismatch:
        if issues:
            if format_mismatch:
                issues.append(
                    "Synthesis answer contains text outside its claim manifest"
                )
            if response_mismatch:
                issues.append(
                    "Final response differs from the verified synthesis manifest"
                )
        else:
            repaired_answer = expected_answer

    missing_tasks = passed_leaf_ids - cited_task_ids
    for task_id in sorted(missing_tasks):
        issues.append(f"Passed leaf has no grounded final claim: {task_id}")

    for source in sources:
        if source.required and source.source_id not in cited_source_ids:
            issues.append(
                "Side-effect evidence is not represented in the final answer: "
                f"{source.source_id}"
            )

    issues.extend(_live_artifact_issues(tree))
    return (
        list(dict.fromkeys(issues)),
        {
            "claim_count": len(synthesis.claims),
            "grounded_claim_count": grounded_count,
            "source_count": len(sources),
            "required_source_count": sum(source.required for source in sources),
            "repaired_answer": repaired_answer,
        },
    )
