"""Branch, commit, and push inside a sandbox. Protected main is not pushed."""

from __future__ import annotations

import subprocess
import uuid

from rxycode_runner.sandbox.gvisor import docker_executable

_PROTECTED = {"main", "master"}


class ProtectedBranch(PermissionError):
    """main and master are not push targets."""

    def __init__(self, branch: str) -> None:
        self.branch = branch
        super().__init__(f"protected branch refused: {branch}")


class SandboxRepo:
    def __init__(self, name: str, tenant_id: str) -> None:
        self.name = name
        self.tenant_id = tenant_id


class GitWorkflow:
    def open_sandbox(self, *, tenant_id: str) -> SandboxRepo:
        name = "rxy-git-" + uuid.uuid4().hex[:12]
        docker = docker_executable()
        created = _run(
            docker,
            [
                "create",
                "--name",
                name,
                "--entrypoint",
                "sleep",
                "--user",
                "65534:65534",
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--label",
                f"rxy.tenant={tenant_id}",
                "--workdir",
                "/tmp",
                "alpine/git",
                "infinity",
            ],
        )
        if created.returncode != 0:
            raise RuntimeError((created.stderr or "git sandbox create failed").strip())
        if _run(docker, ["start", name]).returncode != 0:
            _run(docker, ["rm", "-f", name])
            raise RuntimeError("git sandbox failed to start")
        return SandboxRepo(name, tenant_id)

    def seed(self, box: SandboxRepo, *, files: dict[str, str]) -> str:
        _git(box, ["init", "-b", "main", "/tmp/ws"])
        for path, content in files.items():
            _write(box, f"/tmp/ws/{path}", content)
        _git(box, ["-C", "/tmp/ws", "add", "."])
        _git(
            box,
            [
                "-C",
                "/tmp/ws",
                "-c",
                "user.email=c05@example.test",
                "-c",
                "user.name=c05",
                "commit",
                "-m",
                "init",
            ],
        )
        _git(box, ["init", "--bare", "/tmp/remote.git"])
        _git(box, ["-C", "/tmp/ws", "push", "/tmp/remote.git", "main"])
        return self.rev(box, "main")

    def commit_fix(
        self,
        box: SandboxRepo,
        *,
        branch: str,
        path: str,
        content: str,
        message: str,
    ) -> str:
        if branch in _PROTECTED:
            raise ProtectedBranch(branch)
        _git(box, ["-C", "/tmp/ws", "checkout", "-b", branch])
        _write(box, f"/tmp/ws/{path}", content)
        _git(box, ["-C", "/tmp/ws", "add", path])
        _git(
            box,
            [
                "-C",
                "/tmp/ws",
                "-c",
                "user.email=c05@example.test",
                "-c",
                "user.name=c05",
                "commit",
                "-m",
                message,
            ],
        )
        return self.rev(box, "HEAD")

    def push(self, box: SandboxRepo, *, branch: str, journal: object) -> None:
        if branch in _PROTECTED:
            raise ProtectedBranch(branch)
        record = getattr(journal, "record", None)
        if callable(record):
            record(action="git.push", branch=branch, remote="sandbox")
        _git(box, ["-C", "/tmp/ws", "push", "/tmp/remote.git", branch])

    def rev(self, box: SandboxRepo, ref: str) -> str:
        done = _git(box, ["-C", "/tmp/ws", "rev-parse", ref])
        return done.stdout.strip()

    def close(self, box: SandboxRepo) -> None:
        _run(docker_executable(), ["rm", "-f", box.name])


def _write(box: SandboxRepo, path: str, content: str) -> None:
    done = subprocess.run(
        [docker_executable(), "exec", "-i", box.name, "sh", "-c", f"cat > {path}"],
        input=content,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError((done.stderr or "write failed").strip())


def _git(box: SandboxRepo, args: list[str]) -> subprocess.CompletedProcess[str]:
    done = _run(docker_executable(), ["exec", box.name, "git", *args])
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout or "git failed").strip())
    return done


def _run(docker: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [docker, *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
