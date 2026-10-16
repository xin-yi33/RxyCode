"""WEB-W5-C05. A work-branch commit becomes one PR. A read-only token cannot touch main."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
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


def _pkt(data: bytes) -> bytes:
    return f"{len(data) + 4:04x}".encode() + data


class GitHubApi:
    """GitHub pulls API plus smart HTTP for the same sample repo."""

    def __init__(self, *, write: bool) -> None:
        self.write = write
        self.pulls: list[dict[str, object]] = []
        self.posts = 0
        self.seen_auth: list[str] = []
        root = Path(tempfile.mkdtemp(prefix="rxy-c05-remote-"))
        self.bare = str(root / "w5-sample.git")
        seed = root / "seed"
        seed.mkdir()
        _host_git(["init", "-b", "main", str(seed)])
        (seed / "README.md").write_bytes(b"base\n")
        _host_git(["-C", str(seed), "add", "README.md"])
        _host_git(
            [
                "-C",
                str(seed),
                "-c",
                "user.email=c05@example.test",
                "-c",
                "user.name=c05",
                "commit",
                "-m",
                "init",
            ]
        )
        _host_git(["init", "--bare", self.bare])
        _host_git(["-C", str(seed), "push", self.bare, "main"])
        _host_git(["--git-dir", self.bare, "symbolic-ref", "HEAD", "refs/heads/main"])
        server = ThreadingHTTPServer(("0.0.0.0", 0), self._handler())
        self._server = server
        port = server.server_address[1]
        self.url = f"http://127.0.0.1:{port}"
        self.git_url = f"http://host.docker.internal:{port}/rxycode/w5-sample.git"
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()

    def has_branch(self, branch: str) -> bool:
        done = subprocess.run(
            ["git", "--git-dir", self.bare, "rev-parse", "--verify", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return done.returncode == 0

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
        parsed = urlparse(handler.path)
        if parsed.path.endswith("/info/refs"):
            service = parse_qs(parsed.query).get("service", [""])[0]
            binary = "upload-pack" if service == "git-upload-pack" else "receive-pack"
            advertised = subprocess.run(
                ["git", binary, "--advertise-refs", self.bare],
                capture_output=True,
                check=False,
            )
            header = f"# service={service}\n".encode()
            body = _pkt(header) + b"0000" + advertised.stdout
            handler.send_response(200)
            handler.send_header("Content-Type", f"application/x-{service}-advertisement")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return
        self.seen_auth.append(handler.headers.get("Authorization", ""))
        query = parse_qs(parsed.query)
        head = query.get("head", [""])[0]
        found = [row for row in self.pulls if row["head"] == head]
        body = json.dumps(found).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(body)

    def _post(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        raw = handler.rfile.read(int(handler.headers.get("Content-Length", "0")))
        if parsed.path.endswith("/git-upload-pack") or parsed.path.endswith("/git-receive-pack"):
            binary = "upload-pack" if parsed.path.endswith("/git-upload-pack") else "receive-pack"
            packed = subprocess.run(
                ["git", binary, "--stateless-rpc", self.bare],
                input=raw,
                capture_output=True,
                check=False,
            )
            handler.send_response(200)
            handler.send_header("Content-Type", f"application/x-git-{binary}-result")
            handler.send_header("Content-Length", str(len(packed.stdout)))
            handler.end_headers()
            handler.wfile.write(packed.stdout)
            return
        self.posts += 1
        self.seen_auth.append(handler.headers.get("Authorization", ""))
        if not self.write:
            handler.send_response(403)
            handler.send_header("Content-Type", "application/json")
            handler.end_headers()
            handler.wfile.write(b'{"message":"Resource not accessible by integration"}')
            return
        payload = json.loads(raw.decode())
        branch = str(payload["head"]).split(":", 1)[-1]
        if not self.has_branch(branch):
            handler.send_response(422)
            handler.send_header("Content-Type", "application/json")
            handler.end_headers()
            handler.wfile.write(b'{"message":"head branch is not on the remote"}')
            return
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


def _host_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(["git", *args], capture_output=True, text=True, timeout=30, check=False)
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout or "host git failed").strip())
    return done


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
        main_sha = flow.clone_remote(box, api.git_url)
        sha = flow.commit_fix(
            box,
            branch="rxy/fix-sample",
            path="README.md",
            content="fixed\n",
            message="fix sample",
        )
        assert sha != main_sha
        flow.push(box, branch="rxy/fix-sample", remote=api.git_url, journal=journal)
        assert api.has_branch("rxy/fix-sample")
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
        main_sha = flow.clone_remote(box, api.git_url)
        sha = flow.commit_fix(
            box,
            branch="rxy/fix-denied",
            path="README.md",
            content="fixed\n",
            message="fix denied",
        )
        with pytest.raises(ProtectedBranch):
            flow.push(box, branch="main", remote=api.git_url, journal=journal)
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
