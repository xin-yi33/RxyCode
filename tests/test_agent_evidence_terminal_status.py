"""Tool-boundary evidence is authoritative over optimistic model prose."""

import pytest


@pytest.mark.asyncio
async def test_failed_tool_evidence_overrides_optimistic_final_answer():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.log.monitor import run_monitor

    agent = object.__new__(AgentV2)

    async def optimistic_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "bash",
            {"command": "failing-command"},
            "[error] command failed",
            executed=True,
            approval="approved",
        )
        return "Task completed successfully"

    agent._run_impl = optimistic_run
    result = await agent.run("do the work")

    assert result.startswith("[evidence failed:")
    assert "Task completed successfully" not in result
    assert agent._last_evidence[0]["status"] == "failed"
    snapshot = run_monitor.snapshot()
    assert snapshot["status_counts"] == {"failed": 1}
    assert snapshot["tool_evidence"] == {"total": 1, "failed": 1}


@pytest.mark.asyncio
async def test_failed_version_probe_bash_does_not_override_completed_answer(tmp_path):
    """A Windows ``python3 --version`` miss is a READ environment probe.

    T01 previously died with ``[evidence failed: Tool bash did not complete:
    failed]`` after the agent had already written a playable game, because
    ``2>&1`` kept the probe at WRITE and the terminal evidence gate treated
    exit 1 as authoritative.
    """
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel, classify_tool_risk
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    command = (
        'node --version 2>&1; echo "---"; python --version 2>&1; '
        'echo "---"; python3 --version 2>&1'
    )
    assert classify_tool_risk("bash", {"command": command}) == RiskLevel.READ

    artifact = tmp_path / "index.html"
    artifact.write_text("<html><body>ok</body></html>", encoding="utf-8")
    agent = object.__new__(AgentV2)

    async def completed_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "bash",
            {"command": command, "description": "Check available runtimes"},
            "[error executing bash: v24.18.0\r\n---\r\nPython 3.13.9\r\n---\r\n\n[exit code: 1]]",
            executed=True,
            approval="auto",
            risk=RiskLevel.READ,
        )
        ToolOrchestrator()._finish(
            "write",
            {"filePath": str(artifact), "content": artifact.read_text(encoding="utf-8")},
            f"[wrote {artifact.stat().st_size} bytes to {artifact}]",
            executed=True,
            approval="auto",
            risk=RiskLevel.WRITE,
        )
        return "T01-runner is playable. Files: index.html, styles.css, game.js, README.md."

    agent._run_impl = completed_run
    result = await agent.run("Create T01-runner in the current workspace")

    assert result.startswith("T01-runner is playable")
    assert "evidence failed" not in result


