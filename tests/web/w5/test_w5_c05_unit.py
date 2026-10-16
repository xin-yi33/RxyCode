"""WEB-W5-C05. A work-branch commit becomes one PR. A read-only token cannot touch main."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

REPO = Path(__file__).resolve().parents[3]
BUN = Path(r"D:\nodejs\node_modules\bun\bin\bun.exe")
for _entry in (
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


class GitHubApi:
    """Minimal GitHub REST stand-in. The shipped client speaks this protocol."""

    def __init__(self, *, write: bool) -> None:
        self.write = write
        self.pulls: list[dict[str, object]] = []
        self.posts = 0
        self.seen_auth: list[str] = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server = server
        self.url = f"http://127.0.0.1:{server.server_address[1]}"
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()

    def _handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner._get(self)

            def do_POST(self) -> None:
                owner._post(self)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        return Handler

    def _get(self, handler: BaseHTTPRequestHandler) -> None:
        self.seen_auth.append(handler.headers.get("Authorization", ""))
        parsed = urlparse(handler.path)
        query = parse_qs(parsed.query)
        head = query.get("head", [""])[0]
        found = [row for row in self.pulls if row["head"] == head]
        body = json.dumps(found).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(body)

    def _post(self, handler: BaseHTTPRequestHandler) -> None:
        self.posts += 1
        self.seen_auth.append(handler.headers.get("Authorization", ""))
        raw = handler.rfile.read(int(handler.headers.get("Content-Length", "0")))
        if not self.write:
            handler.send_response(403)
            handler.send_header("Content-Type", "application/json")
            handler.end_headers()
            handler.wfile.write(b'{"message":"Resource not accessible by integration"}')
            return
        payload = json.loads(raw.decode())
        number = len(self.pulls) + 1
        row = {
            "number": number,
            "html_url": f"https://github.com/rxycode/w5-sample/pull/{number}",
            "state": "open",
            "head": payload["head"],
            "base": payload["base"],
            "title": payload["title"],
            "sha": payload.get("sha", ""),
        }
        self.pulls.append(row)
        handler.send_response(201)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps(row).encode())


def _render(url: str, state: str, error: str) -> str:
    script = (
        "import { createElement } from 'react';\n"
        "import { renderToStaticMarkup } from 'react-dom/server';\n"
        "import { PullRequestPanel } from './src/features/git/PullRequestPanel.tsx';\n"
        "process.stdout.write(renderToStaticMarkup(createElement(PullRequestPanel, {\n"
        "  url: process.env.PR_URL,\n"
        "  state: process.env.PR_STATE,\n"
        "  error: process.env.PR_ERROR,\n"
        "})));\n"
    )
    done = subprocess.run(
        [str(BUN), "-e", script],
        cwd=REPO / "apps" / "web",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, "PR_URL": url, "PR_STATE": state, "PR_ERROR": error},
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_w5_c05_contract() -> None:
    """An authorized fix is committed on a work branch and the same branch has a PR."""
    from rxycode_runner.sandbox.git_workflow import GitWorkflow
    from rxycode_server.integrations.github import GitHubClient, ToolJournal

    secret = "ghp-" + "c" * 24
    journal = ToolJournal()
    flow = GitWorkflow()
    box = flow.open_sandbox(tenant_id="tenant-a")
    api = GitHubApi(write=True)
    try:
        main_sha = flow.seed(box, files={"README.md": "base\n"})
        sha = flow.commit_fix(
            box,
            branch="rxy/fix-sample",
            path="README.md",
            content="fixed\n",
            message="fix sample",
        )
        assert sha != main_sha
        flow.push(box, branch="rxy/fix-sample", journal=journal)
        assert flow.rev(box, "main") == main_sha
        client = GitHubClient(base_url=api.url, token=secret, journal=journal)
        opened = client.publish(
            owner="rxycode",
            repo="w5-sample",
            branch="rxy/fix-sample",
            base="main",
            title="fix sample",
            sha=sha,
            confirm=True,
        )
        found = client.find(owner="rxycode", repo="w5-sample", branch="rxy/fix-sample")
        assert found is not None
        assert found.number == opened.number
        assert found.url == opened.url
        assert found.branch == "rxy/fix-sample"
        assert api.posts == 1
        viewed = _render(opened.url, opened.state, "")
        assert opened.url in viewed
        assert secret not in viewed
        assert secret not in journal.text()
        assert "rxy/fix-sample" in journal.text()
    finally:
        api.close()
        flow.close(box)


def test_w5_c05_negative() -> None:
    """A token without write access is refused, and main is not pushed."""
    from rxycode_runner.sandbox.git_workflow import GitWorkflow, ProtectedBranch
    from rxycode_server.integrations.github import GitHubClient, GitHubRefused, ToolJournal

    secret = "ghp-" + "n" * 24
    journal = ToolJournal()
    flow = GitWorkflow()
    box = flow.open_sandbox(tenant_id="tenant-a")
    api = GitHubApi(write=False)
    try:
        main_sha = flow.seed(box, files={"README.md": "base\n"})
        sha = flow.commit_fix(
            box,
            branch="rxy/fix-denied",
            path="README.md",
            content="fixed\n",
            message="fix denied",
        )
        with pytest.raises(ProtectedBranch):
            flow.push(box, branch="main", journal=journal)
        assert flow.rev(box, "main") == main_sha
        client = GitHubClient(base_url=api.url, token=secret, journal=journal)
        held = client.publish(
            owner="rxycode",
            repo="w5-sample",
            branch="rxy/fix-denied",
            base="main",
            title="needs confirm",
            sha=sha,
            confirm=False,
        )
        assert held.status == "recovery_required"
        assert api.posts == 0
        with pytest.raises(GitHubRefused) as refused:
            client.publish(
                owner="rxycode",
                repo="w5-sample",
                branch="rxy/fix-denied",
                base="main",
                title="fix denied",
                sha=sha,
                confirm=True,
            )
        assert "refused" in str(refused.value).lower()
        assert secret not in str(refused.value)
        assert secret not in journal.text()
        assert flow.rev(box, "main") == main_sha
        panel = _render("", "", "write permission refused")
        assert "write permission refused" in panel
        assert secret not in panel
    finally:
        api.close()
        flow.close(box)
