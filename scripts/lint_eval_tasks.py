"""静态体检所有 eval 任务 YAML。

抓两类真实存在过的 bug：
  1. ``python -c "..."`` 检查里的代码根本不是合法 Python
  2. 任务在空临时目录里运行，却用 file_exists 检查仓库内的路径
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

TASKS_DIR = Path(__file__).resolve().parents[1] / "evals" / "tasks"
REPO_ROOT = Path(__file__).resolve().parents[1]


def extract_python_snippet(run: str) -> str | None:
    """从 ``python -c "<code>"`` 形式的命令里取出内层代码。"""
    for marker in ('python -c "', "python -c '"):
        if marker in run:
            quote = marker[-1]
            return run.split(marker, 1)[1].rsplit(quote, 1)[0]
    return None


def main() -> int:
    problems: list[str] = []

    for path in sorted(TASKS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        checks = data.get("checks") or []
        setup = data.get("setup") or {}
        has_setup_files = bool(setup.get("files")) or bool(data.get("setup_files"))

        for i, check in enumerate(checks):
            ctype = check.get("type")

            if ctype == "command_succeeds":
                snippet = extract_python_snippet(check.get("run", ""))
                if snippet is None:
                    continue
                try:
                    ast.parse(snippet)
                except SyntaxError as exc:
                    problems.append(
                        f"{path.name} check[{i}]: python snippet is not valid "
                        f"Python ({exc.msg})"
                    )

            if ctype in ("file_exists", "file_contains", "file_not_contains"):
                rel = check.get("path", "")
                if not has_setup_files and (REPO_ROOT / rel).exists():
                    problems.append(
                        f"{path.name} check[{i}]: path {rel!r} exists in the repo "
                        f"but the task runs in an empty tempdir — this check can "
                        f"never pass"
                    )

    for p in problems:
        print("FAIL:", p)
    print(
        f"\n{len(problems)} problem(s) across "
        f"{len(list(TASKS_DIR.glob('*.yaml')))} task file(s)"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
