#!/usr/bin/env python3
"""Static self-audit for RXYCode Web planning documents; no product tests implied."""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
CARD = re.compile(r"^### (WEB-W[0-7]-C\d{2})\b", re.M)
REF = re.compile(r"\[[^\]\n]+\]\(([^)]+)\)")
CASE = re.compile(r"^\| `(WEB-W[0-7]-C\d{2}-[UMN]|[A-Z][A-Z0-9-]+-\d{2})` \|", re.M)
INDEX_NAMES = ("README.md", "00-WEB-EXECUTION-PLAN.md")
AUTHORITY_ANCHOR = "活开发顺序"


def fail(msg: str, errors: list[str]) -> None:
    errors.append(msg)


def _refs(text: str) -> list[str]:
    found: list[str] = []
    for link in REF.findall(text):
        found.append(unquote(link.split("#", 1)[0]).replace("\\", "/").strip())
    for token in re.findall(r"`([^`\n]+)`", text):
        found.append(token.strip().replace("\\", "/"))
    cleaned: list[str] = []
    for item in found:
        if item.startswith("./"):
            item = item[2:]
        if item:
            cleaned.append(item)
    return cleaned


def _covers(ref: str, rel: str) -> bool:
    if not ref or "://" in ref or ref.startswith("mailto:"):
        return False
    if ref.startswith("./"):
        ref = ref[2:]
    if ref == rel:
        return True
    if any(ch in ref for ch in "*?["):
        # A directory glob must match the whole relative path. A bare filename
        # glob matches only that filename, never every file in the plan.
        if "/" in ref.replace("\\", "/"):
            return fnmatch.fnmatchcase(rel, ref)
        return fnmatch.fnmatchcase(Path(rel).name, Path(ref).name)
    return False


