"""Task definition loading & validation for the evals harness.

Schema stitched from Terminal-Bench's task definition idea (task dir +
instruction + verification) flattened into one YAML file per task, and
SWE-bench's instance record (stable ``id`` + problem statement +
machine-checkable verification).

A task YAML looks like:

    id: bugfix-off-by-one
    category: bugfix            # readcode | bugfix | refactor | feature
    prompt: |                   # instruction handed to the agent
      ...
    setup:                      # optional fixture files for a temp workdir
      files:
        calc.py: |
          ...
    checks:                     # verification assertions
      - type: file_exists
        path: calc.py
      - type: file_contains
        path: calc.py
        pattern: "return total"
      - type: command_succeeds
        run: "python -m pytest {workdir}/test_calc.py -q"
      - type: output_contains   # asserts on the agent's final text answer
        pattern: "validator"

``readcode`` tasks usually have no ``setup`` (they ask about this repo);
``bugfix``/``refactor``/``feature`` tasks should define ``setup.files``
so they run in an isolated temp workdir and never touch this repo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

#: Task categories we support.
CATEGORIES = ("readcode", "bugfix", "refactor", "feature")

#: Check types the runner knows how to execute.
CHECK_TYPES = (
    "file_exists",
    "file_contains",
    "file_not_contains",
    "command_succeeds",
    "output_contains",
)

#: Checks that need a filesystem workdir to be meaningful.
_WORKDIR_CHECKS = ("file_exists", "file_contains", "file_not_contains", "command_succeeds")

TASKS_DIR = Path(__file__).parent / "tasks"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]*$")


class TaskSchemaError(ValueError):
    """Raised when a task YAML fails schema validation."""


@dataclass
class Check:
    """One verification assertion."""

    type: str
    path: Optional[str] = None
    pattern: Optional[str] = None
    run: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict, *, task_id: str) -> "Check":
        if not isinstance(data, dict):
            raise TaskSchemaError(f"task {task_id}: check must be a mapping, got {type(data).__name__}")
        ctype = data.get("type")
        if ctype not in CHECK_TYPES:
            raise TaskSchemaError(
                f"task {task_id}: unknown check type {ctype!r}; known: {list(CHECK_TYPES)}"
            )
        if ctype in ("file_exists", "file_contains", "file_not_contains"):
            if not data.get("path"):
                raise TaskSchemaError(f"task {task_id}: check {ctype} requires 'path'")
        if ctype in ("file_contains", "file_not_contains", "output_contains"):
            if not data.get("pattern"):
                raise TaskSchemaError(f"task {task_id}: check {ctype} requires 'pattern'")
        if ctype == "command_succeeds" and not data.get("run"):
            raise TaskSchemaError(f"task {task_id}: check command_succeeds requires 'run'")
        return cls(
            type=ctype,
            path=data.get("path"),
            pattern=data.get("pattern"),
            run=data.get("run"),
        )


@dataclass
class EvalTask:
    """A single evaluation task."""

    id: str
    category: str
    prompt: str
    setup_files: dict[str, str] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    source_path: Optional[Path] = None

    @property
    def needs_workdir(self) -> bool:
        """True when the task must run inside an isolated temp workdir."""
        if self.setup_files:
            return True
        return any(c.type in _WORKDIR_CHECKS for c in self.checks)

    @classmethod
    def from_dict(cls, data: dict, *, source_path: Optional[Path] = None) -> "EvalTask":
        where = source_path.name if source_path else "<dict>"
        if not isinstance(data, dict):
            raise TaskSchemaError(f"{where}: top level must be a mapping")

        task_id = data.get("id")
        if not task_id or not isinstance(task_id, str):
            raise TaskSchemaError(f"{where}: missing or invalid 'id'")
        if not _ID_RE.match(task_id):
            raise TaskSchemaError(
                f"{where}: id {task_id!r} must be lowercase alnum with - or _"
            )

        category = data.get("category")
        if category not in CATEGORIES:
            raise TaskSchemaError(
                f"{where}: category must be one of {list(CATEGORIES)}, got {category!r}"
            )

        prompt = data.get("prompt")
        if not prompt or not isinstance(prompt, str) or not prompt.strip():
            raise TaskSchemaError(f"{where}: missing or empty 'prompt'")

        setup = data.get("setup") or {}
        if not isinstance(setup, dict):
            raise TaskSchemaError(f"{where}: 'setup' must be a mapping")
        setup_files = setup.get("files") or {}
        if not isinstance(setup_files, dict):
            raise TaskSchemaError(f"{where}: 'setup.files' must be a mapping of path -> content")
        for rel, content in setup_files.items():
            if not isinstance(rel, str) or not rel:
                raise TaskSchemaError(f"{where}: setup file path must be a non-empty string")
            if Path(rel).is_absolute() or ".." in Path(rel).parts:
                raise TaskSchemaError(
                    f"{where}: setup file path {rel!r} must be relative and stay inside the workdir"
                )
            if not isinstance(content, str):
                raise TaskSchemaError(f"{where}: setup file {rel!r} content must be a string")

        raw_checks = data.get("checks") or []
        if not isinstance(raw_checks, list):
            raise TaskSchemaError(f"{where}: 'checks' must be a list")
        checks = [Check.from_dict(c, task_id=task_id) for c in raw_checks]
        if not checks:
            raise TaskSchemaError(f"{where}: at least one check is required")

        return cls(
            id=task_id,
            category=category,
            prompt=prompt.strip(),
            setup_files=dict(setup_files),
            checks=checks,
            source_path=source_path,
        )


def load_task(path: Path) -> EvalTask:
    """Load and validate one task YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return EvalTask.from_dict(data, source_path=path)


def load_tasks(
    tasks_dir: Optional[Path] = None,
    *,
    task_ids: Optional[list[str]] = None,
    category: Optional[str] = None,
) -> list[EvalTask]:
    """Load all task YAMLs from ``tasks_dir``, optionally filtered.

    Raises TaskSchemaError on the first invalid file; raises FileNotFoundError
    when a requested task id does not exist.
    """
    directory = Path(tasks_dir) if tasks_dir else TASKS_DIR
    if not directory.is_dir():
        raise FileNotFoundError(f"tasks dir not found: {directory}")

    tasks: list[EvalTask] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.yaml")):
        task = load_task(path)
        if task.id in seen:
            raise TaskSchemaError(f"duplicate task id {task.id!r} in {path.name}")
        seen.add(task.id)
        tasks.append(task)

    if task_ids:
        wanted = set(task_ids)
        missing = wanted - {t.id for t in tasks}
        if missing:
            raise FileNotFoundError(
                f"unknown task id(s): {sorted(missing)}; available: {sorted(seen)}"
            )
        tasks = [t for t in tasks if t.id in wanted]

    if category:
        if category not in CATEGORIES:
            raise TaskSchemaError(
                f"category must be one of {list(CATEGORIES)}, got {category!r}"
            )
        tasks = [t for t in tasks if t.category == category]

    return tasks
