"""WEB-W3-C04. The diff hunk matches a real workspace edit, and other roots are refused."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
TREE = REPO / "apps" / "web" / "src" / "features" / "workspace" / "FileTree.tsx"
_UNIT = Path(__file__).with_name("test_w3_c02_unit.py")
_spec = importlib.util.spec_from_file_location("w3c02_stack_c04", _UNIT)
assert _spec is not None and _spec.loader is not None
_c02 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_c02)

from rxycode_server.persistence.models import Membership, Organization, Project, User  # noqa: E402


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def _workspace() -> Path:
    root = Path(tempfile.mkdtemp(prefix="w3c04-"))
    _git_init(root)
    (root / "hello.txt").write_text("one\n", encoding="utf-8", newline="\n")
    _git(root, "add", "hello.txt")
    _git(root, "commit", "-m", "base")
    (root / "hello.txt").write_text("one\ntwo\n", encoding="utf-8", newline="\n")
    return root


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "c04@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "c04"], cwd=root, check=True)


def _project(root: Path, target: str) -> str:
    engine = create_engine(_c02.URL)
    with Session(engine) as db:
        user = db.scalars(select(User).where(User.kind == "local")).one_or_none()
        if user is None:
            user = User(id=uuid.uuid4().hex, github_id=None, kind="local")
            db.add(user)
            db.flush()
        tenant_id = db.scalars(
            select(Membership.tenant_id).where(Membership.user_id == user.id)
        ).one_or_none()
        if tenant_id is None:
            tenant_id = uuid.uuid4().hex
            db.add(Organization(id=uuid.uuid4().hex, tenant_id=tenant_id))
            db.add(
                Membership(
                    id=uuid.uuid4().hex,
                    tenant_id=tenant_id,
                    user_id=user.id,
                    role="owner",
                )
            )
        project_id = uuid.uuid4().hex
        db.add(
            Project(
                id=project_id,
                tenant_id=tenant_id,
                name="workspace",
                repo_config={"workspace_root": str(root), "target_id": target},
            )
        )
        db.commit()
    engine.dispose()
    os.environ["RXYCODE_WORKSPACE_BASE"] = str(root.parent.resolve())
    return project_id


def test_w3_c04_contract() -> None:
    """A real file edit shows the same added line as git diff."""
    assert TREE.is_file(), "FileTree.tsx is missing"
    root = _workspace()
    diff = _git(root, "diff", "--", "hello.txt")
    assert "+two" in diff
    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _c02._login(page, stack.origin)
            project_id = _project(root, "local:c04")
            page.goto(
                f"{stack.origin}/projects/{project_id}/workspace",
                wait_until="domcontentloaded",
            )
            expect(page.locator("[data-target='local:c04']")).to_be_visible(timeout=10000)
            page.get_by_role("button", name="hello.txt").click()
            hunk = page.locator("[data-hunk-line]")
            expect(hunk.filter(has_text="+two")).to_be_visible()
            shown = "\n".join(hunk.all_text_contents())
            assert "+two" in shown
            assert "+two" in diff
            browser.close()
    finally:
        stack.close()


def test_w3_c04_negative() -> None:
    """A path outside the workspace is refused and the secret is not returned."""
    assert TREE.is_file(), "FileTree.tsx is missing"
    root = _workspace()
    outside = root.parent / f"outside-{root.name}"
    outside.mkdir()
    secret = "workspace-test-secret-c04"
    (outside / "secret.txt").write_text(secret + "\n", encoding="utf-8")
    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _c02._login(page, stack.origin)
            project_id = _project(root, "remote:c04")
            page.goto(
                f"{stack.origin}/projects/{project_id}/workspace",
                wait_until="domcontentloaded",
            )
            page.get_by_label("路径").fill("../" + outside.name + "/secret.txt")
            with page.expect_response(lambda item: "/diff" in item.url) as denied:
                page.get_by_role("button", name="打开").click()
            body = denied.value.text()
            assert denied.value.status == 403
            assert "WORKSPACE_FORBIDDEN" in body
            assert secret not in body
            expect(page.get_by_role("alert")).to_contain_text("拒绝")
            expect(page.get_by_text(secret)).to_have_count(0)
            browser.close()
    finally:
        stack.close()
