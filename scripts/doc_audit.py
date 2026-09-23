"""Mechanical consistency checks for the development documents.

The phase docs under docs/plans/opus5-plan/rxycode/ are ~35k lines and are the
instructions a developer executes card by card.  Reading them end to end does
not converge: every pass finds different things and the findings are not
comparable between passes.  This turns the checkable part into a gate that
produces the same verdict twice in a row, so "iterate until shippable" has a
definition.

Only mechanically decidable properties are checked.  Whether a design is good
is not in scope; whether a doc tells you to edit a file that does not exist is.

Checks, each grounded in a defect that actually shipped in these docs:

  C1  file paths mentioned in prose exist, or are marked as new
      (X3: PHASE-G routes cards pointed at appserver/handlers/, which the
       repo has never had - the real convention is appserver/*_routes.py)
  C2  cross-document links and anchors resolve
  C4  card ids are unique
      (the audit found 11 numbering errors and 8 name collisions)
  C6  cards marked complete carry a verification command, not just a SHA
      (PHASE-E recorded seven commit SHAs; all seven stopped resolving after
       a history squash, while the deliverables themselves were fine)

Usage:
    python scripts/doc_audit.py            # human-readable report
    python scripts/doc_audit.py --json     # machine-readable
    python scripts/doc_audit.py --check C1 # one check only
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs" / "plans" / "opus5-plan" / "rxycode"
ARCH_DOCS = REPO / "docs" / "plans" / "opus5-plan" / "rxycode" / "architecture"

#: Extensions worth resolving against the working tree.  Prose in these docs
#: mentions plenty of things that look path-ish (module names, URLs, protocol
#: methods); restricting to real source extensions keeps the false positives
#: down to a level where the report is actually read.
SOURCE_SUFFIXES = (
    ".py", ".ts", ".tsx", ".mts", ".json", ".ps1", ".sh", ".toml",
    ".yml", ".yaml", ".cfg", ".ini", ".md",
)

#: A path preceded/followed by any of these is a planned artifact, not a claim
#: about the current tree.
NEW_MARKERS = (
    "新增", "新建", "待建", "将创建", "创建", "产出", "生成",
    "new file", "to be created", "不建", "禁止新建", "未创建", "不得新建",
    # Bare 建 as an imperative ("建 `evals/baselines/...`").  Anchored on the
    # backtick so it cannot match 建议 / 建立关系 / 重建索引 in prose.
    "建 `",
)

#: Phrases that make a path a citation for something already observed.
EVIDENCE_MARKERS = (
    "实测", "复现", "已验证", "零失败", "的做法", "产出", "输出", "日志",
    "见 §", "证据", "跑完", "跑了", "跑过", "分开跑", "结论",
)

PATH_IN_CODE = re.compile(r"`([^`\n]+)`")
MD_LINK = re.compile(r"\[([^\]]*)\]\((\.[^)\s]+|[A-Za-z0-9_.-]+\.md[^)\s]*)\)")
HEADING = re.compile(r"^(#{2,6})\s+(.*)$")
#: Card ids as they appear in headings: F18b, GX28, K5, M0a, PhaseG-B3, X11, D1
#: A card heading is "### <ID> · <title>".  The separator is load-bearing:
#: without it "#### L1 的处理" reads as card L1, and "D5.5" truncates to a
#: bogus second D5.  Sub-numbering is part of the id, not a delimiter.
CARD_ID = re.compile(
    r"^(?:~~)?\*{0,2}((?:Phase[A-Z]-)?[A-Z]{1,7}\d{1,3}(?:\.\d+)?[a-z]?)\s*[·・]"
)
#: CJK replaced by literal "?" - the signature of a write that went through a
#: non-UTF-8 encoder.  Unlike mojibake there is no U+FFFD to search for and
#: the file still parses as valid UTF-8, so nothing else notices.
LOSSY = re.compile(r"\?{2,}|[\u4e00-\u9fff]\s?\?\s?[\u4e00-\u9fff]")
DONE_MARK = re.compile(r"^\s*[-*]?\s*\[x\]", re.IGNORECASE)
SHA_ONLY = re.compile(r"\b[0-9a-f]{7,40}\b")
#: What counts as "you can check this yourself".  A SHA does not: seven of
#: PHASE-E's stopped resolving after a squash, and three more were found dead
#: on 08-18.  A command against the present tree survives history rewrites.
VERIFY_HINT = re.compile(
    r"python -m pytest|npx tsc|npx vitest|pytest |python scripts/|git grep"
    r"|Test-Path|Get-ChildItem|Select-String"
    r"|git (?:cat-file|ls-files|check-ignore|log|status|diff)"
)


ACCEPT_FILE = Path(__file__).with_name("doc_audit_accept.txt")


def _load_accepted() -> list[tuple[str, str]]:
    """Findings someone looked at and chose to live with.

    A silenced finding and an undiscovered one look identical in a report,
    which is how accepted risk quietly turns into forgotten risk.  So the
    entries live in a reviewable file, keep their reason, and are still
    printed - just as notes, and counted on their own line.
    """
    if not ACCEPT_FILE.exists():
        return []
    out: list[tuple[str, str]] = []
    for line in ACCEPT_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        check, _, needle = line.partition(" ")
        if needle.strip():
            out.append((check.strip(), needle.strip()))
    return out


@dataclass
class Finding:
    check: str
    severity: str          # "blocker" | "warn" | "note"
    doc: str
    line: int
    message: str
    context: str = ""


@dataclass
class Doc:
    path: Path
    lines: list[str]
    anchors: set[str] = field(default_factory=set)

    @property
    def name(self) -> str:
        return self.path.name


def slugify(heading: str) -> str:
    """GitHub-flavoured anchor slug (close enough for link checking)."""
    text = re.sub(r"`|\*|~~|<[^>]+>", "", heading).strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", text)
    return re.sub(r"\s+", "-", text).strip("-")


def load_docs() -> list[Doc]:
    docs = []
    roots = [DOCS]
    if ARCH_DOCS.is_dir():
        roots.append(ARCH_DOCS)
    for root in roots:
        for path in sorted(root.glob("*.md")):
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            doc = Doc(path=path, lines=lines)
            for raw in lines:
                m = HEADING.match(raw)
                if m:
                    doc.anchors.add(slugify(m.group(2)))
            docs.append(doc)
    return docs


def _looks_like_path(token: str) -> bool:
    token = token.strip()
    if not token or " " in token or token.startswith(("http", "#", "$", "-")):
        return False
    if not token.endswith(SOURCE_SUFFIXES):
        return False
    # Protocol methods (team/list) and globs are not filesystem claims.
    if any(ch in token for ch in "*?<>|"):
        return False
    # Shorthand like `config/model_catalog.py/.json/.schema.json` means three
    # sibling files, not one nested path.  A dot-leading segment anywhere but
    # the first is the tell (.github/... is a real first segment).
    segments = token.replace("\\", "/").split("/")
    if any(seg.startswith(".") and seg != ".." for seg in segments[1:]):
        return False
    return "/" in token or "\\" in token


def _resolves(doc: Doc, token: str) -> bool:
    """Try every base a human would reasonably have meant.

    ``../linkagent/README.md`` in a doc under docs/plans/opus5-plan/rxycode/
    is relative to that directory, not to the repo root - resolving only
    against the root reported every sibling-plan reference as missing.
    """
    raw = token.replace("\\", "/")
    # doc.parent.parent covers "rxycode/README.md" written from inside
    # rxycode/ - a reference relative to the plans directory, which is how
    # these docs address their siblings.
    for base in (doc.path.parent, doc.path.parent.parent, DOCS, REPO):
        try:
            if (base / raw).resolve().exists():
                return True
        except (OSError, ValueError):
            pass
    stripped = raw.lstrip("./")
    return (REPO / stripped).exists() or (DOCS / stripped).exists()


ACCEPTANCE_HEADING = re.compile(r"验收命令|验收步骤|验收|acceptance|复现命令|执行命令")
FENCE = re.compile(r"^\s*```")


def _acceptance_lines(doc: Doc) -> set[int]:
    """1-based line numbers inside a fenced block under an acceptance heading.

    Commands there are meant to be run as-is today, so a path they name is a
    claim about the current tree, not a plan.
    """
    inside_fence = False
    armed = False
    hits: set[int] = set()
    for i, raw in enumerate(doc.lines, 1):
        if FENCE.match(raw):
            inside_fence = not inside_fence
            continue
        if not inside_fence:
            if raw.strip():
                armed = bool(ACCEPTANCE_HEADING.search(raw))
        elif armed:
            hits.add(i)
    return hits


def _completed_lines(doc: Doc, window: int = 6) -> set[int]:
    """Lines within *window* after a completed checkbox.

    A card that claims to be done cannot also be waiting for its own files.
    """
    hits: set[int] = set()
    for i, raw in enumerate(doc.lines, 1):
        if DONE_MARK.match(raw):
            hits.update(range(i, min(i + window, len(doc.lines)) + 1))
    return hits


DELIVERABLE_HEADING = re.compile(r"涉及文件|交付物|产出物|deliverable")
CLAIM_VERB = re.compile(r"新建|新增|创建|产出|生成|new file")


#: "1. `core/agents/runtime.py`：" - a card's operation step naming the file
#: it is about to write.  This is the dominant shape in PHASE-F/H and has no
#: creation verb anywhere on the line.
STEP_SUBJECT = re.compile(r"^\s*\d+\.\s*\*{0,2}`([^`]+)`")
#: A directory line inside a tree block: "config/" or "core/agents/"
TREE_DIR = re.compile(r"^(\s*)([\w.-][\w./-]*/)\s*(?:#.*)?$")
#: A file line inside a tree block: "  model_pricing.py   # H4 定价表"
TREE_FILE = re.compile(r"^(\s+)([\w.-]+\.[\w]+)\s*(?:#.*)?$")


def _tree_declared(doc: Doc) -> dict[str, int]:
    """Paths spelled out as an indented directory tree in a fenced block.

    PHASE-H declares its deliverables as::

        config/
          model_pricing.py           # H4 定价表

    The filename alone never looks like a path, so scanning line by line
    misses it entirely and the file reads as unowned - which is how a file
    with a named owner ended up reported as an orphan dependency.
    """
    found: dict[str, int] = {}
    inside = False
    stack: list[tuple[int, str]] = []
    for i, line in enumerate(doc.lines, 1):
        if FENCE.match(line):
            inside = not inside
            stack.clear()
            continue
        if not inside:
            continue
        mdir = TREE_DIR.match(line)
        if mdir:
            indent = len(mdir.group(1))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1] if stack else ""
            stack.append((indent, parent + mdir.group(2)))
            continue
        mfile = TREE_FILE.match(line)
        if mfile and stack:
            indent = len(mfile.group(1))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if stack:
                found.setdefault(stack[-1][1] + mfile.group(2), i)
    return found


def _declared_deliverables(docs: list[Doc], window: int = 12) -> dict[str, str]:
    """path -> "DOC:line" for paths some card promises to create.

    Four shapes count, because all four are in active use: a "涉及文件" block,
    a creation verb on the line, a numbered operation step whose subject is
    the file, and an indented directory tree.  Insisting on one canonical
    spelling would not make the docs tidier, it would just make this check
    report owned files as orphans.
    """
    claimed: dict[str, str] = {}
    for doc in docs:
        for path, line_no in _tree_declared(doc).items():
            claimed.setdefault(path, f"{doc.name}:{line_no}")
        in_block = 0
        for i, line in enumerate(doc.lines, 1):
            # No `continue` here: PHASE-G-BACKEND writes the list inline as
            # "**涉及文件**：`a`、`b`、`c`", so skipping the heading line threw
            # away the very paths it was announcing.
            if DELIVERABLE_HEADING.search(line):
                in_block = window
            if in_block and not line.strip():
                in_block -= 1
            step = STEP_SUBJECT.match(line)
            if step and _looks_like_path(step.group(1)):
                claimed.setdefault(step.group(1), f"{doc.name}:{i}")
            claims = bool(in_block) or bool(CLAIM_VERB.search(line))
            if not claims:
                continue
            for token in PATH_IN_CODE.findall(line):
                if _looks_like_path(token):
                    claimed.setdefault(token, f"{doc.name}:{i}")
            if in_block:
                in_block -= 1
    return claimed


def check_c1_paths(docs: list[Doc]) -> list[Finding]:
    # Pass 1: gather every unresolved path with the context it appeared in.
    raw_hits: list[tuple[Doc, int, str, bool, bool, bool]] = []
    for doc in docs:
        acceptance = _acceptance_lines(doc)
        completed = _completed_lines(doc)
        for i, line in enumerate(doc.lines, 1):
            marked_new = any(mark in line for mark in NEW_MARKERS)
            # "- [x] 无 `core/cache_family.py`" asserts the file's *absence* as
            # the success condition.  Read as an ordinary reference it looks
            # like a completed card pointing at a missing file - the exact
            # opposite of what it says.
            asserts_absent = {m for m in NEG_PATH.findall(line)}
            for token in PATH_IN_CODE.findall(line):
                if token in asserts_absent:
                    continue
                if not _looks_like_path(token) or _resolves(doc, token):
                    continue
                raw_hits.append(
                    (doc, i, token, marked_new, i in acceptance, i in completed)
                )

    # A path named by several documents is shared context others depend on,
    # not one card's deliverable - much likelier to be a stale reference.
    spread: dict[str, set[str]] = defaultdict(set)
    for doc, _i, token, _new, _acc, _done in raw_hits:
        spread[token].add(doc.name)

    # ...unless some card has claimed it.  A file six documents depend on is
    # fine while it is unbuilt IF one card is on the hook for building it;
    # what is not fine is six dependants and no owner, which is how X1 and X6
    # slipped through - everyone assumed someone else's phase delivered it.
    owned = _declared_deliverables(docs)

    out: list[Finding] = []
    for doc, i, token, marked_new, in_acceptance, in_completed in raw_hits:
        docs_n = len(spread[token])
        if in_acceptance:
            sev, why = "blocker", "named by an acceptance command (meant to run today)"
        elif in_completed:
            sev, why = "blocker", "inside a card marked complete"
        elif token in owned:
            sev, why = "note", f"unbuilt, but claimed by {owned[token]}"
        elif docs_n >= 3:
            sev, why = "blocker", (f"{docs_n} documents depend on it and NO card "
                                   f"claims to create it")
        elif marked_new:
            # Checked before the evidence test on purpose: "建 X ... 不是实测值"
            # says plainly that X is to be created, and the incidental 实测
            # three clauses later must not outvote it.
            sev, why = "note", "marked as a new artifact"
        elif any(m in doc.lines[i - 1] for m in EVIDENCE_MARKERS):
            # Cited as the evidence behind a finding that already happened,
            # not as something a card will build.  A single mention normally
            # reads as a future deliverable, which is how five deleted X11
            # bisect scripts kept propping up conclusions nobody could rerun.
            sev, why = "warn", ("cited as evidence for a past result, but the "
                                "file is gone - that result cannot be rechecked")
        elif docs_n == 2:
            sev, why = "warn", "2 documents depend on it, no card claims it"
        else:
            sev, why = "note", "single mention, presumed future deliverable"
        out.append(Finding(
            check="C1", severity=sev, doc=doc.name, line=i,
            message=f"path does not exist: {token}  [{why}]",
            context=doc.lines[i - 1].strip()[:160],
        ))
    return out


def check_c2_links(docs: list[Doc]) -> list[Finding]:
    by_name = {d.name: d for d in docs}
    out: list[Finding] = []
    for doc in docs:
        for i, raw in enumerate(doc.lines, 1):
            for _text, target in MD_LINK.findall(raw):
                path_part, _, anchor = target.partition("#")
                path_part = path_part.strip()
                if path_part:
                    target_doc = by_name.get(Path(path_part).name)
                    if target_doc is None and not _resolves(doc, path_part):
                        out.append(Finding(
                            check="C2", severity="blocker", doc=doc.name, line=i,
                            message=f"link target missing: {target}",
                            context=raw.strip()[:160],
                        ))
                        continue
                else:
                    target_doc = doc
                if anchor and target_doc is not None:
                    if anchor.lower() not in target_doc.anchors:
                        out.append(Finding(
                            check="C2", severity="warn", doc=doc.name, line=i,
                            message=(f"anchor not found in {target_doc.name}: "
                                     f"#{anchor}"),
                            context=raw.strip()[:160],
                        ))
    return out


def iter_cards(doc: Doc):
    """Card declarations in a document, skipping fenced examples.

    A card heading quoted inside a code fence is an illustration - the X17
    write-up quotes PhaseG-H13's broken dependency line - and counting it as
    a declaration invents both a duplicate id and a phantom dependency.
    """
    fenced = False
    for i, raw in enumerate(doc.lines, 1):
        if FENCE.match(raw.strip()):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = HEADING.match(raw)
        if not m:
            continue
        title = m.group(2).strip()
        cid = CARD_ID.match(title)
        if cid:
            yield i, cid.group(1), title


def check_c4_card_ids(docs: list[Doc]) -> list[Finding]:
    seen: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for doc in docs:
        for i, cid, title in iter_cards(doc):
            seen[cid].append((doc.name, i, title[:90]))
    out: list[Finding] = []
    for cid, places in sorted(seen.items()):
        if len(places) < 2:
            continue
        docs_involved = {p[0] for p in places}
        where = "; ".join(f"{d}:{ln}" for d, ln, _ in places)
        out.append(Finding(
            check="C4",
            severity="blocker" if len(docs_involved) > 1 else "warn",
            doc=sorted(docs_involved)[0], line=places[0][1],
            message=(f"card id {cid} declared {len(places)}x "
                     f"across {len(docs_involved)} doc(s): {where}"),
            context=places[0][2],
        ))
    return out


#: The metadata line under a card heading: `P0` / 2 天 / 依赖 F1、主计划 Phase 2
CARD_META = re.compile(r"^\s*`?P\d`?\s*/")
#: A card id as it appears inline in a dependency list.
CARD_REF = re.compile(r"\b((?:Phase[A-Z]-)?[A-Z]{1,4}\d{1,3}(?:\.\d+)?[a-z]?)\b")


def check_c9_prereqs_exist(docs: list[Doc]) -> list[Finding]:
    """A card cannot depend on a card that was never written.

    Nothing in a document flags this: "依赖 F16、F19" reads perfectly even
    when F19 does not exist, and the builder only discovers it after picking
    up the card.  Resolution prefers the card's own document, then falls back
    to every other one, because dependencies do cross phases.
    """
    def cards_of(doc: Doc) -> list[tuple[int, str]]:
        return [(i, cid) for i, cid, _t in iter_cards(doc)]

    # Cards are titled "PhaseG-B14" but depended on as "B14".  Both spellings
    # are in active use, so compare on the unprefixed form.
    def bare(cid: str) -> str:
        return re.sub(r"^Phase[A-Z]-", "", cid)

    per_doc = {doc.name: cards_of(doc) for doc in docs}
    here: dict[str, set[str]] = {
        name: {bare(cid) for _i, cid in cards} for name, cards in per_doc.items()
    }
    everywhere: dict[str, str] = {}
    for name, cards in per_doc.items():
        for _i, cid in cards:
            everywhere.setdefault(bare(cid), name)

    def family(ref: str) -> str:
        return re.match(r"^([A-Za-z-]*)", ref).group(1)

    def deps_of(doc: Doc, line_no: int) -> tuple[str, list[str]]:
        meta = next((doc.lines[j] for j in range(line_no, min(line_no + 4,
                                                              len(doc.lines)))
                     if CARD_META.match(doc.lines[j])), None)
        if not meta or "依赖" not in meta:
            return "", []
        tail = meta.split("依赖", 1)[1]
        tail = re.sub(r"Phase\s*[A-Z0-9/]+", " ", tail)
        tail = re.sub(r"[（(][^）)]*[）)]", " ", tail)
        return meta, [bare(r) for r in CARD_REF.findall(tail)]

    # A prefix family that is *partly* dangling is a rename left half-done, and
    # its surviving members are not safe just because they resolve: in
    # PHASE-G-FRONTEND the J7-J12 half is dangling while J1-J6 quietly resolve
    # to PHASE-J's PersonaAgent cards, which the frontend shell never meant.
    suspect_family: dict[str, set[str]] = defaultdict(set)
    for doc in docs:
        for line_no, _cid in per_doc[doc.name]:
            for ref in deps_of(doc, line_no)[1]:
                if ref not in here[doc.name] and ref not in everywhere:
                    suspect_family[doc.name].add(family(ref))

    out: list[Finding] = []
    for doc in docs:
        for line_no, cid in per_doc[doc.name]:
            meta = next((doc.lines[j] for j in range(line_no, min(line_no + 4,
                                                                 len(doc.lines)))
                         if CARD_META.match(doc.lines[j])), None)
            if not meta:
                continue
            tail = meta.split("依赖", 1)[-1] if "依赖" in meta else ""
            if not tail:
                continue
            # "主计划 Phase 2" and "Phase A" are phase references, not cards.
            tail = re.sub(r"Phase\s*[A-Z0-9/]+", " ", tail)
            # "依赖 Phase D 子代理隔离（SB3）+ B6" - the parenthetical names the
            # constraint being honoured, not a card to be built first.
            tail = re.sub(r"[（(][^）)]*[）)]", " ", tail)
            for ref in CARD_REF.findall(tail):
                ref = bare(ref)
                if ref == bare(cid) or ref in here[doc.name]:
                    continue
                if ref in everywhere:
                    if family(ref) in suspect_family[doc.name]:
                        out.append(Finding(
                            check="C9", severity="blocker", doc=doc.name,
                            line=line_no,
                            message=(f"card {cid} depends on {ref}: it resolves "
                                     f"(to {everywhere[ref]}) but other "
                                     f"{family(ref)}* refs in this document "
                                     f"dangle, so this family is a half-done "
                                     f"rename - verify before trusting it"),
                            context=meta.strip()[:140],
                        ))
                    continue
                out.append(Finding(
                    check="C9", severity="blocker", doc=doc.name, line=line_no,
                    message=(f"card {cid} depends on {ref}, which is not a card "
                             f"in any plan document"),
                    context=meta.strip()[:140],
                ))
    return out


SECTION = re.compile(r"^##\s+§(\d+)\s+(.*)$")


def check_c8_section_numbers(docs: list[Doc]) -> list[Finding]:
    """A section number reused inside one document makes "见 §N" ambiguous.

    PHASE-G-DESKTOP restarts numbering for its GX batch, so 11 of its 12
    section numbers appear two or three times and all 319 "§N" references
    have to be disambiguated by context.  Nothing catches this by reading:
    each heading looks fine, and the collision is hundreds of lines away.
    """
    out: list[Finding] = []
    for doc in docs:
        seen: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for i, line in enumerate(doc.lines, 1):
            m = SECTION.match(line)
            if m:
                seen[m.group(1)].append((i, m.group(2).strip()[:40]))
        for num, places in sorted(seen.items(), key=lambda kv: int(kv[0])):
            if len(places) < 2:
                continue
            where = " | ".join(f"{ln}:{t}" for ln, t in places)
            out.append(Finding(
                check="C8", severity="warn", doc=doc.name, line=places[0][0],
                message=(f"section §{num} declared {len(places)}x in one "
                         f"document - every \"见 §{num}\" is ambiguous: {where}"),
            ))
    return out


def check_c7_lossy_text(docs: list[Doc]) -> list[Finding]:
    """Prose destroyed by a lossy encode, reported per contiguous run.

    The damage is invisible to every other check: the file is valid UTF-8,
    the markdown structure survives, code blocks and English identifiers are
    untouched.  What is gone is the part only a human reads - the background,
    the steps, the completion criteria.  PHASE-D lost its entire §3.5 and the
    whole of card D5.5 this way, and neither git nor the .rar archive has a
    copy, because both predate the file.
    """
    out: list[Finding] = []
    for doc in docs:
        # Fenced blocks are exempt: the damage lands in prose, while a fence
        # is where someone quotes the damage as evidence.  Without this the
        # audit entry documenting X13 trips the very check that found it.
        hits: list[int] = []
        inside = False
        for i, line in enumerate(doc.lines, 1):
            if FENCE.match(line):
                inside = not inside
                continue
            # Inline spans are exempt for the same reason as fences: quoting a
            # `??%` placeholder, or the damage itself, is not damage.
            if not inside and LOSSY.search(re.sub(r"`[^`]*`", "", line)):
                hits.append(i)
        if not hits:
            continue
        start = prev = hits[0]
        runs: list[tuple[int, int, int]] = []
        count = 1
        for h in hits[1:]:
            if h - prev > 3:
                runs.append((start, prev, count))
                start, count = h, 0
            prev, count = h, count + 1
        runs.append((start, prev, count))
        for begin, end, n in runs:
            out.append(Finding(
                check="C7", severity="blocker", doc=doc.name, line=begin,
                message=(f"text destroyed by a lossy encode: lines {begin}-{end} "
                         f"({n} line(s)); CJK replaced by literal '?'"),
                context=doc.lines[begin - 1].strip()[:160],
            ))
    return out


def _dead_shas(shas: set[str]) -> set[str]:
    """Which of these no longer resolve in this repository.

    Asking git is the whole point: a SHA is only evidence for as long as it
    resolves, and a squash silently turns it into a 7-character decoration
    that still looks authoritative.
    """
    if not shas:
        return set()
    try:
        proc = subprocess.run(
            ["git", "cat-file", "--batch-check"],
            input="\n".join(sorted(shas)), capture_output=True,
            text=True, cwd=REPO, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return set()  # no git here; fall back to the text-only judgement
    dead = set()
    for line in proc.stdout.splitlines():
        head = line.split(" ", 1)[0]
        if "missing" in line or "ambiguous" in line:
            dead.add(head)
    return dead


def check_c6_done_evidence(docs: list[Doc]) -> list[Finding]:
    """A completed item should be re-verifiable, not merely asserted."""
    candidates: list[tuple[Doc, int, str, set[str]]] = []
    for doc in docs:
        for i, raw in enumerate(doc.lines, 1):
            if not DONE_MARK.match(raw):
                continue
            window = "\n".join(doc.lines[max(0, i - 4): i + 8])
            if VERIFY_HINT.search(window):
                continue
            shas = {s for s in SHA_ONLY.findall(raw)}
            if shas:
                candidates.append((doc, i, raw, shas))

    dead = _dead_shas({s for _d, _i, _r, ss in candidates for s in ss})

    out: list[Finding] = []
    for doc, i, raw, shas in candidates:
        gone = sorted(shas & dead)
        if gone:
            sev = "blocker"
            msg = (f"completed item rests on a SHA that no longer resolves "
                   f"({', '.join(gone)}) - the claim is now unverifiable")
        else:
            sev = "warn"
            msg = ("completed item evidenced only by a SHA; it still resolves "
                   "today, but a squash would silently retire the evidence "
                   "(as it did for PHASE-E's seven)")
        out.append(Finding(check="C6", severity=sev, doc=doc.name, line=i,
                           message=msg, context=raw.strip()[:160]))
    return out


#: A prohibition, with the banned path required to sit immediately after the
#: verb.  Anchoring matters twice over: scanning the whole line makes the
#: sentence banning appserver/handlers/ also ban appserver/team_routes.py,
#: which it names as the correct spelling; and "不新建第二套 X" is a ban on
#: duplicating a concept, not on the path that happens to follow.
FORBID_PATH = re.compile(
    r"(?:不得新建|禁止新建|不得创建|禁止创建|不新建|不建|must not create)"
    r"\s*\*{0,2}`([^`]+)`"
)
FORBID = re.compile(r"不得新建|禁止新建|不得创建|禁止创建|不新建|不建|must not create")
#: A claim that the path is *absent*, which makes non-existence the expected
#: state rather than a defect.  Anchored for the same reason as FORBID_PATH.
NEG_PATH = re.compile(
    r"(?:无|不存在|未创建|未建|未生成|已删除|已移除|不含|没有|删除)"
    r"\s*\*{0,2}`([^`]+)`"
)
#: A line discussing a known-wrong path rather than instructing anyone to use
#: it - the audit table quotes the bad spelling on purpose.
CITATION = re.compile(
    r"不存在|误|错|违反|勘误|裁定|应改为|已废|作废|X3\b|不符|对不上|冲突|白名单"
)
#: A mapping row - "`bad` | `good`" or "bad 改为 good" - is a card scheduling
#: the rewrite, so downstream uses are stale text with an owner, not orphans.
REMAP = re.compile(r"映射|改为|应落在|→")


def _ban_target(raw: str) -> str | None:
    """Normalise the thing a prohibition names, or None if it names nothing.

    Bans are usually aimed at a *directory* ("不建 `appserver/handlers/`"), and
    the file-path predicate rejects those for want of a source suffix - which
    silently emptied this check of its only real finding.  A trailing slash is
    the author saying "directory", so honour it.
    """
    token = raw.strip().replace("\\", "/")
    if not token or " " in token or any(ch in token for ch in "*?<>|"):
        return None
    if token.endswith("/"):
        token = token.rstrip("/")
        return token if "/" in token else None
    return token if _looks_like_path(token) else None


def check_c5_forbidden_vs_claimed(docs: list[Doc]) -> list[Finding]:
    """One document forbids a path while another tells you to create it.

    Being claimed by a card is not the same as being correct.  X3 is exactly
    this shape: PHASE-M ruled that appserver/handlers/ must never exist (the
    convention is appserver/*_routes.py), yet PHASE-K still lists
    appserver/handlers/plugin.py in its deliverables.  Each document is
    self-consistent; only the pair is wrong, so no per-document review finds
    it.
    """
    forbidden: dict[str, str] = {}
    remapped: set[str] = set()
    for doc in docs:
        if not doc.name.startswith("PHASE"):
            continue  # a research note records an opinion, not a ruling
        for i, line in enumerate(doc.lines, 1):
            for banned in FORBID_PATH.findall(line):
                cleaned = _ban_target(banned)
                if cleaned:
                    forbidden.setdefault(cleaned, f"{doc.name}:{i}")

    # The mapping row and the prohibition are rarely the same sentence: M2
    # bans "appserver/handlers/" in one line and tabulates the replacement in
    # another, so looking only at the banning line finds no owner and reports
    # 15 scheduled rewrites as orphan violations.
    for doc in docs:
        for line in doc.lines:
            if not REMAP.search(line):
                continue
            for bad in forbidden:
                if bad in line.replace("\\", "/"):
                    remapped.add(bad)

    out: list[Finding] = []
    for doc in docs:
        for i, line in enumerate(doc.lines, 1):
            if FORBID.search(line) or CITATION.search(line):
                continue
            for token in PATH_IN_CODE.findall(line):
                norm = token.replace("\\", "/")
                if not _looks_like_path(norm):
                    continue
                for bad, where in forbidden.items():
                    if norm == bad or norm.startswith(bad + "/"):
                        owned = bad in remapped
                        out.append(Finding(
                            check="C5",
                            severity="warn" if owned else "blocker",
                            doc=doc.name, line=i,
                            message=(
                                f"uses `{token}`, but {where} forbids `{bad}`"
                                + (" [rewrite already scheduled there]"
                                   if owned else "")
                            ),
                            context=line.strip()[:160],
                        ))
    return out


#: Prefixes used for registry entries, design rulings and discipline tables.
#: These are numbered like cards and sit under card-shaped headings, but nobody
#: builds them, so demanding an acceptance command of them is noise.
NON_BUILD_PREFIX = re.compile(
    r"^(X\d|DF\d|D[LMNK]\d|OV\d|HN\d|MC\d|DC\d|AC\d|EB\d|MA\d|FXC?\d|NC\d)")

#: Any of these words means the card said *something* about being done.
DONE_WORDS = re.compile(r"验收|判据|完成定义|出口")


def check_c10_cards_have_criteria(docs: list[Doc]) -> list[Finding]:
    """A card with no definition of done cannot be finished or reviewed.

    Every phase document has a house style - 验收命令 plus 完成判据 - and the
    cards that skip it are invisible precisely because they look complete:
    they have a priority, an estimate, an owner and a detailed step list.  What
    they lack only shows up when someone has to decide whether the work is over.

    Container cards are exempt.  A heading that exists only to introduce its own
    halves (L0 -> L0a/L0b) carries no work of its own, and the halves are
    checked on their own terms.
    """
    out: list[Finding] = []
    for doc in docs:
        if not doc.name.startswith(("PHASE-", "00-")):
            continue
        cards = list(iter_cards(doc))
        for idx, (line_no, cid, title) in enumerate(cards):
            if NON_BUILD_PREFIX.match(cid):
                continue
            end = cards[idx + 1][0] - 1 if idx + 1 < len(cards) else len(doc.lines)
            body = "\n".join(doc.lines[line_no:end])
            if DONE_WORDS.search(body):
                continue
            # "拆成 A / B 两半" and friends: the work lives in the halves.
            if re.search(r"拆成|拆分为|拆为|分成.{0,6}两半", title + body[:400]):
                continue
            out.append(Finding(
                check="C10",
                severity="blocker",
                doc=doc.name, line=line_no,
                message=(f"card {cid} has no 验收/判据 anywhere in its "
                         f"{end - line_no} lines - it cannot be marked done"),
                context=title.strip()[:160],
            ))
    return out


CHECKS = {
    "C1": ("file paths exist", check_c1_paths),
    "C2": ("links and anchors resolve", check_c2_links),
    "C4": ("card ids unique", check_c4_card_ids),
    "C5": ("no path forbidden elsewhere", check_c5_forbidden_vs_claimed),
    "C6": ("completed items are re-verifiable", check_c6_done_evidence),
    "C7": ("no lossy-encoded prose", check_c7_lossy_text),
    "C8": ("section numbers unique per doc", check_c8_section_numbers),
    "C9": ("card prerequisites exist", check_c9_prereqs_exist),
    "C10": ("cards define done", check_c10_cards_have_criteria),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="append", choices=sorted(CHECKS))
    ap.add_argument("--severity", default="warn", choices=["blocker", "warn", "note"])
    ap.add_argument("--out", help="write the report here as UTF-8")
    args = ap.parse_args()

    # The console on this machine is GBK; the docs are full of CJK and emoji.
    # Without this the report dies on its own output.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    if args.out:
        sys.stdout = open(args.out, "w", encoding="utf-8", errors="replace")  # noqa: SIM115

    docs = load_docs()
    if not docs:
        print(f"no documents under {DOCS}", file=sys.stderr)
        return 1

    order = {"blocker": 0, "warn": 1, "note": 2}
    wanted = args.check or sorted(CHECKS)
    findings: list[Finding] = []
    for key in wanted:
        findings.extend(CHECKS[key][1](docs))

    accepted = _load_accepted()
    n_accepted = 0
    for f in findings:
        for check, needle in accepted:
            if f.check == check and needle in f.message:
                f.severity = "note"
                f.message = "ACCEPTED · " + f.message
                n_accepted += 1
                break

    findings = [f for f in findings if order[f.severity] <= order[args.severity]]
    findings.sort(key=lambda f: (order[f.severity], f.check, f.doc, f.line))

    if args.json:
        print(json.dumps([f.__dict__ for f in findings], ensure_ascii=False, indent=2))
        return 1 if any(f.severity == "blocker" for f in findings) else 0

    print(f"documents scanned : {len(docs)}  "
          f"({sum(len(d.lines) for d in docs)} lines)")
    for key in wanted:
        n = sum(1 for f in findings if f.check == key)
        print(f"  {key} {CHECKS[key][0]:<34} {n} finding(s)")
    print()
    current = None
    for f in findings:
        head = f"{f.severity.upper()} {f.check}"
        if head != current:
            current = head
            print(f"\n===== {head} =====")
        print(f"{f.doc}:{f.line}  {f.message}")
        if f.context:
            print(f"    | {f.context}")
    blockers = sum(1 for f in findings if f.severity == "blocker")
    print(f"\ntotal: {len(findings)} finding(s), {blockers} blocker(s)"
          + (f", {n_accepted} accepted (see {ACCEPT_FILE.name})" if n_accepted
             else ""))
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
