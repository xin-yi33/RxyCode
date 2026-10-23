"""W9-Q1: local end-to-end acceptance of the RxyCode web product.

Runs against the dedicated ``rxyw9e2e`` compose stack (see PHASE-W9 card Q1):

    docker compose -p rxyw9e2e -f infra/compose/compose.yaml up -d   # seeded repo
    python -m pytest tests/web/w9/test_e2e.py -v -x

Environment knobs (defaults match the rxyw9e2e bring-up):

- ``RXY_E2E_BASE_URL``     default ``https://localhost:8543`` — the gateway's
  self-signed ``tls internal`` cert means Playwright needs
  ``ignore_https_errors``. (``http://127.0.0.1:8180`` is unusable: Caddy's
  HTTP listener is a bare 308 redirect to the default HTTPS port.)
- ``RXY_E2E_API_CONTAINER`` default ``rxyw9e2e-api-1`` — used for the admin
  invite CLI and the E-1 ``docker restart``.
- ``RXY_E2E_OUT``          evidence dir; default ``~/.rxycode/output/w9-e2e``.
  Every scenario writes ``<name>.png`` screenshots and ``<name>.events.json``
  (the run's ``GET /runs/{id}/events?follow=0`` replay) next to them.

The suite deliberately shares state between tests (E-3 reuses E-2's session,
E-6 needs A's ids) — run the file as a whole; ``-x`` stops at the first real
failure. Real-model runs take minutes; per-test timeouts are generous.

Bring-up note: raise the stack's per-IP limiter for the suite —
``RXYCODE_WEB_RATE_LIMIT_RPM=2000`` at ``up -d`` time. E-9 spins up sixteen
authed browser contexts in seconds; at the 240 default the shared gateway IP
trips the limiter and ``/me`` returns 429, which is a harness-side flake,
not a product signal (the limiter itself is covered by module tests).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

pytestmark = [pytest.mark.e2e, pytest.mark.live, pytest.mark.serial]

BASE_URL = os.environ.get("RXY_E2E_BASE_URL", "https://localhost:8543").rstrip("/")
API_CONTAINER = os.environ.get("RXY_E2E_API_CONTAINER", "rxyw9e2e-api-1")
OUT_DIR = Path(
    os.environ.get(
        "RXY_E2E_OUT", str(Path.home() / ".rxycode" / "output" / "w9-e2e")
    )
).expanduser()


def _resolve_out_dir(request: pytest.FixtureRequest) -> Path:
    """Evidence must land in the REAL user profile — ``tests/conftest.py``
    redirects HOME/USERPROFILE to a managed temp root (deleted on success),
    so ``Path.home()`` inside pytest would point at a throwaway dir. The
    conftest keeps the pre-isolation values in ``_rxycode_saved_env``.
    ``RXY_E2E_OUT`` overrides everything."""
    if os.environ.get("RXY_E2E_OUT"):
        return Path(os.environ["RXY_E2E_OUT"]).expanduser()
    saved = getattr(request.config, "_rxycode_saved_env", None) or {}
    real = saved.get("USERPROFILE") or saved.get("HOME")
    base = Path(real) if real else Path.home()
    return base / ".rxycode" / "output" / "w9-e2e"

TERMINAL = {"succeeded", "failed", "cancelled", "recovery_required"}
PASSWORD = "W9e2e-Passw0rd!"
RUN_TAG = time.strftime("%H%M%S")  # keeps re-runs' user emails unique

# Cross-scenario state (registered ids, run ids, verdicts for the report).
S: dict[str, object] = {"results": {}}


# ---------------------------------------------------------------------------
# docker / API helpers
# ---------------------------------------------------------------------------


def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, env=env
    )


def mint_invite(uses: int = 5) -> str:
    """Mint an invite code inside the api container (code printed once)."""
    done = _docker(
        "exec",
        API_CONTAINER,
        "python",
        "-m",
        "rxycode_server.admin",
        "invite",
        "create",
        "--uses",
        str(uses),
    )
    assert done.returncode == 0, done.stderr
    code = done.stdout.strip().splitlines()[-1].strip()
    assert code, done.stdout
    return code


def wait_api_healthy(timeout_s: float = 240.0) -> None:
    """After ``docker restart``: the healthcheck runs the real probe."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        done = _docker("inspect", API_CONTAINER, "--format", "{{.State.Health.Status}}")
        if done.returncode == 0 and done.stdout.strip() == "healthy":
            return
        time.sleep(3)
    raise TimeoutError(f"{API_CONTAINER} not healthy after {timeout_s}s")


def api_get(context: BrowserContext, path: str):
    """Authed GET through the browser context's cookie jar."""
    return context.request.get(f"{BASE_URL}{path}")


