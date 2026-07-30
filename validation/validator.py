"""Validator: three-dimensional result validation."""

from __future__ import annotations
from pydantic import BaseModel, Field
from RxyCode.RxyCode1_1_0.core.prompts import get_system_prompt, build_user_message, get_role_prompt
from RxyCode.RxyCode1_1_0.planning.structured_output import (
    StructuredOutputError,
    invoke_structured_output,
)


class ValidationResult(BaseModel):
    passed: bool = False
    completeness_score: float = Field(ge=0, le=1, default=0)
    relevance_score: float = Field(ge=0, le=1, default=0)
    format_score: float = Field(ge=0, le=1, default=0)
    issues: list[str] = Field(default_factory=list)
    suggestion: str = ""


class Validator:
    def __init__(self, llm, pass_threshold: float = 0.7):
        self._llm = llm
        self._pass_threshold = pass_threshold

    async def validate(
        self,
        title: str,
        description: str,
        requirement: str,
        result: str,
        evidence: list[dict] | None = None,
        tools_hint: list[str] | None = None,
        effect: str = "auto",
    ) -> ValidationResult:
        from langchain_core.messages import HumanMessage, SystemMessage
        from RxyCode.RxyCode1_1_0.execution.evidence import deterministic_issues

        records = evidence or []
        issues = deterministic_issues(records)
        from RxyCode.RxyCode1_1_0.validation.side_effects import (
            has_verified_side_effect,
            task_requires_side_effect_evidence,
        )

        if task_requires_side_effect_evidence(
            title=title,
            description=description,
            requirement=requirement,
            result=result,
            tools_hint=tools_hint or (),
            effect=effect,
        ) and not has_verified_side_effect(records):
            issues.append(
                "Task requires a verified WRITE/DANGER tool action; prose alone "
                "cannot prove the side effect"
            )
        lowered = (result or "").strip().lower()
        if lowered.startswith(("[executor error]", "[task_stall_timeout]", "[task_max_time]")):
            issues.append("Execution did not complete normally")

        requested = f"{title}\n{description}\n{requirement}".lower()
        requests_open = (
            ("html" in requested and any(word in requested for word in ("open", "browser", "打开", "浏览器")))
        )
        if requests_open:
            open_evidence = any(
                item.get("executed") is True
                and item.get("status") == "succeeded"
                and item.get("tool", "").lower() in {"open", "open_file", "browser"}
                for item in records
                if isinstance(item, dict)
            )
            if not open_evidence:
                issues.append("No verified browser/file-open action was executed")
        if issues:
            return ValidationResult(passed=False, issues=issues, suggestion="Retry the failed tool action and verify its evidence.")

        task_content = f"Task: {title}\nDescription: {description}\nAcceptance criteria: {requirement or '(no specific criteria)'}\nExecution result:\n{result or '(no result)'}"
        user_msg = build_user_message(get_role_prompt("validator"), task_content)
        messages = [SystemMessage(content=get_system_prompt()), HumanMessage(content=user_msg)]
        try:
            vr = await invoke_structured_output(
                self._llm,
                messages,
                ValidationResult,
            )
        except StructuredOutputError as exc:
            vr = ValidationResult(passed=False, issues=[str(exc)])
        vr.passed = all(score >= self._pass_threshold for score in [vr.completeness_score, vr.relevance_score, vr.format_score])
        return vr
