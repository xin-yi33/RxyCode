"""W3 question-card regression: vertical numbered options, payload order,
and exactly-one answer submission.

The cloud incident (session 0e7dab8474874bbaadc443e4d99fd18f / run
211f0165ba014f3dae77dac8e5626491, question.requested seq 244) shipped a card
that rendered four options as a horizontal wrapping row, and whose label
ternary replaced EVERY option's text with "提交中…" on a single click — which
reads as "all options were submitted". This module pins the fixed contract:

* options render as a vertical <ol> with explicit 1. 2. 3. 4. in payload order;
* clicking one option POSTs exactly one body with that option's value;
* only the clicked option shows "提交中…", the others keep their labels;
* a double dispatch (mobile double-tap / duplicate handler) still yields ONE
  POST — the module-level guard is synchronous, not React state;
* the card folds to "你的回答：<label>" (value -> label), not the raw value;
* the free-text variant still submits exactly what the user typed;
* a 409 QUESTION_STALE reply still folds the card to "已被处理".

The app is the production bundle (vite build + vite preview); every /api/v1
call is stubbed with page.route, so this is UI-contract coverage, not a live
server run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"
# Per-xdist-worker build output — sibling modules share nothing under apps/web.
_WORKER = re.sub(r"[^A-Za-z0-9_]", "_", os.environ.get("PYTEST_XDIST_WORKER") or "main")
_DIST = WEB / ("dist" if _WORKER == "main" else f"dist-{_WORKER}")

RUN_ID = "run-question-card-1"
SESSION_ID = "session-question-card-1"
QUESTION_ID = "dcf987922555"

# The four options from the cloud incident, verbatim (label/value pairs).
CHOICE_OPTIONS = [
    {"label": "你把正文直接粘贴到对话里", "value": "paste"},
    {"label": "把 docx 另存为 .txt 或 .md 后重新上传", "value": "convert_txt"},
    {
        "label": "把内容导出成 PDF 或逐页截图上传（我可用 OCR 读）",
        "value": "pdf_or_images",
    },
    {
        "label": "先说说你的目标（如校对/总结/查重/改格式），我按目标给方案",
        "value": "state_goal",
    },
]

ME = {
    "user": {
        "id": "user-ui-fixture",
        "kind": "password",
        "email": "synthetic-ui@example.invalid",
        "display_name": "Synthetic UI fixture",
        "github_id": None,
    },
    "organization": {"id": "org-ui-fixture", "tenant_id": "tenant-ui-fixture"},
    "membership": {"role": "owner"},
    "default_project_id": None,
}

PREFS = {
    "revision": 1,
    "locale": "auto",
    "sidebar": {"grouping": "merged", "sort": "updated_at", "show_projects": True},
    "appearance": {
        "mode": "light",
        "separate_modes": False,
        "shared": {},
        "light": None,
        "dark": None,
        "reduced_motion": "system",
        "diff_markers": "color",
    },
}

CAPABILITIES = {
    "mode": "password",
    "password": True,
    "registration": "open",
    "github": False,
    "local": False,
    "captcha": None,
    "code_delivery": "none",
}

SESSION_ROW = {
    "id": SESSION_ID,
    "title": "问题卡回归会话",
    "project_id": "project-ui-fixture",
    "updated_at": None,
    "last_run": {"run_id": RUN_ID, "status": "succeeded"},
}

RUN_SUMMARY = {
    "run_id": RUN_ID,
    "status": "succeeded",
    "created_at": None,
    "message": "读一下这份文件",
    "permission_profile": "confirm",
    "final_preview": "",
    "model": None,
}

RUN_DETAIL = {
    "run_id": RUN_ID,
    "status": "succeeded",
    "session_id": SESSION_ID,
    "event_seq": 2,
    "created_at": None,
    "message": "读一下这份文件",
    "permission_profile": "confirm",
    "model": None,
}

ARTIFACTS = {
    "run_id": RUN_ID,
    "manifest_status": "complete",
    "manifest_revision": 1,
    "next_cursor": None,
    "artifacts": [],
}


def _sse(events: list[dict]) -> str:
    return "".join(
        "data: " + json.dumps(event, ensure_ascii=False) + "\n\n" for event in events
    )


def _question_events(question: dict) -> str:
    return _sse(
        [
            {"seq": 1, "type": "run.created", "payload": {"message": "读一下这份文件"}},
            {"seq": 2, "type": "question.requested", "payload": question},
        ]
    )


class QuestionApi:
    """Stub the whole app API; hold answer POSTs so in-flight UI is observable."""

    def __init__(
        self,
        question: dict,
        *,
        hold_answers: bool = True,
        stale_on_answer: bool = False,
    ) -> None:
        self.question = question
        self.question_id = str(question["question_id"])
        self.hold_answers = hold_answers
        self.stale_on_answer = stale_on_answer
        self.posts: list[dict] = []
        self.held: list = []
        self.questions_gets = 0
        self.questions: list[dict] = [
            {
                "question_id": self.question_id,
                "prompt": str(question.get("prompt") or ""),
                "header": str(question.get("header") or ""),
                "options": list(question.get("options") or []),
            }
        ]

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _json(route, status: int, payload: object) -> None:
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    # -- route handler ---------------------------------------------------
    def handle(self, route) -> None:
        request = route.request
        method = request.method.upper()
        path = urlparse(request.url).path

        if path == f"/api/v1/runs/{RUN_ID}/questions":
            if method == "POST":
                self.posts.append(json.loads(request.post_data or "{}"))
                if self.stale_on_answer:
                    self.questions.clear()
                    self._json(route, 409, {"detail": "QUESTION_STALE"})
                    return
                if self.hold_answers:
                    # Leave the request paused; the test asserts the in-flight
                    # UI, then fulfills this route explicitly.
                    self.held.append(route)
                    return
                self._json(route, 200, {"status": "accepted"})
                return
            self.questions_gets += 1
            self._json(route, 200, {"questions": list(self.questions)})
            return
        if path == f"/api/v1/runs/{RUN_ID}/events":
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=_question_events(self.question),
            )
            return
        if path == f"/api/v1/runs/{RUN_ID}/artifacts":
            self._json(route, 200, ARTIFACTS)
            return
        if path == f"/api/v1/runs/{RUN_ID}":
            self._json(route, 200, RUN_DETAIL)
            return
        if path == f"/api/v1/sessions/{SESSION_ID}/runs":
            self._json(route, 200, {"runs": [RUN_SUMMARY], "next_cursor": None})
            return
        if path == f"/api/v1/sessions/{SESSION_ID}":
            self._json(route, 200, SESSION_ROW)
            return
        if path == "/api/v1/sessions":
            self._json(route, 200, {"sessions": [SESSION_ROW]})
            return
        if path == "/api/v1/me/preferences":
            self._json(route, 200, PREFS)
            return
        if path == "/api/v1/me":
            self._json(route, 200, ME)
            return
        if path == "/api/v1/auth/csrf":
            self._json(route, 200, {"csrf_token": "question-card-test-csrf"})
            return
        if path == "/api/v1/auth/capabilities":
            self._json(route, 200, CAPABILITIES)
            return
        if path == "/api/v1/auth/device":
            self._json(route, 200, {"status": "active"})
            return
        if path == "/api/v1/models/access":
            self._json(
                route,
                200,
                {
                    "require_byok": False,
                    "platform_allowed": True,
                    "byok_available": True,
                    "default_model_ref": None,
                },
            )
            return
        if path == "/api/v1/models":
            self._json(route, 200, {"models": [], "default_model_ref": None})
            return
        self._json(route, 200, {})


@pytest.fixture(scope="session")
def production_origin() -> str:
    """Build the real apps/web bundle once and serve it with vite preview."""
    node = shutil.which("node")
    vite = WEB / "node_modules" / "vite" / "bin" / "vite.js"
    if not node or not vite.is_file():
        pytest.skip("Node.js and the installed apps/web Vite dependency are required")

    subprocess.run(
        [node, str(vite), "build", "--outDir", _DIST.name],
        cwd=WEB,
        check=True,
        timeout=300,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    origin = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [
            node,
            str(vite),
            "preview",
            "--outDir",
            _DIST.name,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ],
        cwd=WEB,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"Vite preview exited with {server.returncode}")
            try:
                with urlopen(origin, timeout=0.5) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Vite preview did not become ready in 60 seconds")
        yield origin
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


@pytest.fixture
def browser() -> Browser:
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - environment guard
            pytest.skip(f"Chromium could not launch ({exc})")
        yield instance
        instance.close()


def _open_card(
    browser: Browser, origin: str, api: QuestionApi
) -> tuple[Page, object]:
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
        locale="zh-CN",
    )
    page = context.new_page()
    page.route("**/api/v1/**", api.handle)
    page.goto(f"{origin}/app/s/{SESSION_ID}")
    card = page.locator(
        f'li[id="run-{RUN_ID}"] article[data-question-id="{api.question_id}"]'
    )
    card.wait_for(timeout=30_000)
    return page, card


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def _wait_for_post(api: QuestionApi, page: Page, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if api.posts:
            return
        page.wait_for_timeout(50)
    raise AssertionError("the answer POST never reached the stubbed API")


def _choice_question() -> dict:
    return {
        "header": "文档读取受阻",
        "prompt": "这份 Word 文件读不出正文，你希望怎么继续？",
        "options": CHOICE_OPTIONS,
        "input_type": "choice",
        "question_id": QUESTION_ID,
    }


def test_question_options_are_a_vertical_numbered_payload_order_list(
    browser: Browser, production_origin: str
) -> None:
    api = QuestionApi(_choice_question())
    page, card = _open_card(browser, production_origin, api)
    try:
        # semantic list + one row per option, in exactly the payload order.
        ol = card.locator("ol")
        expect(ol).to_have_count(1)
        items = ol.locator(":scope > li")
        expect(items).to_have_count(len(CHOICE_OPTIONS))

        buttons = card.locator("[data-option-index]")
        expect(buttons).to_have_count(len(CHOICE_OPTIONS))
        texts = [_norm(text) for text in buttons.all_inner_texts()]
        expected = [
            f"{index}. {option['label']}"
            for index, option in enumerate(CHOICE_OPTIONS, start=1)
        ]
        assert texts == expected, texts
        assert [int(buttons.nth(i).get_attribute("data-option-index")) for i in range(4)] == [
            1,
            2,
            3,
            4,
        ]

        # vertical: each row starts below the previous one and shares the left edge.
        boxes = [buttons.nth(i).bounding_box() for i in range(len(CHOICE_OPTIONS))]
        assert all(box is not None for box in boxes)
        for previous, current in zip(boxes, boxes[1:]):
            assert current["y"] > previous["y"] + 4, boxes
            assert abs(current["x"] - previous["x"]) < 2, boxes
            # full-width row (not a wrapping inline pill row).
            assert current["width"] > 0.8 * card.bounding_box()["width"], boxes
        for index in range(len(CHOICE_OPTIONS)):
            assert buttons.nth(index).get_attribute("aria-label") == (
                f"选项 {index + 1}：{CHOICE_OPTIONS[index]['label']}"
            )
    finally:
        page.context.close()


def test_one_click_posts_exactly_one_option_value_and_only_that_row_busy(
    browser: Browser, production_origin: str
) -> None:
    api = QuestionApi(_choice_question())
    page, card = _open_card(browser, production_origin, api)
    try:
        buttons = card.locator("[data-option-index]")
        # nothing is busy before the click
        for index in range(len(CHOICE_OPTIONS)):
            assert "提交中…" not in _norm(buttons.nth(index).inner_text())

        buttons.nth(1).click()
        _wait_for_post(api, page)

        # exactly one POST, carrying exactly the clicked option's value.
        assert len(api.posts) == 1, api.posts
        assert api.posts[0] == {
            "question_id": QUESTION_ID,
            "answer": CHOICE_OPTIONS[1]["value"],
        }

        # in-flight: only the clicked row says 提交中…; every other row keeps
        # its own label (the old bug swapped all four to 提交中…).
        in_flight = card.locator("[data-option-index]")
        for index in range(len(CHOICE_OPTIONS)):
            text = _norm(in_flight.nth(index).inner_text())
            assert text.startswith(f"{index + 1}. "), text
            if index == 1:
                assert "提交中…" in text, text
                assert in_flight.nth(index).get_attribute("aria-busy") == "true"
            else:
                assert "提交中…" not in text, text
                assert in_flight.nth(index).get_attribute("aria-busy") is None
                assert _norm(in_flight.nth(index).inner_text()) == (
                    f"{index + 1}. {CHOICE_OPTIONS[index]['label']}"
                )
            assert in_flight.nth(index).is_disabled()

        # mobile double-tap / duplicate handler: two synchronous dispatches must
        # not produce a second POST (the guard is a ref + module claim, so React
        # batching cannot window the second one through).
        page.evaluate(
            """() => {
              const button = document.querySelector(
                'article[data-question-id] [data-option-index="2"]',
              );
              if (!button) return;
              button.click();
              button.click();
            }"""
        )
        page.wait_for_timeout(300)
        assert len(api.posts) == 1, api.posts

        # release the held POST -> optimistic fold.
        assert len(api.held) == 1
        api.held[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "accepted"}),
        )
        folded = page.locator(
            f'li[id="run-{RUN_ID}"] [data-question-answered][data-question-id="{QUESTION_ID}"]'
        )
        folded.wait_for(timeout=10_000)
        expect(card).to_have_count(0)
        folded_text = _norm(folded.inner_text())
        # human label, not the raw wire value
        assert "你的回答：" in folded_text, folded_text
        assert CHOICE_OPTIONS[1]["label"] in folded_text, folded_text
        assert CHOICE_OPTIONS[1]["value"] not in folded_text, folded_text
        assert "提交中…" not in folded_text
        assert len(api.posts) == 1, api.posts
    finally:
        page.context.close()


def test_text_question_keeps_free_input_and_submits_once(
    browser: Browser, production_origin: str
) -> None:
    text_question = {
        "header": "需要澄清",
        "prompt": "请补充要读取的文件路径。",
        "input_type": "text",
        "question_id": "q-free-text-1",
    }
    api = QuestionApi(text_question)
    page, card = _open_card(browser, production_origin, api)
    try:
        # choice variant must not appear for a free-text question.
        expect(card.locator("[data-option-index]")).to_have_count(0)
        field = card.locator('input[aria-label="回答"]')
        field.fill("D:/docs/report.docx")
        card.locator('button:has-text("发送")').click()
        _wait_for_post(api, page)
        assert len(api.posts) == 1, api.posts
        assert api.posts[0] == {
            "question_id": "q-free-text-1",
            "answer": "D:/docs/report.docx",
        }
        assert len(api.held) == 1
        api.held[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "accepted"}),
        )
        folded = page.locator(
            f'li[id="run-{RUN_ID}"] [data-question-answered][data-question-id="q-free-text-1"]'
        )
        folded.wait_for(timeout=10_000)
        assert "你的回答：D:/docs/report.docx" in _norm(folded.inner_text())
    finally:
        page.context.close()


def test_stale_409_folds_the_card_without_a_second_post(
    browser: Browser, production_origin: str
) -> None:
    api = QuestionApi(_choice_question(), hold_answers=False, stale_on_answer=True)
    page, card = _open_card(browser, production_origin, api)
    try:
        card.locator("[data-option-index]").nth(0).click()
        stale = page.locator(
            f'li[id="run-{RUN_ID}"] [data-question-stale][data-question-id="{QUESTION_ID}"]'
        )
        stale.wait_for(timeout=10_000)
        assert "已被处理" in _norm(stale.inner_text())
        page.wait_for_timeout(300)
        assert len(api.posts) == 1, api.posts
        assert api.posts[0]["answer"] == CHOICE_OPTIONS[0]["value"]
        expect(card).to_have_count(0)
    finally:
        page.context.close()

def test_synchronous_double_dispatch_posts_exactly_once(
    browser: Browser, production_origin: str
) -> None:
    """Two clicks dispatched in the same task (mobile double-tap, duplicate
    listener, Replay double mount) must still produce ONE POST.

    React batches state updates for the whole task, so the second handler runs
    with submitting=false; only the synchronous ref/module claim can stop it.
    """
    api = QuestionApi(_choice_question())
    page, card = _open_card(browser, production_origin, api)
    try:
        page.evaluate(
            """() => {
              const button = document.querySelector(
                'article[data-question-id] [data-option-index="2"]',
              );
              if (!button) return;
              button.click();
              button.click();
            }"""
        )
        _wait_for_post(api, page)
        page.wait_for_timeout(300)
        assert len(api.posts) == 1, api.posts
        assert api.posts[0] == {
            "question_id": QUESTION_ID,
            "answer": CHOICE_OPTIONS[1]["value"],
        }
        # the clicked row is the only one marked busy; the rest keep their label
        buttons = card.locator("[data-option-index]")
        assert "提交中…" in _norm(buttons.nth(1).inner_text())
        for index in (0, 2, 3):
            assert "提交中…" not in _norm(buttons.nth(index).inner_text())
        assert len(api.held) == 1
        api.held[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "accepted"}),
        )
        folded = page.locator(
            f'li[id="run-{RUN_ID}"] [data-question-answered][data-question-id="{QUESTION_ID}"]'
        )
        folded.wait_for(timeout=10_000)
        assert CHOICE_OPTIONS[1]["label"] in _norm(folded.inner_text())
    finally:
        page.context.close()