def api_post(context: BrowserContext, path: str, body: dict | None = None):
    """Authed write: fetch a CSRF token first (cookie + header pair)."""
    resp = context.request.get(f"{BASE_URL}/api/v1/auth/csrf")
    assert resp.ok, resp.status
    token = resp.json()["csrf_token"]
    return context.request.post(
        f"{BASE_URL}{path}",
        data=json.dumps(body or {}),
        headers={
            "content-type": "application/json",
            "x-csrf-token": token,
            "origin": BASE_URL,
        },
    )


def save_events(context: BrowserContext, run_id: str, name: str) -> list[dict]:
    """Persist ``GET /runs/{id}/events?follow=0`` as JSON evidence."""
    resp = api_get(context, f"/api/v1/runs/{run_id}/events?follow=0")
    assert resp.ok, f"events fetch failed: {resp.status}"
    events: list[dict] = []
    for block in resp.text().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except ValueError:
                    pass
    (OUT_DIR / f"{name}.events.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return events


def shot(page: Page, name: str) -> Path:
    path = OUT_DIR / f"{name}.png"
    page.screenshot(path=str(path))
    return path


def ensure_idle(context: BrowserContext, timeout_s: float = 90.0) -> None:
    """Cancel every still-active run of the current user — test isolation.

    QUOTA concurrency is 1: a leftover active run makes the next POST /tasks
    fail with '你已有任务在运行' instead of navigating. Scenarios that submit
    call this first so one stalled run cannot cascade into later failures.
    """
    deadline = time.time() + timeout_s
    while True:
        resp = api_get(context, "/api/v1/sessions")
        if not resp.ok:
            return
        pending = {
            row["last_run"]["run_id"]: row["last_run"].get("status")
            for row in resp.json().get("sessions", [])
            if row.get("last_run")
            and row["last_run"].get("status") not in TERMINAL
        }
        if not pending:
            return
        # cancel_requested still occupies the concurrency slot until the worker
        # acks — wait it out; only (re)send cancel to runs not yet asked.
        for rid, st in pending.items():
            if st != "cancel_requested":
                api_post(context, f"/api/v1/runs/{rid}/cancel")
        if time.time() > deadline:
            raise TimeoutError(f"runs still active after cancel: {pending}")
        time.sleep(2)


def note(scenario: str, verdict: str) -> None:
    S["results"][scenario] = verdict


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------


def register(page: Page, email: str, password: str, invite: str) -> None:
    page.goto(f"{BASE_URL}/register")
    page.locator('input[name="email"]').fill(email)
    page.locator('input[name="password"]').fill(password)
    page.locator('input[name="invite-code"]').fill(invite)
    page.locator('button[type="submit"]', has_text="注册").click()
    page.wait_for_url(re.compile(r"/app$"), timeout=30_000)


def login(page: Page, email: str, password: str) -> None:
    page.goto(f"{BASE_URL}/login")
    page.locator('input[name="email"]').fill(email)
    page.locator('input[name="password"]').fill(password)
    page.locator('button[type="submit"]', has_text="登录").click()
    page.wait_for_url(re.compile(r"/app$"), timeout=30_000)


def submit_task(page: Page, text: str, profile: str = "full") -> None:
    """Fill the composer on the current page and send."""
    area = page.locator('textarea[aria-label="消息"]')
    area.fill(text)
    page.locator('select[aria-label="权限模式"]').select_option(profile)
    page.locator('button[aria-label="发送"]').click()


def submit_new_task(page: Page, text: str, profile: str = "full") -> str:
    """Submit from /app (POST /tasks) — returns the new session id."""
    if not page.url.rstrip("/").endswith("/app"):
        page.goto(f"{BASE_URL}/app")
    submit_task(page, text, profile)
    page.wait_for_url(re.compile(r"/app/s/[0-9a-f]+$"), timeout=30_000)
    session_id = page.url.rsplit("/", 1)[-1]
    return session_id


def current_run_id(context: BrowserContext, session_id: str) -> str:
    resp = api_get(context, f"/api/v1/sessions/{session_id}/runs?limit=1")
    assert resp.ok, resp.status
    runs = resp.json()["runs"]
    assert runs, "no runs in session"
    return runs[0]["run_id"]


def run_status(context: BrowserContext, run_id: str) -> str:
    resp = api_get(context, f"/api/v1/runs/{run_id}")
    return str(resp.json().get("status") or "") if resp.ok else f"http-{resp.status}"


def chip_status(page: Page, run_id: str) -> str:
    sel = f'li[id="run-{run_id}"] [data-run-status]'
    node = page.locator(sel)
    return node.get_attribute("data-run-status") if node.count() else ""


def wait_terminal(
    page: Page, context: BrowserContext, run_id: str, timeout_s: float
) -> str:
    """Wait for the status chip to reach a terminal state (API cross-check)."""
    deadline = time.time() + timeout_s
    status = ""
    while time.time() < deadline:
        status = run_status(context, run_id)
        if status in TERMINAL:
            # let the SSE replay + reducer settle the chip
            try:
                page.locator(
                    f'li[id="run-{run_id}"] [data-run-status="{status}"]'
                ).wait_for(timeout=15_000)
            except Exception:
                pass
            return status
        page.wait_for_timeout(2_000)
    raise TimeoutError(f"run {run_id} still {status!r} after {timeout_s}s")


def timeline_kinds(page: Page, run_id: str) -> list[str]:
    """Classify the run's timeline <li> elements in DOM order (skips the
    sticky “新消息” FAB row that is rendered inside the same <ol>)."""
    return page.eval_on_selector_all(
        f'li[id="run-{run_id}"] ol.relative > li',
        """els => els
            .filter(li => !li.querySelector(':scope > button'))
            .map(li => {
                if (li.hasAttribute('data-answer')) return 'final';
                if (li.querySelector('[data-tool-id]')) return 'tool';
                if (li.querySelector('[data-approval-id]')) return 'approval';
                if (li.querySelector('[data-question-id]')) return 'question';
                if (li.querySelector('.bg-bubble')) return 'user';
                return 'text';
            })""",
    )


def timeline_texts(page: Page, run_id: str) -> list[str]:
    """textContent of non-tool timeline items (tools dedupe by callId instead —
    two identical ``cat f`` calls are legitimate rows, not replay dupes)."""
    return page.eval_on_selector_all(
        f'li[id="run-{run_id}"] ol.relative > li',
        """els => els
            .filter(li => !li.querySelector('[data-tool-id]'))
            .filter(li => !li.querySelector(':scope > button'))
            .map(li => (li.textContent || '').trim())""",
    )


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser(request: pytest.FixtureRequest):
    global OUT_DIR
    OUT_DIR = _resolve_out_dir(request)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True)
        yield br
        br.close()


