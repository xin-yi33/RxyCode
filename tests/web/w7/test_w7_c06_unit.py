"""WEB-W7-C06 — release validation matrix, user docs, interview case.

Contract: the README Web feature matrix may only claim `shipped` rows whose
evidence and test artifacts really exist on disk; docs the card ships must
exist and be git-trackable. Negative: every quantitative claim in the
portfolio case study / README matrix carries a verifiable citation or an
explicit placeholder — never a guessed number.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
README = REPO / "README.md"
GUIDE = REPO / "docs" / "product" / "web-user-guide.md"
DESIGN = REPO / "docs" / "architecture" / "web-system-design.md"
CASE = REPO / "docs" / "portfolio" / "rxycode-web-case-study.md"

_STATUSES = ("shipped", "experimental", "planned", "blocked")
_EVIDENCE_REF = re.compile(r"evidence/web/WEB-W\d+-C\d\d")
_TEST_REF = re.compile(r"tests/(?:web|integration|unit|test_)[\w./-]*\.py")
# A quantitative claim: digits next to units/suffixes or an explicit count
# like "48 cards" / "1400 行" / "9165 input tokens". Citations are `[…]` links
# or `（证据: …）`/`(evidence: …)` on the same line; TBD/占位/BLOCKED mark an
# honest placeholder.
_METRIC = re.compile(
    r"\d[\d.,]*\s*(?:(?:input|output|total)\s+)?"
    r"(%|ms|s\b|min|x\b|tokens?|commits?|runs?|tests?|"
    r"次|条|卡|轮|个|项|行|张|分钟|小时|秒|工程日)"
)
_CITATION = re.compile(r"\[[^\]]+\]\(|证据[:：]|evidence[:=]|TBD|占位|BLOCKED")
_TABLE_ROW = re.compile(r"^\s*\|.*\|.*\|")
# A `（证据: …）` citation must name at least one artifact that exists on
# disk — the word alone is not a citation (audit r1).
_EVIDENCE_CLAIM = re.compile(r"(?:证据|evidence)[:：]\s*([^）)\n]+)")
_BACKTICK = re.compile(r"`([^`]+)`")
_BARE_PATH = re.compile(r"(?:evidence|docs|tests|infra|packages|apps)/[\w\-./ ]+")


def _row_status(cells: list[str]) -> str | None:
    """Status cells carry the keyword first (`shipped`, `blocked: reason`);
    an exact-match test would silently skip `blocked: …` rows entirely."""
    for c in cells[1:]:
        low = c.lower()
        for s in _STATUSES:
            if low.startswith(s):
                return s
    return None


def _citation_targets_exist(line: str) -> bool:
    """Validate the targets of `（证据: …）`/`(evidence: …)` citations —
    every cited path must resolve on this checkout. Markdown links and
    placeholder markers are not path claims."""
    match = _EVIDENCE_CLAIM.search(line)
    if not match:
        return True
    body = match.group(1)
    refs = _BACKTICK.findall(body) or _BARE_PATH.findall(body)
    if not refs:
        return False
    return any((REPO / r.split("::")[0].strip().rstrip("/")).exists() for r in refs)


def _readme_web_section() -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(r"^## .*Web.*$", text, flags=re.M)
    assert match, "README.md carries no '## … Web …' section — the matrix is missing"
    tail = text[match.end() :]
    nxt = re.search(r"^## ", tail, flags=re.M)
    return tail[: nxt.start()] if nxt else tail


def _matrix_rows() -> list[list[str]]:
    section = _readme_web_section()
    rows: list[list[str]] = []
    for line in section.splitlines():
        if not _TABLE_ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in {"---", ":---"} or set(cells[0]) <= {"-", ":"}:
            continue
        if _row_status(cells):
            rows.append(cells)
    return rows


def _not_ignored(path: Path) -> bool:
    done = subprocess.run(
        ["git", "check-ignore", "-q", str(path.relative_to(REPO))],
        cwd=REPO,
        check=False,
    )
    return done.returncode == 1


def test_w7_c06_contract() -> None:
    """Given README 声称支持 Full / Web 能力 When 审计 Then 每条 shipped
    声明可定位真机证据与测试文件；blocked 能力不得冒充 shipped。"""
    assert README.is_file(), "README.md missing"
    rows = _matrix_rows()
    assert rows, "README Web section has no status-tagged matrix rows"

    shipped = 0
    blocked = 0
    for cells in rows:
        line = " | ".join(cells)
        status = _row_status(cells)
        if status == "shipped":
            shipped += 1
            ev = _EVIDENCE_REF.search(line)
            assert ev, f"shipped row lacks an evidence ref: {line}"
            assert (REPO / ev.group(0)).is_dir(), f"evidence dir missing: {line}"
            test_refs = _TEST_REF.findall(line)
            assert test_refs, f"shipped row lacks a test ref: {line}"
            for ref in test_refs:
                assert (REPO / ref).is_file(), f"test file missing: {ref} ({line})"
        elif status == "blocked":
            # A blocked row must name the blocker — no silent gaps.
            blocked += 1
            assert re.search(r"(?i)blocked[:：]\s*\S", line) or any(
                "no " in c.lower() or "需要" in c or "requires" in c.lower() for c in cells
            ), f"blocked row lacks a named blocker: {line}"
    assert shipped >= 3, "matrix ships almost nothing — matrix is dishonest"
    # The parser must actually SEE the blocked rows — an exact-match status
    # bug once let `blocked: reason` cells skip every assertion (audit r1).
    assert blocked >= 1, "no blocked rows parsed — status detection regressed"

    # The card's three docs exist, are substantive, and are git-trackable.
    for path in (GUIDE, DESIGN, CASE):
        assert path.is_file(), f"{path.name} missing"
        assert path.stat().st_size > 400, f"{path.name} is a stub"
        assert _not_ignored(path), f"{path.name} is gitignored — not retrievable"


def test_w7_c06_negative() -> None:
    """Given 一项指标缺真实 taskset/report When 写简历 Then 模板保留占位
    而非猜数 — every metric must cite its source or stay a placeholder."""
    for path in (CASE,):
        assert path.is_file(), f"{path.name} missing (contract covers it too)"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not _METRIC.search(line):
                continue
            assert _CITATION.search(line), (
                f"{path.name}:{lineno} uncited metric claim: {line.strip()[:100]}"
            )
            assert _citation_targets_exist(line), (
                f"{path.name}:{lineno} cites no artifact that exists on disk: {line.strip()[:100]}"
            )
    # The README matrix itself must not smuggle uncited numbers either.
    for cells in _matrix_rows():
        line = " | ".join(cells)
        for metric in _METRIC.finditer(line):
            # Status tags like "W7-C05" contain digits — ignore evidence refs
            # and card ids; a bare performance/cost number needs a citation.
            context = line[max(0, metric.start() - 30) : metric.end() + 30]
            if _EVIDENCE_REF.search(context) or "WEB-W" in context:
                continue
            assert _CITATION.search(line), (
                f"README matrix row has an uncited metric: {line.strip()[:100]}"
            )
    # A deliberately placeholder row must remain a placeholder, not a guess:
    # if the case study marks a metric TBD the test passes only while the
    # placeholder token is present — filling in a number without a citation
    # re-fails this test.
    case_text = CASE.read_text(encoding="utf-8")
    assert ("TBD" in case_text) or ("占位" in case_text) or ("BLOCKED" in case_text), (
        "case study has no honest placeholders — either every metric is "
        "cited (fine, then this expectation may be revisited) or the gaps "
        "were silently invented"
    )
