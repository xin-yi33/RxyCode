"""WEB-W1-C02. Concurrent tool calls keep their own RunContext."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tarfile
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-protocol" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _auth(tenant: str, target: str) -> dict[str, str]:
    return {
        "tenant_id": tenant,
        "actor_id": "actor-1",
        "project_id": "project-1",
        "session_id": "client-session",
        "target_id": target,
        "permission_profile": "default",
        "deadline_at": "2026-10-16T00:00:00Z",
        "trace_id": f"trace-{tenant}",
    }


async def test_w1_c02_integration():
    """Two concurrent ToolOrchestrator calls do not swap tenant or target."""
    from langchain_core.tools import StructuredTool

    from appserver.runtime import bind_prompt_context, current_run_context, reset_prompt_context
    from execution.tool_orchestrator import ToolOrchestrator
    from rxycode_protocol.run_context import RunContext

    async def echo() -> str:
        context = current_run_context()
        assert context is not None
        return f"{context.tenant_id}|{context.target_id}"

    orchestrator = ToolOrchestrator()
    orchestrator.register(
        "echo",
        StructuredTool.from_function(coroutine=echo, name="echo", description="read run scope"),
    )

    async def once(tenant: str, target: str) -> str:
        context = RunContext.from_authenticated(_auth(tenant, target))
        tokens = bind_prompt_context("ses-c02", None, run_context=context)
        try:
            return await orchestrator.execute_tool(
                "echo",
                {},
                config={"safety": {"enabled": False}},
            )
        finally:
            reset_prompt_context(tokens)

    left, right = await asyncio.gather(
        once("tenant-a", "target-a"),
        once("tenant-b", "target-b"),
    )
    assert left == "tenant-a|target-a"
    assert right == "tenant-b|target-b"


def _python(env_dir: Path) -> Path:
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def test_w1_c02_installed_open_run(tmp_path: Path):
    """An installed wheel imports rxycode_protocol without the checkout src path."""
    archive = tmp_path / "head.tar"
    archived = subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), "HEAD"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )
    assert archived.returncode == 0, archived.stderr
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    with tarfile.open(archive) as bundle:
        if sys.version_info >= (3, 12):
            bundle.extractall(checkout, filter="data")
        else:
            bundle.extractall(checkout)
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(wheel_dir), str(checkout)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert build.returncode == 0, build.stderr
    wheels = list(wheel_dir.glob("rxycode-*.whl"))
    assert len(wheels) == 1
    env_dir = tmp_path / "venv"
    venv.create(env_dir, with_pip=True, system_site_packages=True)
    python = _python(env_dir)
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert install.returncode == 0, install.stderr
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "from pathlib import Path\n"
            "import rxycode_protocol.run_context as run_context\n"
            "from RxyCode.RxyCode1_1_0.core.session import Session\n"
            "session = Session(session_id='ses-installed', workspace_root='.', emit=lambda _n: None)\n"
            "context = session.open_run({\n"
            " 'tenant_id': 'tenant-real', 'actor_id': 'actor', 'project_id': 'project',\n"
            " 'session_id': 'forged', 'target_id': 'target', 'permission_profile': 'default',\n"
            " 'deadline_at': 'none', 'trace_id': 'trace'})\n"
            "assert context.session_id == 'ses-installed'\n"
            "assert context.tenant_id == 'tenant-real'\n"
            "print(Path(run_context.__file__).resolve())\n"
            "print(Path(session.__class__.__module__ and __import__('RxyCode.RxyCode1_1_0.core.session', fromlist=['Session']).__file__).resolve())\n"
            "print('installed-run-ok')\n",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert probe.returncode == 0, probe.stderr
    assert "installed-run-ok" in probe.stdout
    venv_root = str(env_dir.resolve()).casefold()
    repo_root = str(REPO.resolve()).casefold()
    origins = [line.strip() for line in probe.stdout.splitlines() if line.strip() and line.strip() != "installed-run-ok"]
    assert len(origins) == 2
    for origin in origins:
        folded = origin.casefold()
        assert venv_root in folded
        assert repo_root not in folded