@pytest.fixture(scope="module")
def ctx_a(browser: Browser) -> BrowserContext:
    """User A's logged-in browser context (persists across E-1..E-9)."""
    context = browser.new_context(ignore_https_errors=True)
    yield context
    context.close()


@pytest.fixture(scope="module")
def page_a(ctx_a: BrowserContext) -> Page:
    page = ctx_a.new_page()
    yield page
    page.close()


# ---------------------------------------------------------------------------
# E-1 身份：邀请码 → 注册 → /app → 刷新 → api 重启 → 刷新 → 退出 → 后退
# ---------------------------------------------------------------------------


@pytest.mark.timeout(420)
def test_e1_identity(ctx_a: BrowserContext, page_a: Page):
    invite = mint_invite(uses=8)
    S["invite_uses"] = 8
    # unique per run: re-runs must not collide with "email already exists"
    email = f"w9e2e-alice-{RUN_TAG}@example.com"
    S["user_a"] = email
    S["password_a"] = PASSWORD

    register(page_a, email, PASSWORD, invite)
    assert page_a.url.rstrip("/").endswith("/app")
    page_a.locator('textarea[aria-label="消息"]').wait_for(timeout=15_000)
    shot(page_a, "e1-01-registered")

    # push a second (authenticated) history entry so Back after logout has
    # a real protected URL to land on (register/login/logout all navigate
    # with replace: true, which otherwise leaves a single-entry history).
    page_a.goto(f"{BASE_URL}/app/settings")
    page_a.locator('textarea[aria-label="消息"], main').first.wait_for(
        timeout=15_000
    )

    # refresh keeps the session
    page_a.reload()
    assert "/app" in page_a.url
    page_a.wait_for_timeout(1_000)
    shot(page_a, "e1-02-after-reload")

    # restart the api: session rows are durable — still logged in afterwards
    restart = _docker("restart", API_CONTAINER, timeout=30)
    assert restart.returncode == 0, restart.stderr
    wait_api_healthy()
    page_a.reload()
    page_a.locator("main").first.wait_for(timeout=30_000)
    assert "/login" not in page_a.url, f"session lost after api restart: {page_a.url}"
    shot(page_a, "e1-03-after-api-restart")

    # logout via sidebar account menu → /login
    page_a.locator('button[aria-label^="账户："]').click()
    page_a.locator('[role="menuitem"]', has_text="登出").click()
    page_a.wait_for_url(re.compile(r"/login"), timeout=15_000)
    shot(page_a, "e1-04-logged-out")

    # browser Back must NOT resurrect data. It may land on the pushed /app/*
    # entry (AuthGate must redirect to /login) or have no target at all
    # (replace-navigated history) — either way no authenticated UI may show.
    page_a.go_back()
    try:
        page_a.wait_for_url(re.compile(r"/(login|register)"), timeout=30_000)
    except PlaywrightTimeout:
        pass  # already on /login (no back target) or stuck — assert below
    page_a.wait_for_timeout(1_000)
    S["e1_back_landed"] = page_a.url
    assert "/app" not in page_a.url, f"back exposed authed UI: {page_a.url}"
    body = page_a.locator("body").inner_text() or ""
    assert email not in body, "user identity leaked after back"
    shot(page_a, "e1-05-back-after-logout")
    note("E-1", "pass")


