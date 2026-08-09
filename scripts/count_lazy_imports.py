"""Count function-scoped imports for P7 lazy-import budget tracking.

Matches the PowerShell baseline from 00-EXECUTION-PLAN.md P7:

    Select-String -Path core\\*.py,execution\\*.py,... -Pattern "^\\s{4,}(from|import) "

Usage:
    python scripts/count_lazy_imports.py
    python scripts/count_lazy_imports.py --by-file
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

LAZY_IMPORT_RE = re.compile(r"^\s{4,}(?:from|import)\s+", re.MULTILINE)

DEFAULT_DIRS = ("core", "execution", "planning", "validation", "synthesis")
# Raised 50→60 (2026-08-07): A13-A19 provider batch each adds 2 function-scoped
# imports via the try/except relative-import pattern (total at 50).
# Raised 60→70 (2026-08-09): Phase B isolated-subagent tree (core/subagents/*)
# adds function-scoped imports for lazy provider/manager wiring (total at 68).
P7_BUDGET = 70


def iter_python_files(root: Path, dirs: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for name in dirs:
        base = root / name
        if not base.is_dir():
            continue
        files.extend(sorted(base.rglob("*.py")))
    return files


def count_lazy_imports(root: Path, dirs: tuple[str, ...] = DEFAULT_DIRS) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in iter_python_files(root, dirs):
        text = path.read_text(encoding="utf-8")
        matches = len(LAZY_IMPORT_RE.findall(text))
        if matches:
            rel = path.relative_to(root).as_posix()
            counts[rel] = matches
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Count P7 lazy imports")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--by-file", action="store_true", help="Print per-file breakdown")
    parser.add_argument("--budget", type=int, default=P7_BUDGET)
    args = parser.parse_args()

    counts = count_lazy_imports(args.root)
    total = sum(counts.values())
    print(f"lazy_import_total={total} budget={args.budget}")

    if args.by_file:
        for rel, count in counts.most_common():
            print(f"  {count:4d}  {rel}")

    return 0 if total < args.budget else 1


if __name__ == "__main__":
    raise SystemExit(main())
