"""Self-audit: hunt for problems the first audit round did not list.

Each test encodes a property the user cares about ("保持持久状态，但复用原执行
保护；诊断如实反映执行结果和文件版本") and checks it adversarially.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps

WINDOWS = os.name == "nt"
pytestmark = pytest.mark.asyncio


def show(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'PROBLEM'}] {name}" + (f" :: {detail}" if detail else ""))


@pytest.fixture(autouse=True)
async def _clean():
    try:
        await ps.release_all()
        yield
        await ps.release_all()
    finally:
        try:
            await ps.release_all()
        except Exception:
            pass


class TestShellStateEdgeCases:
    async def test_venv_activation_affects_python(self):
        """A venv activated in one call must govern python in the next."""
        base = Path(os.getcwd()) / f"_venvprobe_{os.getpid()}"
        try:
            if WINDOWS:
                await ps.release_all()
                sh = await ps.acquire_shell(identity="venv", cwd=os.getcwd())
                r = await sh.run(f"python -m venv '{base}'", timeout=180)
                show("venv created", base.is_dir(), f"rc={r.exit_code}")
                if not base.is_dir():
                    pytest.skip("venv creation unavailable")
                act = base / "Scripts" / "Activate.ps1"
                await sh.run(f"& '{act}'", timeout=60)
                probe = await sh.run(
                    "python -c \"import sys; print(sys.prefix)\"", timeout=60
                )
                prefix = probe.stdout.strip()
                show(
                    "python -c uses the venv prefix after activation",
                    str(base).lower() in prefix.lower(),
                    f"prefix={prefix[:80]}",
                )
                assert str(base).lower() in prefix.lower(), (
                    "activation must govern python -c (the audit's venv trap)"
                )
        finally:
            import shutil

            shutil.rmtree(base, ignore_errors=True)

    async def test_function_survives_and_runs(self):
        sh = await ps.acquire_shell(identity="fn", cwd=os.getcwd())
        if WINDOWS:
            await sh.run("function rxy_probe_fn { 'fn-result' }", timeout=30)
            r = await sh.run("rxy_probe_fn", timeout=30)
        else:
            await sh.run("rxy_probe_fn() { echo fn-result; }", timeout=30)
            r = await sh.run("rxy_probe_fn", timeout=30)
        show("function persists", "fn-result" in r.stdout, repr(r.stdout.strip()[:40]))
        assert "fn-result" in r.stdout

    async def test_unset_variable_stays_unset(self):
        sh = await ps.acquire_shell(identity="unset", cwd=os.getcwd())
        if WINDOWS:
            await sh.run("$u = 'x'; Remove-Variable u", timeout=30)
            r = await sh.run('Write-Output "[$u]"', timeout=30)
        else:
            await sh.run("u=x; unset u", timeout=30)
            r = await sh.run('echo "[$u]"', timeout=30)
        show("unset persists", r.stdout.strip() == "[]", repr(r.stdout.strip()))
        assert r.stdout.strip() == "[]"

    async def test_large_output_is_bounded_and_flagged(self):
        """Output beyond the cap must be cut AND the truncation reported."""
        sh = await ps.acquire_shell(identity="big", cwd=os.getcwd())
        if WINDOWS:
            # ~6 MB of output, comfortably past one capture preview window.
            cmd = "1..60000 | ForEach-Object { 'x' * 100 }"
        else:
            cmd = "for i in $(seq 1 60000); do printf 'x%.0s' $(seq 1 100); echo; done"

        # Audit P2-04 changed the contract: raw output streams straight into
        # the shared bounded capture, so the ARTIFACT holds the full output and
        # the MODEL-facing preview is what gets truncated.  The shell must not
        # pre-truncate and hand a maimed copy to the capture.
        from RxyCode.RxyCode1_1_0.utils.shell import BoundedOutputCapture

        capture = BoundedOutputCapture()
        await sh.run(cmd, timeout=180, capture=capture)
        capture.end_stream("stdout")
        capture.end_stream("stderr")
        finished = capture.finish()
        total = int(finished.get("stdout_bytes") or 0)
        print(f"\n  captured_bytes={total} artifact={finished.get('stdout_artifact')}")
        show(
            "large output captured without shell-side truncation",
            total > ps.MAX_CAPTURE_BYTES,
            f"total={total} preview_truncated={finished.get('stdout_truncated')}",
        )
        assert total > ps.MAX_CAPTURE_BYTES, (
            "the capture must receive the complete stream, not a capped copy"
        )
        assert finished.get("stdout_truncated") is True or finished.get(
            "stdout_artifact"
        ), "a large preview must be truncated and/or spill to an artifact"

    async def test_rapid_sequential_commands_do_not_interleave(self):
        sh = await ps.acquire_shell(identity="seq", cwd=os.getcwd())
        for i in range(15):
            if WINDOWS:
                r = await sh.run(f"Write-Output 'seq{i}'", timeout=20)
            else:
                r = await sh.run(f"echo seq{i}", timeout=20)
            assert f"seq{i}" in r.stdout, f"iteration {i}: {r.stdout!r}"
        show("15 sequential commands all correct", True)


class TestCancelEdgeCases:
    async def test_cancel_then_state_reported_lost(self):
        sh = await ps.acquire_shell(identity="c1", cwd=os.getcwd())
        if WINDOWS:
            await sh.run("$keepme = 'alive'", timeout=20)
            task = asyncio.create_task(sh.run("Start-Sleep -Seconds 10", timeout=60))
        else:
            await sh.run("keepme=alive", timeout=20)
            task = asyncio.create_task(sh.run("sleep 10", timeout=60))
        await asyncio.sleep(0.4)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, ps.ShellLostError):
            pass
        show("shell is closed after cancel", not sh.alive, f"alive={sh.alive}")
        assert not sh.alive

    async def test_timeout_reports_lost_state(self):
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash_async

        await ps.release_all()
        cmd = "Start-Sleep -Seconds 30" if WINDOWS else "sleep 30"
        out = await run_bash_async(cmd, "", "", 2)
        show(
            "timeout explains state loss",
            "environment was lost" in out or "lost" in out,
            out.strip()[:120],
        )
        assert "lost" in out.lower()
        assert ps.active_identities() == [] or not ps._SHELLS

    async def test_background_output_does_not_leak_into_next_command(self):
        """A background job's output must not appear in the following result."""
        await ps.release_all()
        sh = await ps.acquire_shell(identity="bg", cwd=os.getcwd())
        if WINDOWS:
            await sh.run(
                "Start-Job { Start-Sleep -Seconds 5; 'BG-MARKER' } | Out-Null",
                timeout=30,
            )
            r = await sh.run("Write-Output 'foreground-only'", timeout=30)
        else:
            await sh.run("(sleep 5; echo BG-MARKER) &", timeout=20)
            r = await sh.run("echo foreground-only", timeout=30)
        show(
            "background output stays out of the next command",
            "BG-MARKER" not in r.stdout,
            repr(r.stdout.strip()[:80]),
        )
        assert "BG-MARKER" not in r.stdout