# ---------------------------------------------------------------------------
# E-2 主任务：自动执行 hello.py — 时间线顺序 + 终态后 SSE 关闭
# ---------------------------------------------------------------------------


@pytest.mark.timeout(720)
def test_e2_main_task(ctx_a: BrowserContext, page_a: Page):
    email = str(S["user_a"])
    login(page_a, email, str(S["password_a"]))

    event_requests: list[str] = []
    page_a.on(
        "request",
        lambda req: event_requests.append(req.url)
        if "/api/v1/runs/" in req.url and "/events" in req.url
        else None,
    )

    session_id = submit_new_task(
        page_a,
        "创建 hello.py 打印 hello，然后运行它，最后用一个表格总结你做了什么",
        profile="full",
    )
    S["session_a"] = session_id
    run_id = current_run_id(ctx_a, session_id)
    S["run_e2"] = run_id

    # mid-run evidence + running->completed transition observation
    saw_running_tool = False
    terminal = ""
    deadline = time.time() + 600
    while time.time() < deadline:
        if page_a.locator(f'li[id="run-{run_id}"] [data-tool-status="running"]').count():
            saw_running_tool = True
            shot(page_a, "e2-01-running")
            break
        terminal = run_status(ctx_a, run_id)
        if terminal in TERMINAL:
            break
        page_a.wait_for_timeout(1_000)

    if terminal not in TERMINAL:
        # keep polling the tool row while the run proceeds
        tool_deadline = time.time() + 90
        while time.time() < tool_deadline:
            if page_a.locator(
                f'li[id="run-{run_id}"] [data-tool-status="running"]'
            ).count():
                saw_running_tool = True
                break
            if run_status(ctx_a, run_id) in TERMINAL:
                break
            page_a.wait_for_timeout(500)

    status = wait_terminal(page_a, ctx_a, run_id, timeout_s=600)
    shot(page_a, "e2-02-final")
    events = save_events(ctx_a, run_id, "e2-run")

    kinds = timeline_kinds(page_a, run_id)
    S["e2_kinds"] = kinds
    assert "user" in kinds and "final" in kinds, kinds
    assert "tool" in kinds, f"no tool row rendered: {kinds}"

    # order: final last; tools before it. A text delta may legitimately come
    # AFTER the first tool row — the model can act before narrating (observed
    # on the 2026-10-21 rerun: ['user','tool','text','tool',...]), so text
    # ordering is not asserted.
    i_tool = kinds.index("tool")
    i_final = kinds.index("final")
    assert i_final == len(kinds) - 1, f"final not last: {kinds}"
    assert i_tool < i_final

    # tool rows reached completed (running may be too fast to catch visually;
    # the event log is the ground truth for started->completed)
    completed = page_a.locator(
        f'li[id="run-{run_id}"] [data-tool-status="completed"]'
    ).count()
    failed = page_a.locator(
        f'li[id="run-{run_id}"] [data-tool-status="failed"]'
    ).count()
    started_seqs = [e["seq"] for e in events if e.get("type") == "tool.started"]
    done_seqs = [
        e["seq"] for e in events if e.get("type") in ("tool.completed", "tool.failed")
    ]
    assert started_seqs and done_seqs, "no tool lifecycle in event log"
    assert min(started_seqs) < max(done_seqs)
    S["e2_saw_running_tool"] = saw_running_tool
    S["e2_tool_rows"] = {"completed": completed, "failed": failed}

    # Final rendered as Markdown containing the requested table
    final_li = page_a.locator(f'li[id="run-{run_id}"] li[data-answer]')
    assert final_li.count() == 1
    final_text = final_li.inner_text()
    S["e2_final_head"] = final_text[:300]
    assert (
        final_li.locator("table").count() >= 1 or "|" in final_text
    ), "final answer has no markdown table"

    assert status == "succeeded", f"run ended {status}"
    chip = page_a.locator(f'li[id="run-{run_id}"] [data-run-status="succeeded"]')
    assert chip.count() == 1
    assert "已完成" in (chip.inner_text() or "")

    # SSE closed after terminal: no further /events requests may fire.
    page_a.wait_for_timeout(8_000)
    count_at_terminal = len(
        [u for u in event_requests if "events" in u]
    )  # snapshot BEFORE the quiet window would be ideal; instead compare two samples
    page_a.wait_for_timeout(6_000)
    later = len([u for u in event_requests if "events" in u])
    assert later == count_at_terminal, (
        f"events requests continued after terminal: {count_at_terminal} -> {later}"
    )
    note("E-2", "pass")


# ---------------------------------------------------------------------------
# E-3 审批：同会话 “需要确认”，批准 → 续接 → Final（且看得到 hello.py，D-6）
# ---------------------------------------------------------------------------


