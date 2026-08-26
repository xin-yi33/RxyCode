"""机械验证门。

在 LLM 审计之前跑确定性检查。抄 karajan-code 的 "deterministic first, then
cross-AI review" 和 local-ai-agent-orchestrator 在 coder 与 reviewer 之间
插入的 mechanical verification。

省钱逻辑：机械检查过不了就直接打回 coder，审计模型一个 token 都不用花。
可靠性逻辑：「文件存在吗」「能编译吗」这类问题不该交给 LLM 判断。

本模块**不得引入任何 LLM 调用**。有测试守这条。
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from RxyCode.RxyCode1_1_0.protocol.agents import SopStage

#: low = compile/run/lint; high = task-spec / game-rule semantics (MAST FC3).
CHECK_LEVELS: dict[str, str] = {
    "files_exist": "low",
    "python_parses": "low",
    "json_parses": "low",
    "yaml_parses": "low",
    "lint_clean": "low",
    "tests_pass": "low",
    "no_forbidden": "low",
    "diff_non_empty": "low",
    "goal_satisfied": "high",
}

#: Contract: software_dev/team.yaml must copy into each stage's verify_before_next.
#: implement mixes low-level gates with the high-level goal check.
SOFTWARE_DEV_STAGE_CHECKS: dict[str, list[str]] = {
    "clarify": [],
    "plan": [],
    "implement": [
        "diff_non_empty",
        "files_exist",
        "python_parses",
        "lint_clean",
        "goal_satisfied",
    ],
    "test": ["files_exist", "python_parses"],
    "verify": [
        "files_exist",
        "python_parses",
        "lint_clean",
        "tests_pass",
    ],
    "audit": ["goal_satisfied"],
    "document": [],
}

_FORBIDDEN_DEFAULT = ("credentials.yaml", ".env", "data/")
_TEST_FILE_RE = re.compile(r"(?:tests[/\\])?test_[\w]+\.py", re.I)
_PRODUCT_FILE_RE = re.compile(r"(?:[\w.-]+/)*[\w.-]+\.py")


def named_product_files(user_input: str) -> list[str]:
    """Product ``.py`` paths the user named. Tests are excluded.

    Implement must land ``lru_cache.py`` at the workspace root when the prompt
    says so; renaming it to ``backend/app.py`` is not the named file.
    """
    mentioned: list[str] = []
    for raw in _PRODUCT_FILE_RE.findall(user_input or ""):
        name = raw.replace("\\", "/")
        base = Path(name).name
        if base.startswith("test_") or name.startswith("tests/"):
            continue
        if name not in mentioned:
            mentioned.append(name)
    return mentioned


def named_pytest_targets(user_input: str, *, on_disk: list[str]) -> list[str]:
    """Pytest only the test files the task named (P3), not extra tester files.

    Extra ``test_*.py`` (root or ``*_independent.py``) previously failed the
    mechanical gate and burned wall-clock on verify retries. P3 is unfiltered
    pytest on that named file (no ``-k`` skip of failing tests inside it).
    """
    disk = [p.replace("\\", "/") for p in on_disk]
    disk_set = set(disk)
    mentioned: list[str] = []
    for raw in _TEST_FILE_RE.findall(user_input or ""):
        name = raw.replace("\\", "/")
        if name in mentioned:
            continue
        mentioned.append(name)
    chosen: list[str] = []
    for name in mentioned:
        if name in disk_set:
            chosen.append(name)
            continue
        bare = Path(name).name
        under = f"tests/{bare}"
        if under in disk_set:
            chosen.append(under)
            continue
        # Keep the named path even if it is not on disk yet so extras
        # (test_simple.py) cannot become the mechanical pytest target.
        chosen.append(name)
    if chosen:
        return chosen
    return sorted(
        p
        for p in disk
        if p.startswith("tests/")
        and Path(p).name.startswith("test_")
        and p.endswith(".py")
    )


@dataclass
class VerifyContext:
    """Inputs for deterministic checks. No model objects."""

    workspace: Path
    stage_output: str = ""
    expected_output: str = ""
    diff: str = ""
    claimed_files: list[str] = field(default_factory=list)
    python_files: list[str] = field(default_factory=list)
    json_files: list[str] = field(default_factory=list)
    yaml_files: list[str] = field(default_factory=list)
    pytest_targets: list[str] = field(default_factory=list)
    forbidden_paths: tuple[str, ...] = _FORBIDDEN_DEFAULT
    goal_rules: list[str] = field(default_factory=list)


@dataclass
class MechanicalVerdict:
    passed: bool
    findings: list[str] = field(default_factory=list)
    subject: str = ""
    checks_run: list[str] = field(default_factory=list)


def subject_hash(stage_output: str, diff: str) -> str:
    """计算被审对象的哈希。

    审计通过的是"这一份具体的产出"。coder 改完之后旧的通过结论自动失效，
    防止"审计通过 → 又偷偷改了 → 直接进入下一阶段"。
    """
    return hashlib.sha256((stage_output + "\n---\n" + diff).encode()).hexdigest()


def _check_files_exist(ctx: VerifyContext) -> tuple[bool, str]:
    missing = [rel for rel in ctx.claimed_files if not (ctx.workspace / rel).exists()]
    if missing:
        return False, f"claimed files missing: {missing}"
    return True, ""


def _check_python_parses(ctx: VerifyContext) -> tuple[bool, str]:
    targets = ctx.python_files or [p for p in ctx.claimed_files if p.endswith(".py")]
    for rel in targets:
        path = ctx.workspace / rel
        if not path.is_file():
            return False, f"python file missing: {rel}"
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            return False, f"{rel} is not utf-8 text: {exc}"
        try:
            ast.parse(text, filename=rel)
        except SyntaxError as exc:
            return False, f"{rel} does not parse: {exc.msg}"
        if Path(rel).name.startswith("test_") and "def test_" not in text:
            return False, f"{rel} has no test_ functions"
    return True, ""


def _check_json_parses(ctx: VerifyContext) -> tuple[bool, str]:
    targets = ctx.json_files or [p for p in ctx.claimed_files if p.endswith(".json")]
    for rel in targets:
        path = ctx.workspace / rel
        if not path.is_file():
            return False, f"json file missing: {rel}"
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            return False, f"{rel} is not utf-8 text: {exc}"
        except json.JSONDecodeError as exc:
            return False, f"{rel} is not valid JSON: {exc.msg}"
    return True, ""


def _check_yaml_parses(ctx: VerifyContext) -> tuple[bool, str]:
    targets = ctx.yaml_files or [
        p for p in ctx.claimed_files if p.endswith((".yaml", ".yml"))
    ]
    for rel in targets:
        path = ctx.workspace / rel
        if not path.is_file():
            return False, f"yaml file missing: {rel}"
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            return False, f"{rel} is not utf-8 text: {exc}"
        except yaml.YAMLError as exc:
            return False, f"{rel} is not valid YAML: {exc}"
    return True, ""


def _check_ruff(ctx: VerifyContext) -> tuple[bool, str]:
    targets = ctx.python_files or [p for p in ctx.claimed_files if p.endswith(".py")]
    paths = [str(ctx.workspace / rel) for rel in targets if (ctx.workspace / rel).is_file()]
    if not paths:
        return True, ""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", *paths],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        # Hung ruff on Windows is an environment stall, not a lint finding.
        return True, ""
    if proc.returncode != 0:
        return False, (proc.stdout or proc.stderr or "ruff failed").strip()
    return True, ""


def _check_pytest(ctx: VerifyContext) -> tuple[bool, str]:
    targets = ctx.pytest_targets or [
        p for p in ctx.claimed_files if p.startswith("test") or "/test" in p
    ]
    paths = [str(ctx.workspace / rel) for rel in targets]
    if not paths:
        return False, "tests_pass requires pytest targets"
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                *paths,
                "-q",
                "--tb=no",
                "-p",
                "no:cacheprovider",
                "--override-ini=addopts=",
                f"--rootdir={ctx.workspace}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(ctx.workspace),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, "pytest timed out"
    if proc.returncode != 0:
        return False, (proc.stdout or proc.stderr or "pytest failed").strip()
    return True, ""


def _check_forbidden_paths(ctx: VerifyContext) -> tuple[bool, str]:
    blob = "\n".join([*ctx.claimed_files, ctx.diff, ctx.stage_output])
    hit = [name for name in ctx.forbidden_paths if name and name in blob]
    if hit:
        return False, f"touched forbidden paths: {hit}"
    return True, ""


def _check_diff_non_empty(ctx: VerifyContext) -> tuple[bool, str]:
    if not ctx.diff.strip():
        return False, "claimed complete but diff is empty"
    return True, ""


def _check_goal_satisfied(ctx: VerifyContext) -> tuple[bool, str]:
    """High-level goal check (MAST FC3).

    Explicit ``goal_rules`` stay substring checks. Template ``expected_output``
    is not matched verbatim (that stalled live teams on clarify/plan).
    """
    rules = [rule.strip() for rule in ctx.goal_rules if rule.strip()]
    if rules:
        missing = [rule for rule in rules if rule.lower() not in ctx.stage_output.lower()]
        if missing:
            return False, f"high-level goal not met: {missing}"
        return True, ""
    if (ctx.stage_output or "").strip():
        return True, ""
    return False, "goal_satisfied: empty stage output"


class MechanicalVerifier:
    CHECKS: dict[str, Callable[[VerifyContext], tuple[bool, str]]] = {
        "files_exist": _check_files_exist,
        "python_parses": _check_python_parses,
        "json_parses": _check_json_parses,
        "yaml_parses": _check_yaml_parses,
        "lint_clean": _check_ruff,
        "tests_pass": _check_pytest,
        "no_forbidden": _check_forbidden_paths,
        "diff_non_empty": _check_diff_non_empty,
        "goal_satisfied": _check_goal_satisfied,
    }

    def run(
        self,
        stage: SopStage,
        result: Any,
        ctx: VerifyContext | None = None,
    ) -> MechanicalVerdict:
        context = ctx or getattr(result, "verify_ctx", None)
        if context is None:
            context = VerifyContext(
                workspace=Path("."),
                stage_output=getattr(result, "answer", "") or "",
                expected_output=stage.expected_output,
                diff=getattr(result, "diff", "") or "",
            )
        if not context.stage_output:
            context.stage_output = getattr(result, "answer", "") or ""
        digest = subject_hash(context.stage_output, context.diff)
        findings: list[str] = []
        ran: list[str] = []
        for name in stage.verify_before_next:
            checker = self.CHECKS.get(name)
            ran.append(name)
            if checker is None:
                findings.append(f"unknown check {name!r}")
                continue
            ok, detail = checker(context)
            if not ok:
                findings.append(f"{name}: {detail}")
        return MechanicalVerdict(
            passed=not findings,
            findings=findings,
            subject=digest,
            checks_run=ran,
        )