class TestConcurrencyEdgeCases:
    async def test_parallel_isolated_sessions(self):
        a = await ps.acquire_shell(identity="p1::iso", cwd=os.getcwd())
        b = await ps.acquire_shell(identity="p2::iso", cwd=os.getcwd())
        if WINDOWS:
            await a.run("$v = 'A'", timeout=20)
            await b.run("$v = 'B'", timeout=20)
            ra = await a.run("Write-Output $v", timeout=20)
            rb = await b.run("Write-Output $v", timeout=20)
        else:
            await a.run("v=A", timeout=20)
            await b.run("v=B", timeout=20)
            ra = await a.run("echo $v", timeout=20)
            rb = await b.run("echo $v", timeout=20)
        show("isolated sessions keep their own vars", ra.stdout.strip() == "A" and rb.stdout.strip() == "B")
        assert ra.stdout.strip() == "A"
        assert rb.stdout.strip() == "B"

    async def test_release_for_session_scoped(self):
        await ps.release_all()
        await ps.acquire_shell(identity="s1", cwd=os.getcwd())
        await ps.acquire_shell(identity="s1::iso", cwd=os.getcwd())
        await ps.acquire_shell(identity="s2", cwd=os.getcwd())
        n = await ps.release_for_session("s1")
        remaining = ps.active_identities()
        show("release_for_session removes only its own", n == 2 and remaining == ["s2"], f"released={n} remaining={remaining}")
        assert n == 2
        assert remaining == ["s2"]
