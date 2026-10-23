"""Checkout and cleanup inside a sandbox. The API host does not run git."""

from __future__ import annotations

import base64
import subprocess
import uuid

from rxycode_runner.sandbox.gvisor import docker_executable
from rxycode_runner.sandbox.provider import SandboxHandle

_TREE = (
    "import base64, os, sys\n"
    "root = '/tmp/ws'\n"
    "chunks = []\n"
    "for dirpath, dirs, files in os.walk(root):\n"
    "    dirs[:] = [name for name in sorted(dirs) if name != '.git']\n"
    "    for name in sorted(files):\n"
    "        path = os.path.join(dirpath, name)\n"
    "        rel = os.path.relpath(path, root).replace('\\\\', '/')\n"
    "        data = open(path, 'rb').read()\n"
    "        chunks.append(rel.encode() + b'\\0' + data + b'\\0')\n"
    "sys.stdout.write(base64.b64encode(b''.join(chunks)).decode())\n"
)


class CheckoutFailed(RuntimeError):
    """The sandbox git checkout did not land on the requested revision."""


def prepare_checkout(*, url: str, revision: str) -> str:
    """Clone the requested URL and detach HEAD inside a git sandbox."""
    docker = docker_executable()
    git_name = "rxy-git-" + uuid.uuid4().hex[:12]
    try:
        created = _run(
            docker,
            [
                "create",
                "--name",
                git_name,
                "--entrypoint",
                "sleep",
                "--user",
                "65534:65534",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--workdir",
                "/tmp",
                "alpine/git",
                "infinity",
            ],
        )
        if created.returncode != 0:
            detail = created.stderr or created.stdout or "git sandbox create failed"
            raise CheckoutFailed(detail.strip())
        if _run(docker, ["start", git_name]).returncode != 0:
            raise CheckoutFailed("git sandbox failed to start")
        cloned = _exec(docker, git_name, ["git", "clone", "--quiet", url, "/tmp/ws"])
        if cloned.returncode != 0:
            raise CheckoutFailed((cloned.stderr or "git clone failed").strip())
        checked = _exec(
            docker,
            git_name,
            ["git", "-C", "/tmp/ws", "checkout", "--detach", revision],
        )
        if checked.returncode != 0:
            raise CheckoutFailed((checked.stderr or "git checkout failed").strip())
        head = _exec(docker, git_name, ["git", "-C", "/tmp/ws", "rev-parse", "HEAD"])
        if head.returncode != 0 or head.stdout.strip() != revision:
            raise CheckoutFailed("sandbox revision does not match")
        marked = _exec(
            docker,
            git_name,
            [
                "sh",
                "-c",
                "git -C /tmp/ws status --porcelain > /tmp/clean-status && "
                "git -C /tmp/ws rev-parse HEAD > /tmp/ws/.revision && "
                "cp /tmp/clean-status /tmp/ws/.porcelain && "
                "git -C /tmp/ws rev-parse --abbrev-ref HEAD > /tmp/ws/.branch",
            ],
        )
        if marked.returncode != 0:
            raise CheckoutFailed((marked.stderr or "git status failed").strip())
        return git_name
    except Exception:
        _run(docker, ["rm", "-f", git_name])
        raise


def adopt_checkout(handle: SandboxHandle, git_name: str) -> None:
    """Copy the checked-out tree into the tenant sandbox. Does not run host git."""
    docker = docker_executable()
    made = _exec(
        docker,
        handle.sandbox_id,
        ["python", "-c", "import os; os.makedirs('/tmp/ws', exist_ok=True)"],
    )
    if made.returncode != 0:
        raise CheckoutFailed((made.stderr or "workspace dir failed").strip())
    source = subprocess.Popen(
        [docker, "exec", git_name, "tar", "-C", "/tmp/ws", "-cf", "-", "."],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert source.stdout is not None
    dest = subprocess.run(
        [docker, "exec", "-i", handle.sandbox_id, "tar", "-C", "/tmp/ws", "-xf", "-"],
        stdin=source.stdout,
        capture_output=True,
        timeout=60,
        check=False,
    )
    source.stdout.close()
    err = source.stderr.read() if source.stderr is not None else b""
    code = source.wait(timeout=60)
    if code != 0 or dest.returncode != 0:
        detail = (dest.stderr or err or b"workspace copy failed").decode("utf-8", "replace")
        raise CheckoutFailed(detail.strip())


def discard_checkout(git_name: str) -> None:
    _run(docker_executable(), ["rm", "-f", git_name])


def run_in_workspace(handle: SandboxHandle, argv: list[str]) -> tuple[int, str, str]:
    done = _exec(docker_executable(), handle.sandbox_id, argv)
    return done.returncode, done.stdout, done.stderr


_CHECK = (
    "from pathlib import Path\n"
    "files = [p for p in Path('/tmp/ws').rglob('*') if p.is_file()]\n"
    "files = [p for p in files if '.git' not in p.parts and not p.name.startswith('.')]\n"
    "files.sort()\n"
    "print(files[0].read_text(encoding='utf-8') if files else '')\n"
    "print('sample-ok')\n"
)


def run_tree_check(handle: SandboxHandle) -> tuple[int, str, str]:
    return run_in_workspace(handle, ["python", "-c", _CHECK])


def tree_bytes(handle: SandboxHandle) -> bytes:
    code, out, err = run_in_workspace(handle, ["python", "-c", _TREE])
    if code != 0:
        raise CheckoutFailed((err or "tree archive failed").strip())
    return base64.b64decode(out.strip())


def _exec(docker: str, name: str, argv: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(docker, ["exec", name, *argv])


def _run(docker: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [docker, *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