@pytest.mark.timeout(720)
def test_e3_approval(ctx_a: BrowserContext, page_a: Page):
    session_id = str(S["session_a"])
    page_a.goto(f"{BASE_URL}/app/s/{session_id}")
    page_a.locator('textarea[aria-label="消息"]').wait_for(timeout=15_000)

    submit_task(page_a, "把 hello.py 改成打印当前时间并运行它", profile="confirm")
    # find the new run id (latest in this session)
    deadline = time.time() + 30
    run_id = ""
    while time.time() < deadline:
        rid = current_run_id(ctx_a, session_id)
        if rid != S["run_e2"]:
            run_id = rid
            break
        page_a.wait_for_timeout(1_000)
    assert run_id, "second run never appeared in the session"
    S["run_e3"] = run_id

    approved = 0
    shots_taken: set[str] = set()
    deadline = time.time() + 600
    status = ""
    while time.time() < deadline:
        status = run_status(ctx_a, run_id)
        if status in TERMINAL:
            break
        cards = page_a.locator(f'li[id="run-{run_id}"] article[data-approval-id]')
        pending = page_a.locator(
            f'li[id="run-{run_id}"] article[data-approval-id]:has(button:has-text("批准"))'
        )
        if pending.count():
            if "light" not in shots_taken:
                shot(page_a, "e3-01-approval-card")
                # E-9 evidence: approval card, dark theme + narrow viewport
                try:
                    page_a.locator('button[aria-label="切换到深色"]').click()
                    page_a.wait_for_timeout(400)
                    shot(page_a, "e9-approval-1280-dark")
                    page_a.set_viewport_size({"width": 375, "height": 812})
                    page_a.wait_for_timeout(400)
                    shot(page_a, "e9-approval-375-dark")
                    page_a.set_viewport_size({"width": 1280, "height": 800})
                    page_a.locator('button[aria-label="切换到浅色"]').click()
                    page_a.wait_for_timeout(400)
                except Exception:
                    pass
                shots_taken.add("light")
            pending.first.locator('button:has-text("批准")').click()
            approved += 1
            page_a.wait_for_timeout(1_500)
            if approved >= 2:
                # approval + resume is proven twice; a chatty model under
                # confirm can otherwise cycle indefinitely — cancel now and
                # assert the cancel settles, not just the approval loop.
                api_post(ctx_a, f"/api/v1/runs/{run_id}/cancel")
            continue
        if cards.count() and not pending.count():
            page_a.wait_for_timeout(1_000)
            continue
        page_a.wait_for_timeout(1_500)

    assert approved >= 1, "confirm profile never raised an approval card"
    if status not in TERMINAL:
        status = wait_terminal(page_a, ctx_a, run_id, timeout_s=180)
    assert status in {"succeeded", "cancelled"}, f"run ended {status}"
    S["e3_approvals"] = approved

    if status == "succeeded":
        final_li = page_a.locator(f'li[id="run-{run_id}"] li[data-answer]')
        final_li.wait_for(timeout=30_000)
        final_text = final_li.inner_text()
        assert "hello.py" in final_text.lower(), "final never referenced hello.py"
        shot(page_a, "e3-02-final")
    save_events(ctx_a, run_id, "e3-run")
    note("E-3", f"pass (approvals={approved}, status={status})")


# ---------------------------------------------------------------------------
# E-4 提问：澄清式任务 —— agent 提问则回答，否则记录 N/A
# ---------------------------------------------------------------------------


@pytest.mark.timeout(720)
def test_e4_question(ctx_a: BrowserContext, page_a: Page):
    # E-3 may leave its run parked (waiting_approval) in session_a — it still
    # holds the concurrency slot, so E-4's submit would 429 without cleanup.
    ensure_idle(ctx_a)
    session_id = str(S["session_a"])
    page_a.goto(f"{BASE_URL}/app/s/{session_id}")
    submit_task(
        page_a, "帮我选一种语言写个排序，然后写出来", profile="confirm"
    )
    deadline = time.time() + 30
    run_id = ""
    while time.time() < deadline:
        rid = current_run_id(ctx_a, session_id)
        if rid not in {str(S["run_e2"]), str(S.get("run_e3", ""))}:
            run_id = rid
            break
        page_a.wait_for_timeout(1_000)
    assert run_id, "E-4 run never appeared"
    S["run_e4"] = run_id

    asked = False
    answered = False
    status = ""
    approvals = 0
    deadline = time.time() + 420
    while time.time() < deadline:
        status = run_status(ctx_a, run_id)
        if status in TERMINAL:
            break
        # confirm 档：run 也会停在审批卡上 —— 同 E-3，批准后继续推进。
        # 上限后取消：啰嗦模型的探测循环不应把场景烧到超时。
        pending = page_a.locator(
            f'li[id="run-{run_id}"] article[data-approval-id]:has(button:has-text("批准"))'
        )
        if pending.count():
            pending.first.locator('button:has-text("批准")').click()
            approvals += 1
            if approvals >= 8:
                api_post(ctx_a, f"/api/v1/runs/{run_id}/cancel")
            page_a.wait_for_timeout(1_500)
            continue
        qcard = page_a.locator(f'li[id="run-{run_id}"] article[data-question-id]')
        if qcard.count():
            asked = True
            shot(page_a, "e4-01-question-card")
            option = qcard.first.locator("button", has_not_text="发送")
            if option.count():
                option.first.click()
            else:
                qcard.first.locator('input[aria-label="回答"]').fill("Python")
                qcard.first.locator('button:has-text("发送")').click()
            answered = True
            page_a.wait_for_timeout(2_000)
            continue
        page_a.wait_for_timeout(2_000)

    if status not in TERMINAL:
        status = wait_terminal(page_a, ctx_a, run_id, timeout_s=240)
    shot(page_a, "e4-02-final")
    save_events(ctx_a, run_id, "e4-run")

    if asked:
        assert answered
        # resolved card collapses into "你的回答：…" or the run continued
        assert status in TERMINAL
        note("E-4", "pass (question asked+answered)")
    else:
        # the agent never asked — allowed N/A per the card
        note("E-4", "N/A (agent never asked)")
        S["e4_na"] = True


