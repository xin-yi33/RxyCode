"""WEB-W5-C05. Retrying the same branch reuses the pull request."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from tests.web.w5.test_w5_c05_unit import GitHubApi


def test_w5_c05_integration() -> None:
    """A second publish of the same branch returns the existing PR and does not POST again."""
    from rxycode_runner.sandbox.git_workflow import GitWorkflow
    from rxycode_server.integrations.github import GitHubClient, ToolJournal

    secret = "ghp-" + "i" * 24
    journal = ToolJournal()
    flow = GitWorkflow()
    box = flow.open_sandbox(tenant_id="tenant-a")
    api = GitHubApi(write=True)
    try:
        flow.clone_remote(box, api.git_url)
        sha = flow.commit_fix(
            box,
            branch="rxy/fix-retry",
            path="README.md",
            content="fixed\n",
            message="fix retry",
        )
        flow.push(box, branch="rxy/fix-retry", remote=api.git_url, journal=journal)
        assert api.has_branch("rxy/fix-retry")
        client = GitHubClient(base_url=api.url, token=secret, journal=journal)
        kwargs = {
            "owner": "rxycode",
            "repo": "w5-sample",
            "branch": "rxy/fix-retry",
            "base": "main",
            "title": "fix retry",
            "sha": sha,
            "confirm": True,
        }
        first = client.publish(**kwargs)
        second = client.publish(**kwargs)
        assert second.number == first.number
        assert second.url == first.url
        assert second.status == "existing"
        assert api.posts == 1
        assert secret not in journal.text()
    finally:
        api.close()
        flow.close(box)