@pytest.mark.asyncio
async def test_failed_pip_show_probe_does_not_block_later_write(tmp_path):
    """Windows ``pip show | grep`` is an env probe; it must not abort /solo
    before named source files are written."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel, classify_tool_risk
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    command = (
        'python3 --version && pip show fastapi passlib pyjwt httpx pytest bcrypt '
        '2>&1 | grep -E "^(Name|Version)"'
    )
    assert classify_tool_risk("bash", {"command": command}) == RiskLevel.READ

    artifact = tmp_path / "auth"
    artifact.mkdir()
    passwords = artifact / "passwords.py"
    passwords.write_text("def hash_password(p): return p\n", encoding="utf-8")
    agent = object.__new__(AgentV2)

    async def completed_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "bash",
            {"command": command},
            "[error executing bash: grep : CommandNotFoundException\n[exit code: 1]]",
            executed=True,
            approval="auto",
            risk=RiskLevel.READ,
        )
        ToolOrchestrator()._finish(
            "write",
            {"filePath": str(passwords), "content": passwords.read_text(encoding="utf-8")},
            f"[wrote {passwords.stat().st_size} bytes to {passwords}]",
            executed=True,
            approval="auto",
            risk=RiskLevel.WRITE,
        )
        return "auth/passwords.py written with stdlib hashing."

    agent._run_impl = completed_run
    result = await agent.run(
        "/solo 实现 POST /login。必须落地 auth/passwords.py、auth/routes.py、tests/test_login.py。"
    )
    assert "auth/passwords.py" in result
    assert "evidence failed" not in result


@pytest.mark.asyncio
async def test_failed_bash_smoke_test_does_not_override_written_artifact(tmp_path):
    """A later ``node smoke-test.mjs`` exit 1 must not discard files already written.

    T01 wrote a complete runner game, then a 18/19 smoke check failed on
    localStorage. The evidence gate used to replace the Final Answer with
    ``[evidence failed: Tool bash did not complete: failed]``.
    """
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    artifact = tmp_path / "index.html"
    artifact.write_text("<html><body>ok</body></html>", encoding="utf-8")
    agent = object.__new__(AgentV2)

    async def completed_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "write",
            {"filePath": str(artifact), "content": artifact.read_text(encoding="utf-8")},
            f"[wrote {artifact.stat().st_size} bytes to {artifact}]",
            executed=True,
            approval="auto",
            risk=RiskLevel.WRITE,
        )
        ToolOrchestrator()._finish(
            "bash",
            {"command": "node .\\smoke-test.mjs", "workdir": str(tmp_path)},
            "[error executing bash: FAIL  localStorage 写入最高分\n=== 结果: 18/19 通过 ===\n[exit code: 1]]",
            executed=True,
            approval="approved",
            risk=RiskLevel.WRITE,
        )
        return "T01-runner is playable. Smoke: 18/19. localStorage probe unavailable in Node."

    agent._run_impl = completed_run
    result = await agent.run("Create T01-runner in the current workspace")

    assert result.startswith("T01-runner is playable")
    assert "evidence failed" not in result


@pytest.mark.asyncio
async def test_read_only_probe_failure_does_not_override_completed_answer():
    """A failed read-only probe (webfetch/websearch) must not discard a fully
    completed answer. Research fetches are attempts — the model may retry with
    another source. Only critical (WRITE/DANGER or artifact) failures override.
    """
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    agent = object.__new__(AgentV2)

    async def completed_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "webfetch",
            {"url": "https://example.com/404", "format": "text"},
            "[error fetching https://example.com/404: Client error '404 Not Found' for url]",
            executed=True,
            approval="approved",
            risk=RiskLevel.READ,
        )
        return "2026 年 AI 编程助手的三大趋势：Agentic 编码、上下文工程、安全治理。"

    agent._run_impl = completed_run
    result = await agent.run("搜索 2026 AI 编程助手趋势")

    assert result.startswith("2026 年 AI 编程助手")
    assert "evidence failed" not in result


@pytest.mark.asyncio
async def test_write_failure_still_overrides_even_with_read_probe_failure():
    """A WRITE-level failure must still override, even when a read-only probe
    also failed in the same run."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    agent = object.__new__(AgentV2)

    async def mixed_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "webfetch",
            {"url": "https://example.com/404", "format": "text"},
            "[error fetching https://example.com/404: 404]",
            executed=True,
            approval="approved",
            risk=RiskLevel.READ,
        )
        ToolOrchestrator()._finish(
            "bash",
            {"command": "python script.py"},
            "[error] script crashed",
            executed=True,
            approval="approved",
            risk=RiskLevel.WRITE,
        )
        return "claiming success despite failure"

    agent._run_impl = mixed_run
    result = await agent.run("do the work")

    assert result.startswith("[evidence failed:")
    assert "claiming success" not in result


@pytest.mark.asyncio
async def test_tool_timeout_does_not_override_recovered_answer(tmp_path):
    """A bash hard-timeout is a controlled runtime outcome; if the agent
    recovers and documents it, evidence must not discard the answer."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    agent = object.__new__(AgentV2)
    note = tmp_path / "timeout_note.md"
    note.write_text("timed out as expected", encoding="utf-8")

    async def recovered_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "bash",
            {"command": "python -c \"import time; time.sleep(600)\""},
            "[error: tool 'bash' timed out after 45s]",
            executed=True,
            approval="approved",
            risk=RiskLevel.WRITE,
        )
        ToolOrchestrator()._finish(
            "write",
            {"filePath": str(note), "content": "timed out as expected"},
            f"[wrote 20 bytes to {note}]",
            executed=True,
            approval="approved",
            risk=RiskLevel.WRITE,
        )
        return "超时发生：bash 在 45s 被终止，已写入 timeout_note.md。"

    agent._run_impl = recovered_run
    result = await agent.run("观察长 sleep 超时")

    assert "超时发生" in result
    assert "evidence failed" not in result


@pytest.mark.asyncio
async def test_shell_timeout_after_format_does_not_override_written_artifact(tmp_path):
    """Windows bash records '[timeout after 60s]', not 'timed out after'."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    agent = object.__new__(AgentV2)
    game = tmp_path / "game.js"
    game.write_text("console.log('ok')", encoding="utf-8")

    async def recovered_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "write",
            {"filePath": str(game), "content": "console.log('ok')"},
            f"[wrote 18 bytes to {game}]",
            executed=True,
            approval="approved",
            risk=RiskLevel.WRITE,
        )
        ToolOrchestrator()._finish(
            "bash",
            {"command": "python T01-runner\\\\_check_html.py"},
            "[error executing bash: [timeout after 60s]\n[exit code: -1]]",
            executed=True,
            approval="approved",
            risk=RiskLevel.WRITE,
        )
        return "game.js written; HTML parser timed out and was skipped."

    agent._run_impl = recovered_run
    result = await agent.run("create the runner")

    assert "game.js written" in result
    assert "evidence failed" not in result