# ---------------------------------------------------------------------------
# E-5 取消：长任务运行中点“停止”→ 取消中 → 已取消，侧栏状态点更新
# ---------------------------------------------------------------------------


@pytest.mark.timeout(420)
def test_e5_cancel(ctx_a: BrowserContext, page_a: Page):
    ensure_idle(ctx_a)
    session_id = submit_new_task(
        page_a,
        "先运行 sleep 20，然后创建 flag.txt 写入 done，最后用一句话总结",
        profile="full",
    )
    S["session_e5"] = session_id
    run_id = current_run_id(ctx_a, session_id)
    S["run_e5"] = run_id

    # wait until it is actually running (leased/running) or shows activity
    deadline = time.time() + 120
    while time.time() < deadline:
        if run_status(ctx_a, run_id) in {"running", "leased"}:
            break
        page_a.wait_for_timeout(1_000)
    shot(page_a, "e5-01-running")

    page_a.locator('button[aria-label="停止"]').click()
    # transient "取消中" state (button label or status chip)
    try:
        page_a.locator(
            'button[aria-label="取消中…"], '
            f'li[id="run-{run_id}"] [data-run-status="cancel_requested"]'
        ).first.wait_for(timeout=15_000)
        S["e5_saw_cancelling"] = True
        shot(page_a, "e5-02-cancelling")
    except Exception:
        S["e5_saw_cancelling"] = False

    status = wait_terminal(page_a, ctx_a, run_id, timeout_s=180)
    assert status == "cancelled", f"expected cancelled, got {status}"
    chip = page_a.locator(f'li[id="run-{run_id}"] [data-run-status="cancelled"]')
    assert "已取消" in (chip.inner_text() or "")
    shot(page_a, "e5-03-cancelled")

    # sidebar status dot for this session reflects the cancel
    side = page_a.locator(f'aside a[href="/app/s/{session_id}"]')
    deadline = time.time() + 40
    side_text = ""
    while time.time() < deadline:
        side_text = side.inner_text() if side.count() else ""
        if "已取消" in side_text:
            break
        page_a.wait_for_timeout(2_000)
    assert "已取消" in side_text, f"sidebar still shows {side_text!r}"
    save_events(ctx_a, run_id, "e5-run")
    note("E-5", "pass")


# ---------------------------------------------------------------------------
# E-6 隔离：用户 B 访问 A 的会话页与 run —— 404 / 不泄露
# ---------------------------------------------------------------------------


@pytest.mark.timeout(240)
def test_e6_isolation(browser: Browser, ctx_a: BrowserContext):
    invite = mint_invite(uses=3)
    email_b = f"w9e2e-bob-{RUN_TAG}@example.com"
    S["user_b"] = email_b

    ctx_b = browser.new_context(ignore_https_errors=True)
    page_b = ctx_b.new_page()
    register(page_b, email_b, PASSWORD, invite)

    a_session = str(S["session_a"])
    a_run = str(S["run_e2"])

    # API level: every A-owned resource 404s for B
    for path in (
        f"/api/v1/sessions/{a_session}",
        f"/api/v1/sessions/{a_session}/runs",
        f"/api/v1/runs/{a_run}",
        f"/api/v1/runs/{a_run}/events?follow=0",
    ):
        resp = api_get(ctx_b, path)
        assert resp.status == 404, f"{path} -> {resp.status} (expected 404)"

    # Page level: A's session URL shows a not-found alert and no data leak
    page_b.goto(f"{BASE_URL}/app/s/{a_session}")
    page_b.locator('[role="alert"]').wait_for(timeout=15_000)
    body = page_b.locator("body").inner_text()
    assert "创建 hello.py" not in body, "user A's task text leaked to user B"
    shot(page_b, "e6-01-cross-tenant-session")

    # run-compat route shows “任务不存在”
    page_b.goto(f"{BASE_URL}/runs/{a_run}")
    page_b.locator("text=任务不存在").first.wait_for(timeout=15_000)
    shot(page_b, "e6-02-cross-tenant-run")
    page_b.close()
    ctx_b.close()
    note("E-6", "pass")


