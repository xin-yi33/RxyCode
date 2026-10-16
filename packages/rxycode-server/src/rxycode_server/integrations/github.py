"""GitHub pull requests. The token is an Authorization header and nothing else."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal, new_attempt_id


class GitHubRefused(PermissionError):
    """The token cannot write the pull request."""

    def __init__(self) -> None:
        super().__init__("write permission refused")


@dataclass(frozen=True)
class PublishResult:
    number: int | None
    url: str
    state: str
    branch: str
    status: str


class ToolJournal:
    """Remote writes reserve the on-disk tool journal before they run."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or Path(tempfile.mkdtemp(prefix="rxy-tool-journal-"))
        self._store = ToolExecutionJournal(self.directory)
        self.attempt_id = new_attempt_id()
        self._binding = self._store.binding(self.attempt_id)

    def reserve_remote(self, **fields: object) -> object:
        payload = {key: str(value) for key, value in fields.items()}
        call = self._binding.next_call(payload.get("action", "remote"), payload)
        reservation = self._store.reserve(self.attempt_id, call)
        if reservation.action != "execute":
            raise RuntimeError("journal blocked the remote write")
        return call

    def complete_remote(self, call: object, result: str) -> None:
        self._store.complete(self.attempt_id, call, result)

    def text(self) -> str:
        parts = [path.read_text(encoding="utf-8") for path in sorted(self.directory.glob("att_*.json"))]
        return "\n".join(parts)


class GitHubClient:
    def __init__(self, *, base_url: str, token: str, journal: ToolJournal) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._journal = journal

    def publish(
        self,
        *,
        owner: str,
        repo: str,
        branch: str,
        base: str,
        title: str,
        sha: str,
        confirm: bool,
    ) -> PublishResult:
        if not confirm:
            call = self._journal.reserve_remote(
                action="pull_request.hold",
                repo=f"{owner}/{repo}",
                branch=branch,
                sha=sha,
                status="recovery_required",
            )
            self._journal.complete_remote(call, "recovery_required")
            return PublishResult(None, "", "", branch, "recovery_required")
        found = self.find(owner=owner, repo=repo, branch=branch)
        if found is not None:
            return PublishResult(found.number, found.url, found.state, found.branch, "existing")
        call = self._journal.reserve_remote(
            action="pull_request.create",
            repo=f"{owner}/{repo}",
            branch=branch,
            sha=sha,
            status="opened",
        )
        response = self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json={
                "title": title,
                "head": f"{owner}:{branch}",
                "base": base,
                "sha": sha,
                "body": title,
            },
        )
        if response.status_code == 403:
            raise GitHubRefused()
        if response.status_code >= 400:
            raise GitHubRefused()
        result = self._result(response.json(), "opened")
        self._journal.complete_remote(call, f"pr {result.number}")
        return result

    def find(self, *, owner: str, repo: str, branch: str) -> PublishResult | None:
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={"head": f"{owner}:{branch}", "state": "open"},
        )
        if response.status_code >= 400:
            raise GitHubRefused()
        rows = response.json()
        if not rows:
            return None
        return self._result(rows[0], "open")

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json"}
        with httpx.Client(base_url=self._base, timeout=10, follow_redirects=False) as client:
            return client.request(method, path, headers=headers, **kwargs)

    def _result(self, row: dict[str, object], status: str) -> PublishResult:
        head = row.get("head", "")
        if isinstance(head, dict):
            branch = str(head.get("ref", ""))
        else:
            branch = str(head).split(":", 1)[-1]
        number = row.get("number")
        return PublishResult(
            number=int(number) if number is not None else None,
            url=str(row.get("html_url", "")),
            state=str(row.get("state", "")),
            branch=branch,
            status=status,
        )