@pytest.mark.asyncio
async def test_helper_write_bracket_mismatch_does_not_override_game_files(tmp_path):
    """A _smoke.js bracket warning must not discard an already written game."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    agent = object.__new__(AgentV2)
    game = tmp_path / "game.js"
    smoke = tmp_path / "_smoke.js"
    game.write_text("console.log('ok')", encoding="utf-8")
    smoke.write_text("console.log('smoke')", encoding="utf-8")

    async def recovered_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "write",
            {"filePath": str(game), "content": "console.log('ok')"},
            f"[wrote 18 bytes to {game}]\n[syntax check: OK]",
            executed=True,
            approval="approved",
            risk=RiskLevel.WRITE,
        )
        ToolOrchestrator()._finish(
            "write",
            {"filePath": str(smoke), "content": "console.log('smoke')"},
            f"[wrote 20 bytes to {smoke}]\n[syntax check: BRACKET_MISMATCH: opens=35, closes=40]",
            executed=True,
            approval="approved",
            risk=RiskLevel.WRITE,
        )
        return "T01-runner written with helper smoke file."

    agent._run_impl = recovered_run
    result = await agent.run("create the runner")

    assert "T01-runner written" in result
    assert "evidence failed" not in result


@pytest.mark.asyncio
async def test_declared_read_only_effect_skips_side_effect_gate():
    """只读任务声明 effect=search 时，即使 prompt 含副作用措辞，
    证据门也不应把完成答案替换为占位符（evals websearch-summary 修复）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)

    async def prose_run(_user_input: str, _mode: str) -> str:
        return "已完成：2026 年 AI 编程助手的三大趋势。搜索工具已调用。"

    agent._run_impl = prose_run
    result = await agent.run("创建文件并实现功能", effect="search")

    assert result.startswith("已完成")
    assert "evidence failed" not in result


@pytest.mark.asyncio
async def test_s3_explain_prompt_succeeds_after_bash_ls_without_write():
    """S3 SOLO 只读问答：bash/ls 探测不得要求 WRITE 证据。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    agent = object.__new__(AgentV2)
    prompt = (
        "这段代码干什么？\n\n"
        "```python\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "```"
    )

    async def explain_run(_user_input: str, _mode: str) -> str:
        agent._side_effecting_tool_attempted = True
        ToolOrchestrator()._finish(
            "bash",
            {"command": "ls"},
            "lru_cache.py\n",
            executed=True,
            approval="auto",
            risk=RiskLevel.READ,
        )
        ToolOrchestrator()._finish(
            "ls",
            {"path": "."},
            "lru_cache.py\n",
            executed=True,
            approval="auto",
            risk=RiskLevel.READ,
        )
        return "这段代码定义函数 add，返回两个参数之和。"

    agent._run_impl = explain_run
    result = await agent.run(prompt)

    assert "evidence failed" not in result
    assert "两个参数" in result or "之和" in result


@pytest.mark.asyncio
async def test_declared_write_effect_forces_side_effect_gate():
    """显式声明 effect=write 时，无 WRITE/DANGER 证据的完成声称仍被门拦截。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)

    async def prose_run(_user_input: str, _mode: str) -> str:
        return "已完成"

    agent._run_impl = prose_run
    result = await agent.run("搜索资料", effect="write")

    assert result.startswith(
        "[evidence failed: requested side effect has no verified "
        "WRITE/DANGER tool execution]"
    )