# ---------------------------------------------------------------------------
# E-7 断线：运行中 offline 5s → 恢复 → 无重复时间线项、不丢 Final
# ---------------------------------------------------------------------------


@pytest.mark.timeout(600)
def test_e7_reconnect(ctx_a: BrowserContext, page_a: Page):
    ensure_idle(ctx_a)
    session_id = submit_new_task(
        page_a,
        "创建 sum.py 计算 1 到 100 的和并打印结果，运行它，然后总结",
        profile="full",
    )
    run_id = current_run_id(ctx_a, session_id)
    S["run_e7"] = run_id

    # wait until the timeline actually streams (>=2 items or a tool row)
    deadline = time.time() + 180
    while time.time() < deadline:
        kinds = timeline_kinds(page_a, run_id)
        if len(kinds) >= 2 or "tool" in kinds:
            break
        if run_status(ctx_a, run_id) in TERMINAL:
            break
        page_a.wait_for_timeout(1_000)

    ctx_a.set_offline(True)
    try:
        page_a.wait_for_timeout(5_000)
        shot(page_a, "e7-01-offline")
        # dark-theme mid-run evidence for E-9
        try:
            page_a.locator('button[aria-label="切换到深色"]').click()
            page_a.set_viewport_size({"width": 768, "height": 1024})
            page_a.wait_for_timeout(300)
            shot(page_a, "e9-running-768-dark")
            page_a.set_viewport_size({"width": 1280, "height": 800})
            page_a.locator('button[aria-label="切换到浅色"]').click()
        except Exception:
            pass
    finally:
        ctx_a.set_offline(False)

    status = wait_terminal(page_a, ctx_a, run_id, timeout_s=420)
    shot(page_a, "e7-02-final")
    events = save_events(ctx_a, run_id, "e7-run")

    texts = [t for t in timeline_texts(page_a, run_id) if len(t) > 10]
    dupes = [t for t in set(texts) if texts.count(t) > 1]
    assert not dupes, f"duplicate timeline items after reconnect: {dupes[:3]}"
    tool_ids = page_a.eval_on_selector_all(
        f'li[id="run-{run_id}"] [data-tool-id]',
        "els => els.map(e => e.getAttribute('data-tool-id'))",
    )
    assert len(tool_ids) == len(set(tool_ids)), "duplicated tool rows"
    finals = page_a.locator(f'li[id="run-{run_id}"] li[data-answer]').count()
    assert finals == 1, f"final answer rendered {finals} times"
    assert status in TERMINAL
    S["e7_status"] = status
    S["e7_events"] = len(events)
    note("E-7", f"pass (status={status})")


# ---------------------------------------------------------------------------
# E-8 准入：已有活跃 run 时另一个会话再提交 → “你已有任务在运行”/409
# ---------------------------------------------------------------------------


@pytest.mark.timeout(300)
def test_e8_admission(ctx_a: BrowserContext, page_a: Page):
    # first run — kept busy with sleep so it stays active
    ensure_idle(ctx_a)
    session1 = submit_new_task(
        page_a, "先运行 sleep 45，然后创建 hold.txt 写入 x", profile="full"
    )
    run1 = current_run_id(ctx_a, session1)
    S["run_e8"] = run1
    deadline = time.time() + 90
    while time.time() < deadline:
        if run_status(ctx_a, run1) in {"running", "leased", "pending"}:
            break
        page_a.wait_for_timeout(1_000)
    assert run_status(ctx_a, run1) in {"running", "leased", "pending"}

    # second submission on a NEW session must be refused
    page_a.goto(f"{BASE_URL}/app")
    submit_task(page_a, "第二个任务：创建 later.txt 写入 later", profile="full")
    alert = page_a.locator('p[role="alert"]')
    alert.wait_for(timeout=30_000)
    text = alert.inner_text()
    S["e8_refusal"] = text
    shot(page_a, "e8-01-quota-refused")
    assert (
        "你已有任务在运行" in text or "该会话已有任务在运行" in text
    ), f"unexpected refusal text: {text!r}"
    # still on /app — no phantom session was navigated to
    assert page_a.url.rstrip("/").endswith("/app")

    # cleanup: cancel the first run so the account is free again
    resp = api_post(ctx_a, f"/api/v1/runs/{run1}/cancel")
    assert resp.ok, resp.status
    deadline = time.time() + 120
    while time.time() < deadline:
        if run_status(ctx_a, run1) in TERMINAL:
            break
        time.sleep(2)
    save_events(ctx_a, run1, "e8-run")
    note("E-8", f"pass ({text.strip()})")


