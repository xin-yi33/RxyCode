"""GX18 rule-based follow-up scanner. Zero LLM. Max 3, deduped per turn."""

from __future__ import annotations

from pathlib import Path


class FollowupScanner:
    def __init__(self) -> None:
        self._emitted: set[str] = set()

    def scan(self, workspace: Path, *, turn_id: str) -> list[dict[str, str]]:
        key = str(turn_id)
        if key in self._emitted:
            return []
        suggestions: list[dict[str, str]] = []
        root = Path(workspace)
        if root.is_dir():
            py_files = [p for p in root.rglob("*.py") if p.is_file() and "test" not in p.name.lower()]
            tests = [p for p in root.rglob("test_*.py") if p.is_file()]
            if py_files and not tests:
                suggestions.append({"rule": "missing_tests", "text": "Add tests for untested Python files"})
            todos: list[str] = []
            for path in list(root.rglob("*"))[:80]:
                if not path.is_file() or path.suffix not in {".py", ".md", ".ts", ".tsx"}:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if "TODO" in text or "FIXME" in text:
                    todos.append(str(path.relative_to(root)))
                if len(todos) >= 5:
                    break
            if todos:
                suggestions.append({"rule": "leftover_todo", "text": f"Resolve leftover TODO markers in {todos[0]}"})
            git_dir = root / ".git"
            if git_dir.exists():
                try:
                    import subprocess

                    result = subprocess.run(
                        ["git", "status", "--porcelain"],
                        cwd=str(root),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                    if result.stdout.strip():
                        suggestions.append({"rule": "uncommitted", "text": "Commit leftover workspace changes"})
                except OSError:
                    pass
        seen_rules: set[str] = set()
        out: list[dict[str, str]] = []
        for item in suggestions:
            if item["rule"] in seen_rules:
                continue
            seen_rules.add(item["rule"])
            out.append(item)
            if len(out) >= 3:
                break
        self._emitted.add(key)
        return out