def scan_contract(plan_root: Path) -> dict:
    """Return card uniqueness and whether every plan file is linked from the index."""
    plan_root = Path(plan_root)
    cards: list[str] = []
    for doc in sorted((plan_root / "phases").glob("PHASE-W*.md")):
        cards.extend(CARD.findall(doc.read_text(encoding="utf-8")))
    counts = Counter(cards)
    refs: list[str] = []
    for name in INDEX_NAMES:
        refs.extend(_refs((plan_root / name).read_text(encoding="utf-8")))
    unindexed: list[str] = []
    for path in sorted(plan_root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(plan_root).as_posix()
        if Path(rel).name in INDEX_NAMES:
            continue
        if not any(_covers(ref, rel) for ref in refs):
            unindexed.append(rel)
    return {
        "card_count": len(counts),
        "duplicate_cards": sorted(card for card, n in counts.items() if n != 1),
        "unindexed_files": unindexed,
    }


def authority_status(dev_order: Path) -> str:
    """The old DEV-ORDER stays the authority. A missing file is not a new authority."""
    path = Path(dev_order)
    if not path.is_file():
        return "BLOCKED_PREREQUISITE"
    text = path.read_text(encoding="utf-8")
    if AUTHORITY_ANCHOR not in text:
        return "BLOCKED_PREREQUISITE"
    return "OK"


def _git_ignored(repo: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "--", relative],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def tracking_status(repo: Path) -> dict:
    """Web docs must be trackable. The plans archive, secrets, and the old tree stay ignored.

    ``docs/plans/opus5-plan`` is an embedded repository. The parent gitignore must
    not hide the Web plan, and that embedded repository must not ignore it either.
    """
    repo = Path(repo)
    web = "docs/plans/opus5-plan/rxycode -web/README.md"
    owning = repo / "docs" / "plans" / "opus5-plan"
    web_ignored = _git_ignored(repo, web)
    if (owning / ".git").exists():
        web_ignored = web_ignored or _git_ignored(owning, "rxycode -web/README.md")
    web_root = "docs/plans/opus5-plan/rxycode -web"
    secret_names = (
        ".env",
        "credentials.yaml",
        "history.rar",
        "token.key",
        "session.token",
        "config.local.yaml",
    )
    parent_secrets_ignored = all(_git_ignored(repo, f"{web_root}/{name}") for name in secret_names)
    nested_secrets_ignored = True
    if (owning / ".git").exists():
        nested_secrets_ignored = all(
            _git_ignored(owning, f"rxycode -web/{name}") for name in secret_names
        )
    return {
        "web_doc_ignored": web_ignored,
        "plans_archive_ignored": _git_ignored(repo, "docs/plans/opus5-plan.rar"),
        "secret_ignored": _git_ignored(repo, ".env"),
        "legacy_plan_tree_ignored": _git_ignored(
            repo, "docs/plans/opus5-plan/rxycode/architecture/DEV-ORDER.md"
        ),
        "web_local_env_ignored": _git_ignored(repo, f"{web_root}/.env"),
        "web_local_credentials_ignored": _git_ignored(repo, f"{web_root}/credentials.yaml"),
        "web_local_archive_ignored": _git_ignored(repo, f"{web_root}/history.rar"),
        "web_local_secrets_ignored": parent_secrets_ignored and nested_secrets_ignored,
    }


def version_conflict_scan(plan_root: Path, dev_order: Path) -> dict:
    """Compare the Web plan with the old DEV-ORDER authority. Missing authority is a conflict."""
    conflicts: list[str] = []
    plan_root = Path(plan_root)
    plan_text = (plan_root / "00-WEB-EXECUTION-PLAN.md").read_text(encoding="utf-8")
    if "DEV-ORDER.md" not in plan_text or "不是" not in plan_text.split("DEV-ORDER.md", 1)[0][-40:]:
        conflicts.append("web execution plan does not keep the old DEV-ORDER")
    order_path = Path(dev_order)
    if not order_path.is_file() or AUTHORITY_ANCHOR not in order_path.read_text(encoding="utf-8"):
        conflicts.append("DEV-ORDER missing 活开发顺序")
    report = scan_contract(plan_root)
    if report["duplicate_cards"]:
        conflicts.extend(f"duplicate {card}" for card in report["duplicate_cards"])
    return {"ok": not conflicts, "conflicts": conflicts}


_FROZEN_HEADING = "## WEB-W0-C02 frozen rows"
_KNOWN_LICENSES = {"APACHE-2.0", "MIT"}


def _frozen_rows(plan_root: Path) -> list[dict[str, str]]:
    text = (Path(plan_root) / "15-RESEARCH-VERDICTS.md").read_text(encoding="utf-8")
    rows: list[dict[str, str]] = []
    started = False
    for line in text.splitlines():
        if line.startswith(_FROZEN_HEADING):
            started = True
            continue
        if started and line.startswith("## "):
            break
        if not started or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 11 or cells[0] in {"id"} or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append(
            {
                "id": cells[0],
                "requirement": cells[1],
                "source_url": cells[2],
                "commit": cells[3],
                "license": cells[4],
                "decision": cells[5],
                "rejected": cells[6],
                "adr": cells[7],
                "version": cells[8],
                "why": cells[9],
                "threshold": cells[10],
            }
        )
    return rows


def lookup_verdict(plan_root: Path, verdict_id: str) -> dict[str, str]:
    """Return one frozen subsystem verdict from the Web research document."""
    for row in _frozen_rows(plan_root):
        if row["id"] == verdict_id:
            return row
    raise KeyError(verdict_id)


def trace_verdict(plan_root: Path, verdict_id: str) -> dict[str, str]:
    """Follow a verdict into its ADR and return the requirement, limit, and version."""
    row = lookup_verdict(plan_root, verdict_id)
    adr_text = (Path(plan_root) / row["adr"]).read_text(encoding="utf-8")
    if row["version"] not in adr_text or row["commit"] not in adr_text:
        raise ValueError(f"{row['adr']} does not pin {verdict_id}")
    limit = ""
    seen_id = False
    for line in adr_text.splitlines():
        stripped = line.strip()
        if stripped == f"- id: {verdict_id}":
            seen_id = True
            continue
        if seen_id and stripped.startswith("- id:"):
            break
        if seen_id and stripped.startswith("- limit:"):
            limit = stripped.split(":", 1)[1].strip()
            break
    if not limit:
        raise ValueError(f"{row['adr']} has no limit for {verdict_id}")
    return {
        "requirement": row["requirement"],
        "source_url": row["source_url"],
        "adr": row["adr"],
        "limit": limit,
        "version": row["version"],
        "why": row["why"],
        "threshold": row["threshold"],
    }


def reuse_decision(license_name: str, commit: str = "") -> dict[str, object]:
    """Copying needs both a known SPDX license and a pinned commit."""
    cleaned = (license_name or "").strip().upper()
    sha = (commit or "").strip().lower()
    sha_ok = len(sha) >= 12 and all(char in "0123456789abcdef" for char in sha)
    if cleaned in _KNOWN_LICENSES and sha_ok:
        return {"status": "LICENSED", "copy_allowed": True}
    return {"status": "RESEARCH_REQUIRED", "copy_allowed": False}


def baseline_file_status(path: Path) -> str:
    """A missing baseline test is BLOCKED. It is not a skipped pass."""
    if Path(path).is_file():
        return "PRESENT"
    return "BLOCKED"


_REQUIREMENT_HEADING = "## WEB-W0-C04 requirement rows"
_CONFLICT_HEADING = "## WEB-W0-C04 conflict rows"


def _table_after(text: str, heading: str) -> list[list[str]]:
    rows: list[list[str]] = []
    started = False
    for line in text.splitlines():
        if line.startswith(heading):
            started = True
            continue
        if started and line.startswith("## "):
            break
        if not started or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or cells[0] in {"id", "R"} or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append(cells)
    return rows


def trace_requirements(plan_root: Path) -> list[dict[str, object]]:
    """Read the seven-requirement table and whether each test id exists."""
    plan_root = Path(plan_root)
    text = (plan_root / "12-REQUIREMENTS-TRACEABILITY.md").read_text(encoding="utf-8")
    matrix = (plan_root / "tests" / "TEST-MATRIX.md").read_text(encoding="utf-8")
    traced: list[dict[str, object]] = []
    for cells in _table_after(text, _REQUIREMENT_HEADING):
        if len(cells) < 4:
            continue
        test_id = cells[3]
        traced.append(
            {
                "id": cells[0],
                "owner": cells[1],
                "card": cells[2],
                "test_id": test_id,
                "test_defined": f"`{test_id}`" in matrix,
            }
        )
    return traced


def load_conflicts(plan_root: Path) -> list[dict[str, str]]:
    """Read the C04 conflict rows. OPEN P0 items keep W1 shut."""
    text = (Path(plan_root) / "13-CONFLICT-AUDIT.md").read_text(encoding="utf-8")
    conflicts: list[dict[str, str]] = []
    for cells in _table_after(text, _CONFLICT_HEADING):
        if len(cells) < 5:
            continue
        conflicts.append(
            {
                "id": cells[0],
                "severity": cells[1],
                "status": cells[2],
                "command": cells[3],
                "ruling": cells[4],
            }
        )
    return conflicts


_RESOLVED_CONFLICT = {"RESOLVED", "FALSE_POSITIVE"}


def w1_gate(conflicts: list[dict[str, str]]) -> str:
    """Any P0 that is not resolved or a false positive rejects W1."""
    for item in conflicts:
        if item.get("severity") != "P0":
            continue
        if item.get("status") not in _RESOLVED_CONFLICT:
            return "REJECTED"
    return "ALLOWED"


def old_protocol_methods(repo: Path) -> set[str]:
    """Method names already declared on the old JSON-RPC models."""
    found: set[str] = set()
    for path in (Path(repo) / "protocol").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found.update(re.findall(r'method:\s*Literal\["([^"]+)"\]', text))
    return found


def protocol_name_ruling(repo: Path, plan_root: Path, command: str) -> dict[str, str]:
    """A new web command that reuses an old method stays blocked."""
    old_methods = old_protocol_methods(repo)
    match = next(
        (item for item in load_conflicts(plan_root) if item["command"] == command),
        None,
    )
    if match is not None:
        return {
            "command": command,
            "old_method": command if command in old_methods else "",
            "ruling": match["ruling"],
            "conflict_id": match["id"],
        }
    if command in old_methods:
        return {
            "command": command,
            "old_method": command,
            "ruling": "BLOCKED",
            "conflict_id": "",
        }
    return {
        "command": command,
        "old_method": "",
        "ruling": "CLEAR",
        "conflict_id": "",
    }


def main() -> int:
    errors: list[str] = []
    docs = sorted(ROOT.rglob("*.md"))
    cards: list[str] = []
    all_cases: list[str] = []
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        if not text.strip():
            fail(f"empty file {doc.relative_to(ROOT)}", errors)
        if "schema diff+TypeScript+\n" in text:
            fail(f"broken migration table {doc.relative_to(ROOT)}", errors)
        lines = text.splitlines()
        for idx, line in enumerate(lines[:-2]):
            if line.startswith("|---") and not lines[idx + 1].strip() and lines[idx + 2].startswith("|"):
                fail(f"invalid Markdown table {doc.relative_to(ROOT)}:{idx + 1}", errors)
        for link in REF.findall(text):
            link = unquote(link.split("#", 1)[0])
            if not link or link.startswith(("http://", "https://", "mailto:", "data:")):
                continue
            if not (doc.parent / link).exists():
                fail(f"broken link {doc.relative_to(ROOT)} => {link}", errors)
        if doc.parent.name == "phases":
            cards.extend(CARD.findall(text))
        if doc.name == "TEST-MATRIX.md":
            all_cases.extend(CASE.findall(text))
    counts = Counter(cards)
    if len(cards) != 48 or len(counts) != 48:
        fail(f"expected 48 unique task cards; found total={len(cards)}, unique={len(counts)}", errors)
    if any(n != 1 for n in counts.values()):
        fail(f"duplicate task cards {[(k, v) for k, v in counts.items() if v != 1]}", errors)
    for wave, expected in {0: 4, 1: 5, 2: 7, 3: 7, 4: 7, 5: 6, 6: 6, 7: 6}.items():
        actual = sum(card.startswith(f"WEB-W{wave}-") for card in cards)
        if actual != expected:
            fail(f"W{wave}: expected {expected} cards, found {actual}", errors)
    case_counts = Counter(all_cases)
    if len(all_cases) != 173 or len(case_counts) != 173:
        fail(f"expected 173 unique test specifications; found total={len(all_cases)}, unique={len(case_counts)}", errors)
    for card in counts:
        for suffix in ("U", "M", "N"):
            if f"{card}-{suffix}" not in case_counts:
                fail(f"test coverage missing {card}-{suffix}", errors)
    print(f"AUDIT docs={len(docs)} cards={len(cards)} tests={len(all_cases)} errors={len(errors)}")
    for msg in errors:
        print("FAIL", msg)
    if not errors:
        print("PASS static documentation check; NOT a claim of product implementation or runtime tests")
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