# ---------------------------------------------------------------------------
# E-9 视觉：375/768/1280/1440 × 浅/深 — 登录/首页/运行中/审批/Final/控制台
# ---------------------------------------------------------------------------

VIEWPORTS = [(375, 812), (768, 1024), (1280, 800), (1440, 900)]


def _no_hscroll(page: Page) -> bool:
    return page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
        " && document.body.scrollWidth <= window.innerWidth + 1"
    )


@pytest.mark.timeout(600)
def test_e9_visual(browser: Browser, ctx_a: BrowserContext):
    session_id = str(S["session_a"])
    # clone A's session cookie instead of re-logging in per context — the
    # per-email /auth/login rate limit (5/min) would otherwise trip.
    auth_state = ctx_a.storage_state()
    problems: list[str] = []
    shots: list[str] = []

    def check(page: Page, name: str) -> None:
        page.wait_for_timeout(600)
        shot(page, name)
        shots.append(f"{name}.png")
        if not _no_hscroll(page):
            problems.append(f"{name}: horizontal scrollbar")
        if not (page.locator("body").inner_text() or "").strip():
            problems.append(f"{name}: blank page")

    for width, height in VIEWPORTS:
        for theme in ("light", "dark"):
            tag = f"{width}-{theme}"
            # login page (unauthenticated context)
            anon = browser.new_context(
                ignore_https_errors=True,
                viewport={"width": width, "height": height},
            )
            anon.add_cookies(
                [
                    {
                        "name": "rxy_theme",
                        "value": theme,
                        "url": BASE_URL,
                    }
                ]
            )
            p = anon.new_page()
            p.goto(f"{BASE_URL}/login")
            p.locator('input[name="email"]').wait_for(timeout=15_000)
            check(p, f"e9-login-{tag}")
            p.close()
            anon.close()

            # authed context at this size+theme
            ctx = browser.new_context(
                ignore_https_errors=True,
                viewport={"width": width, "height": height},
                storage_state=auth_state,
            )
            ctx.add_cookies(
                [{"name": "rxy_theme", "value": theme, "url": BASE_URL}]
            )
            ap = ctx.new_page()
            ap.goto(f"{BASE_URL}/app")
            # loaded-stack first paint can exceed 15s (session list + me + SSE
            # handshake); 30s keeps the check meaningful without false flakes.
            ap.locator('textarea[aria-label="消息"]').wait_for(timeout=30_000)
            check(ap, f"e9-home-{tag}")

            # finished session: Final + tool rows visible
            ap.goto(f"{BASE_URL}/app/s/{session_id}")
            ap.locator(f'li[id="run-{S["run_e2"]}"] li[data-answer]').wait_for(
                timeout=30_000
            )
            check(ap, f"e9-final-{tag}")

            # console panel (xl sidebar at 1280+, fullscreen below)
            ap.locator('button[aria-label="打开控制台"]').click()
            ap.locator('aside[aria-label="控制台"]').wait_for(timeout=10_000)
            check(ap, f"e9-console-{tag}")
            if width >= 1280:
                aside = ap.locator('aside[aria-label="控制台"]')
                # exact name match — has-text is a substring match and tool-row
                # buttons' titles can contain 运行/用量, causing strict-mode hits.
                aside.get_by_role("button", name="运行", exact=True).click()
                check(ap, f"e9-console-run-{tag}")
                aside.get_by_role("button", name="用量", exact=True).click()
                check(ap, f"e9-console-usage-{tag}")
            ap.close()
            ctx.close()

    S["e9_shots"] = shots
    assert not problems, "; ".join(problems)
    note("E-9", f"pass ({len(shots)} screenshots)")


# ---------------------------------------------------------------------------
# evidence index — runs last regardless of outcome
# ---------------------------------------------------------------------------


@pytest.mark.timeout(60)
def test_zz_evidence_index(ctx_a: BrowserContext):
    """Write a machine-readable index of every artifact for the report."""
    index = {
        "base_url": BASE_URL,
        "results": S.get("results", {}),
        "user_a": S.get("user_a"),
        "user_b": S.get("user_b"),
        "session_a": S.get("session_a"),
        "runs": {
            k: v
            for k, v in S.items()
            if k.startswith("run_") or k.startswith("session_")
        },
        "e2_kinds": S.get("e2_kinds"),
        "e8_refusal": S.get("e8_refusal"),
        "artifacts": sorted(p.name for p in OUT_DIR.iterdir()),
    }
    # per-run token usage straight from the durable usage_records table
    usage = _docker(
        "exec",
        "rxyw9e2e-postgres-1",
        "psql",
        "-U",
        "rxycode",
        "-d",
        "rxycode",
        "-Atc",
        "select run_id, model_id, tokens, amount, currency from usage_records",
    )
    index["usage_records"] = usage.stdout
    (OUT_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
