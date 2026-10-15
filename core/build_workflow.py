"""Task-level build contract. The model chooses stages; the harness checks evidence.

This is not a tool and not a second model loop. Keyword length rules stay
where they are and are not reused as difficulty.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Literal, Mapping

Difficulty = Literal["simple", "medium", "complex"]
TaskKind = Literal["development", "question", "read_only"]
StageAction = Literal["inspect", "run", "skip"]
Predicate = Literal["exit_zero", "tests_passed_nonempty"]

STAGES = (
    "project_docs",
    "clarify",
    "design",
    "build_verify",
    "doc_sync",
)
_DIFFICULTIES = {"simple", "medium", "complex"}
_KINDS = {"development", "question", "read_only"}
_ACTIONS = {"inspect", "run", "skip"}
_PREDICATES = {"exit_zero", "tests_passed_nonempty"}


class WorkflowContractError(ValueError):
    """The model output is not a usable contract."""


@dataclass(frozen=True)
class RequiredCheck:
    check_id: str
    contract_revision: int
    command: str
    cwd: str
    success_predicate: Predicate
    required: bool = True


@dataclass(frozen=True)
class WorkflowDecision:
    workflow_id: str
    goal_revision: int
    contract_revision: int
    task_kind: TaskKind
    difficulty: Difficulty
    stage_actions: dict[str, StageAction]
    reason: str
    acceptance: tuple[str, ...]
    required_checks: tuple[RequiredCheck, ...]
    goal: str = ""


@dataclass(frozen=True)
class CheckReceipt:
    check_id: str
    workflow_id: str
    goal_revision: int
    contract_revision: int
    workspace_id: str
    subject_hash: str
    command: str
    cwd: str
    exit_code: int | None
    executed: bool
    predicate_passed: bool
    result_summary: str
    tool_result_ref: str


@dataclass(frozen=True)
class CompletionVerdict:
    accepted: bool
    missing: tuple[str, ...]
    stale: tuple[str, ...]
    reason: str


def workflow_enabled(config: Mapping | None) -> bool:
    if not isinstance(config, Mapping):
        return False
    execution = config.get("execution")
    if not isinstance(execution, Mapping):
        return False
    block = execution.get("build_workflow")
    if not isinstance(block, Mapping):
        return False
    return bool(block.get("enabled"))


def validate_decision(raw: Mapping, *, goal: str) -> WorkflowDecision:
    """Reject a contract that skips development verification or invents enums."""
    difficulty = str(raw.get("difficulty") or "")
    kind = str(raw.get("task_kind") or "")
    if difficulty not in _DIFFICULTIES:
        raise WorkflowContractError(f"difficulty must be simple, medium, or complex; got {difficulty}")
    if kind not in _KINDS:
        raise WorkflowContractError(f"unknown task_kind {kind}")
    actions = raw.get("stage_actions")
    if not isinstance(actions, Mapping):
        raise WorkflowContractError("stage_actions must be an object")
    stage_actions: dict[str, StageAction] = {}
    for stage in STAGES:
        action = str(actions.get(stage) or "")
        if action not in _ACTIONS:
            raise WorkflowContractError(f"stage {stage} needs inspect, run, or skip")
        stage_actions[stage] = action  # type: ignore[assignment]
    if kind == "development" and stage_actions["build_verify"] != "run":
        raise WorkflowContractError("development cannot skip build_verify")
    acceptance_raw = raw.get("acceptance") or []
    if not isinstance(acceptance_raw, list) or not acceptance_raw:
        raise WorkflowContractError("acceptance must name concrete outcomes")
    acceptance = tuple(str(item).strip() for item in acceptance_raw if str(item).strip())
    if not acceptance:
        raise WorkflowContractError("acceptance must name concrete outcomes")
    if any(item in {"功能正常", "works", "done"} for item in acceptance):
        raise WorkflowContractError("acceptance is too vague")
    checks: list[RequiredCheck] = []
    revision = int(raw.get("contract_revision") or 1)
    for item in raw.get("required_checks") or []:
        if not isinstance(item, Mapping):
            raise WorkflowContractError("required check must be an object")
        predicate = str(item.get("success_predicate") or "")
        if predicate not in _PREDICATES:
            raise WorkflowContractError(f"unknown success predicate {predicate}")
        command = str(item.get("command") or "").strip()
        cwd = str(item.get("cwd") or "").strip()
        check_id = str(item.get("check_id") or "").strip()
        if not command or not cwd or not check_id:
            raise WorkflowContractError("required check needs id, command, and cwd")
        checks.append(
            RequiredCheck(
                check_id=check_id,
                contract_revision=int(item.get("contract_revision") or revision),
                command=command,
                cwd=cwd,
                success_predicate=predicate,  # type: ignore[arg-type]
                required=bool(item.get("required", True)),
            )
        )
    if kind == "development" and not any(check.required for check in checks):
        raise WorkflowContractError("development requires at least one required check")
    workflow_id = str(raw.get("workflow_id") or "").strip()
    if not workflow_id:
        raise WorkflowContractError("workflow_id is required")
    return WorkflowDecision(
        workflow_id=workflow_id,
        goal_revision=int(raw.get("goal_revision") or 1),
        contract_revision=revision,
        task_kind=kind,  # type: ignore[arg-type]
        difficulty=difficulty,  # type: ignore[arg-type]
        stage_actions=stage_actions,
        reason=str(raw.get("reason") or "").strip(),
        acceptance=acceptance,
        required_checks=tuple(checks),
        goal=goal,
    )


def assign_workflow_id(text: str, goal: str) -> str:
    """Fill workflow_id when the model omits the identity field."""
    match = re.search(r"\{.*\}", text.strip(), re.S)
    if match is None:
        return text
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return text
    if not isinstance(raw, dict) or str(raw.get("workflow_id") or "").strip():
        return text
    raw["workflow_id"] = "wf-" + hashlib.sha256(goal.encode("utf-8")).hexdigest()[:12]
    return json.dumps(raw, ensure_ascii=False)


def parse_decision_text(text: str, *, goal: str) -> WorkflowDecision:
    body = text.strip()
    fenced = re.search(r"\{.*\}", body, re.S)
    if fenced is None:
        raise WorkflowContractError("classifier did not return JSON")
    try:
        raw = json.loads(fenced.group(0))
    except json.JSONDecodeError as exc:
        raise WorkflowContractError("classifier JSON is invalid") from exc
    if not isinstance(raw, dict):
        raise WorkflowContractError("classifier JSON must be an object")
    return validate_decision(raw, goal=goal)


def classify_workflow(
    ask: Callable[[str], str],
    goal: str,
    *,
    repair: Callable[[str], str] | None = None,
) -> WorkflowDecision:
    """Ask once. One protocol repair is allowed. Never fall back to simple."""
    prompt = (
        "Classify this development goal. Reply with one JSON object only. "
        "difficulty must be simple, medium, or complex based on the goal, "
        "not on prompt length or keyword lists. "
        "task_kind is development, question, or read_only. "
        "stage_actions keys are project_docs, clarify, design, build_verify, doc_sync. "
        "Each value is inspect, run, or skip. development must set build_verify to run "
        "and include at least one required_checks item with check_id, command, cwd, "
        "and success_predicate exit_zero or tests_passed_nonempty. "
        f"Goal:\n{goal}"
    )
    try:
        return parse_decision_text(ask(prompt), goal=goal)
    except WorkflowContractError:
        if repair is None:
            raise
        fixed = repair(prompt)
        return parse_decision_text(fixed, goal=goal)


def tests_passed_nonempty(text: str) -> bool:
    """True when a real run reported tests and zero failures."""
    if re.search(r"(\d+)\s+failed", text) and not re.search(r"\b0\s+failed\b", text):
        return False
    passed = re.search(r"(\d+)\s+passed", text)
    if passed is None:
        return False
    return int(passed.group(1)) > 0


def check_completion(
    workflow: WorkflowDecision,
    receipts: Mapping[str, CheckReceipt],
    workspace_id: str,
    subject: str,
) -> CompletionVerdict:
    required = [check for check in workflow.required_checks if check.required]
    if workflow.task_kind == "development" and not required:
        return CompletionVerdict(False, ("required_checks",), (), "development requires at least one check")
    if workflow.task_kind != "development" and not required:
        return CompletionVerdict(True, (), (), "no required checks")
    missing: list[str] = []
    stale: list[str] = []
    for check in required:
        if check.contract_revision != workflow.contract_revision:
            stale.append(check.check_id)
            continue
        receipt = receipts.get(check.check_id)
        if receipt is None or not receipt.executed or not receipt.tool_result_ref:
            missing.append(check.check_id)
            continue
        identity_matches = (
            receipt.check_id == check.check_id
            and receipt.workflow_id == workflow.workflow_id
            and receipt.goal_revision == workflow.goal_revision
            and receipt.contract_revision == workflow.contract_revision
            and receipt.workspace_id == workspace_id
            and receipt.subject_hash == subject
            and receipt.command == check.command
            and receipt.cwd == check.cwd
        )
        if not identity_matches:
            stale.append(check.check_id)
        elif receipt.exit_code != 0 or not receipt.predicate_passed:
            missing.append(check.check_id)
    accepted = not missing and not stale
    return CompletionVerdict(
        accepted,
        tuple(missing),
        tuple(stale),
        "checks satisfied" if accepted else "checks missing or stale",
    )


def retarget_contract(previous: WorkflowDecision, new: WorkflowDecision) -> WorkflowDecision:
    """Keep the task identity and drop a stale revision when the goal changes."""
    revision = max(int(new.contract_revision), int(previous.contract_revision) + 1)
    goal_revision = max(int(new.goal_revision), int(previous.goal_revision) + 1)
    checks = tuple(replace(check, contract_revision=revision) for check in new.required_checks)
    return replace(
        new,
        workflow_id=previous.workflow_id,
        contract_revision=revision,
        goal_revision=goal_revision,
        required_checks=checks,
    )


_DOC_SUFFIXES = {".md", ".rst", ".txt"}
_ORDINARY_SUFFIXES = {".txt", ".md", ".rst", ".log", ""}
_CODE_TOKENS = ("def ", "class ", "function ", "import ", "#include", "package ")


def is_documentation_path(path: str) -> bool:
    candidate = Path(str(path or ""))
    name = candidate.name.lower()
    suffix = candidate.suffix.lower()
    if suffix in _DOC_SUFFIXES:
        return True
    return name.startswith("changelog") or name in {"readme", "agents.md", "claude.md"}


def is_ordinary_text_save(path: str, content: str) -> bool:
    """User-supplied prose, not a source or test file."""
    text = str(path or "").strip()
    if not text:
        return False
    candidate = Path(text)
    if candidate.suffix.lower() not in _ORDINARY_SUFFIXES:
        return False
    sample = str(content or "")[:500]
    return not any(token in sample for token in _CODE_TOKENS)


def decision_to_jsonable(decision: WorkflowDecision) -> dict:
    return {
        "workflow_id": decision.workflow_id,
        "goal_revision": decision.goal_revision,
        "contract_revision": decision.contract_revision,
        "task_kind": decision.task_kind,
        "difficulty": decision.difficulty,
        "stage_actions": dict(decision.stage_actions),
        "reason": decision.reason,
        "acceptance": list(decision.acceptance),
        "goal": decision.goal,
        "required_checks": [
            {
                "check_id": check.check_id,
                "contract_revision": check.contract_revision,
                "command": check.command,
                "cwd": check.cwd,
                "success_predicate": check.success_predicate,
                "required": check.required,
            }
            for check in decision.required_checks
        ],
    }


def checkpoint_payload(
    decision: WorkflowDecision,
    receipts: Mapping[str, CheckReceipt],
    *,
    stage_progress: Mapping[str, str] | None = None,
    plan_revision: int = 1,
    plan_status: str = "pending",
    plan_goal: str = "",
    plan_bound_revision: int | None = None,
    clarify_answered: bool = False,
    write_generation: int = 0,
    touched_dirs: tuple[str, ...] | list[str] = (),
) -> dict:
    """JSON workflow identity, revisions, stage progress, and receipt refs."""
    body = decision_to_jsonable(decision)
    body["receipts"] = [
        {
            "check_id": receipt.check_id,
            "workflow_id": receipt.workflow_id,
            "goal_revision": receipt.goal_revision,
            "contract_revision": receipt.contract_revision,
            "workspace_id": receipt.workspace_id,
            "subject_hash": receipt.subject_hash,
            "command": receipt.command,
            "cwd": receipt.cwd,
            "exit_code": receipt.exit_code,
            "executed": receipt.executed,
            "predicate_passed": receipt.predicate_passed,
            "tool_result_ref": receipt.tool_result_ref,
        }
        for receipt in receipts.values()
    ]
    body["stage_progress"] = dict(stage_progress or {})
    body["plan_revision"] = int(plan_revision)
    body["plan_status"] = str(plan_status or "pending")
    body["plan_goal"] = str(plan_goal or decision.goal)
    body["plan_bound_revision"] = plan_bound_revision
    body["clarify_answered"] = bool(clarify_answered)
    body["write_generation"] = int(write_generation)
    body["touched_dirs"] = list(touched_dirs)
    return body


def workflow_from_checkpoint(
    payload: Mapping,
) -> tuple[WorkflowDecision, dict[str, CheckReceipt]]:
    goal = str(payload.get("goal") or "")
    decision = validate_decision(payload, goal=goal)
    receipts: dict[str, CheckReceipt] = {}
    for item in payload.get("receipts") or []:
        if not isinstance(item, Mapping):
            continue
        check_id = str(item.get("check_id") or "")
        if not check_id:
            continue
        receipts[check_id] = CheckReceipt(
            check_id=check_id,
            workflow_id=str(item.get("workflow_id") or ""),
            goal_revision=int(item.get("goal_revision") or 0),
            contract_revision=int(item.get("contract_revision") or 0),
            workspace_id=str(item.get("workspace_id") or ""),
            subject_hash=str(item.get("subject_hash") or ""),
            command=str(item.get("command") or ""),
            cwd=str(item.get("cwd") or ""),
            exit_code=item.get("exit_code"),
            executed=bool(item.get("executed")),
            predicate_passed=bool(item.get("predicate_passed")),
            result_summary="",
            tool_result_ref=str(item.get("tool_result_ref") or ""),
        )
    return decision, receipts
