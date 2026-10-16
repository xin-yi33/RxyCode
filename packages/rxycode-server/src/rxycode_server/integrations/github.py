"""GitHub pull requests. The token is an Authorization header and nothing else."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx


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
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []

    def record(self, **fields: object) -> None:
        self.rows.append({key: str(value) for key, value in fields.items()})

    def text(self) -> str:
        return json.dumps(self.rows)


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
            self._note("pull_request.hold", owner, repo, branch, sha, "recovery_required")
            return PublishResult(None, "", "", branch, "recovery_required")
        found = self.find(owner=owner, repo=repo, branch=branch)
        if found is not None:
            return PublishResult(found.number, found.url, found.state, found.branch, "existing")
        self._note("pull_request.create", owner, repo, branch, sha, "opened")
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
        return self._result(response.json(), "opened")

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

    def _note(self, action: str, owner: str, repo: str, branch: str, sha: str, status: str) -> None:
        self._journal.record(
            action=action,
            repo=f"{owner}/{repo}",
            branch=branch,
            sha=sha,
            status=status,
        )

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
