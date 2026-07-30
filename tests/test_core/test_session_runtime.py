from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path


def _create_tasks_in_process(
    data_dir: str,
    session_id: str,
    prefix: str,
    count: int,
    start_event,
    result_queue,
) -> None:
    os.environ["RXYCODE_DATA_DIR"] = data_dir
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
    )
    from RxyCode.RxyCode1_1_0.tools.task_tool import manage_tasks

    token = bind_session(session_id)
    try:
        if not start_event.wait(timeout=10):
            result_queue.put(["start timeout"])
            return
        result_queue.put(
            [
                manage_tasks("create", summary=f"{prefix}-{index}")
                for index in range(count)
            ]
        )
    finally:
        reset_session_binding(token)


def test_sessions_keep_independent_working_directories_and_tasks(
    tmp_path,
    monkeypatch,
):
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        current_working_directory,
        reset_session_binding,
        set_working_directory,
    )
    from RxyCode.RxyCode1_1_0.tools.read import read_file
    from RxyCode.RxyCode1_1_0.tools.task_tool import manage_tasks
    from RxyCode.RxyCode1_1_0.tools.write import write_file

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    process_cwd = Path.cwd()

    first_token = bind_session("session-a")
    try:
        set_working_directory(first_dir)
        assert "wrote" in write_file("shared.txt", "first-session")
        assert manage_tasks("create", summary="first-only").startswith(
            "Created task T1:"
        )
        assert current_working_directory() == first_dir.resolve()
    finally:
        reset_session_binding(first_token)

    second_token = bind_session("session-b")
    try:
        set_working_directory(second_dir)
        assert "wrote" in write_file("shared.txt", "second-session")
        assert "first-only" not in manage_tasks("list")
        assert manage_tasks("create", summary="second-only").startswith(
            "Created task T1:"
        )
        assert "second-session" in read_file("shared.txt")
        assert current_working_directory() == second_dir.resolve()
    finally:
        reset_session_binding(second_token)

    first_token = bind_session("session-a")
    try:
        assert current_working_directory() == first_dir.resolve()
        tasks = manage_tasks("list")
        assert "first-only" in tasks
        assert "second-only" not in tasks
        assert "second-session" in read_file("shared.txt")
    finally:
        reset_session_binding(first_token)

    assert Path.cwd() == process_cwd
    output_dir = tmp_path / "data" / "output"
    generated = list(output_dir.glob("*/shared.txt"))
    assert len(generated) == 1
    assert generated[0].read_text(encoding="utf-8") == "second-session"


def test_project_and_runtime_session_records_use_dated_directories(tmp_path, monkeypatch):
    from datetime import datetime
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
        set_working_directory,
    )

    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(data_dir))
    token = bind_session("dated-session")
    try:
        set_working_directory(workspace)
    finally:
        reset_session_binding(token)

    date_dir = datetime.now().strftime("%Y-%m-%d")
    project_file = data_dir / "projects" / date_dir / "dated-session.json"
    session_file = data_dir / "sessions" / date_dir / "runtime" / "dated-session.json"
    assert project_file.exists()
    assert session_file.exists()
    assert json.loads(project_file.read_text(encoding="utf-8"))["working_directory"] == str(workspace.resolve())
    assert json.loads(session_file.read_text(encoding="utf-8"))["project_file"] == str(project_file)


def test_registered_local_file_tools_resolve_against_session_cwd(
    tmp_path,
    monkeypatch,
):
    import RxyCode.RxyCode1_1_0.tools.format_tool as format_module
    import RxyCode.RxyCode1_1_0.tools.git_tool as git_module
    import RxyCode.RxyCode1_1_0.tools.vision as vision_module
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
        set_working_directory,
    )
    from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
    from RxyCode.RxyCode1_1_0.tools.edit import edit_file
    from RxyCode.RxyCode1_1_0.tools.glob_tool import glob_files
    from RxyCode.RxyCode1_1_0.tools.grep_tool import grep_files
    from RxyCode.RxyCode1_1_0.tools.ls import run_ls
    from RxyCode.RxyCode1_1_0.tools.open_file import _validate_previewable_file
    from RxyCode.RxyCode1_1_0.tools.patch import run_patch
    from RxyCode.RxyCode1_1_0.tools.read import read_file
    from RxyCode.RxyCode1_1_0.tools.view import run_view
    from RxyCode.RxyCode1_1_0.tools.write import write_file

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    process_cwd = Path.cwd()
    token = bind_session("relative-tools")
    try:
        set_working_directory(workspace)
        assert "wrote" in write_file("sample.txt", "alpha\n")
        assert "alpha" in read_file("sample.txt")
        assert "edited" in edit_file("sample.txt", "alpha", "beta")
        assert "beta" in run_view("sample.txt")
        output_dir = tmp_path / "data" / "output"
        dated_output = next(output_dir.iterdir())
        assert "beta" in grep_files("beta", str(dated_output), "*.txt")
        assert str(dated_output / "sample.txt") in glob_files("*.txt", str(dated_output))
        assert "sample.txt" in run_ls(str(dated_output))
        patch = "@@ -1,1 +1,1 @@\n-beta\n+gamma"
        assert "Patch applied" in run_patch("sample.txt", patch)

        write_file("clean.py", "value = 1\n")
        assert "No issues" in run_diagnostics("clean.py")

        write_file("page.html", "<html></html>")
        preview_path, error = _validate_previewable_file("page.html")
        assert error is None
        assert preview_path == (dated_output / "page.html").resolve()

        formatted_commands = []

        def fake_formatter(command, _file_path):
            formatted_commands.append(command)
            return "formatted"

        monkeypatch.setattr(format_module, "_run_formatter", fake_formatter)
        assert format_module.run_format("clean.py", tool="black") == "formatted"
        assert formatted_commands[-1][-1] == str((dated_output / "clean.py").resolve())

        monkeypatch.setattr(
            git_module,
            "_run_git",
            lambda _command, repository: f"repository:{repository}",
        )
        assert git_module.run_git("status", ".") == (
            f"repository:{workspace.resolve()}"
        )

        image = workspace / "image.png"
        image.write_bytes(b"not-decoded-by-this-test")
        monkeypatch.setattr(
            vision_module,
            "_describe_image",
            lambda path: f"resolved:{path}",
        )
        assert vision_module.run_vision("describe", "image.png") == (
            f"resolved:{image.resolve()}"
        )
    finally:
        reset_session_binding(token)

    assert Path.cwd() == process_cwd


def test_concurrent_structured_tools_keep_session_files_and_tasks_isolated(
    tmp_path,
    monkeypatch,
):
    import asyncio

    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
        set_working_directory,
    )
    from RxyCode.RxyCode1_1_0.tools.read import read_tool
    from RxyCode.RxyCode1_1_0.tools.task_tool import task_tool
    from RxyCode.RxyCode1_1_0.tools.write import write_tool

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    directories = [tmp_path / "async-a", tmp_path / "async-b"]
    for directory in directories:
        directory.mkdir()
    process_cwd = Path.cwd()

    async def run_session(session_id: str, directory: Path, marker: str):
        token = bind_session(session_id)
        try:
            set_working_directory(directory)
            await write_tool.ainvoke(
                {"filePath": f"{session_id}.txt", "content": marker}
            )
            created = await task_tool.ainvoke(
                {"operation": "create", "summary": marker}
            )
            await asyncio.sleep(0)
            content = await read_tool.ainvoke({"filePath": f"{session_id}.txt"})
            tasks = await task_tool.ainvoke({"operation": "list"})
            return created, content, tasks
        finally:
            reset_session_binding(token)

    async def run_both():
        return await asyncio.gather(
            run_session("async-a", directories[0], "only-a"),
            run_session("async-b", directories[1], "only-b"),
        )

    first, second = asyncio.run(run_both())
    assert first[0].startswith("Created task T1:")
    assert second[0].startswith("Created task T1:")
    assert "only-a" in first[1] and "only-b" not in first[1]
    assert "only-b" in second[1] and "only-a" not in second[1]
    assert "only-a" in first[2] and "only-b" not in first[2]
    assert "only-b" in second[2] and "only-a" not in second[2]
    assert Path.cwd() == process_cwd


def test_write_gate_and_tool_resolve_the_same_session_relative_target(
    tmp_path,
    monkeypatch,
):
    import asyncio

    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
        set_working_directory,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.write import write_tool

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    session_dir = tmp_path / "session-root"
    sibling = tmp_path / "sibling"
    session_dir.mkdir()
    sibling.mkdir()
    orchestrator = ToolOrchestrator()
    orchestrator.register("write", write_tool)
    config = {
        "safety": {
            "enabled": True,
            "auto_approve": ["write"],
        }
    }

    token = bind_session("write-gate")
    try:
        set_working_directory(session_dir)
        evidence_token = orchestrator.begin_evidence_capture()
        allowed = asyncio.run(
            orchestrator.execute_tool(
                "write",
                {"filePath": "inside.txt", "content": "inside"},
                config,
            )
        )
        evidence = orchestrator.end_evidence_capture(evidence_token)
        blocked = asyncio.run(
            orchestrator.execute_tool(
                "write",
                {"filePath": str(sibling / "outside.txt"), "content": "outside"},
                config,
            )
        )
    finally:
        reset_session_binding(token)

    assert allowed.startswith("[wrote ")
    assert len(evidence) == 1
    assert evidence[0].passed is True
    output_dir = tmp_path / "data" / "output"
    inside = next(output_dir.glob("*/inside.txt"))
    assert evidence[0].artifacts[0].path == str(inside.resolve())
    assert inside.read_text(encoding="utf-8") == "inside"
    assert "write path not allowed" in blocked
    assert not list(output_dir.glob("*/outside.txt"))
    assert not (sibling / "outside.txt").exists()


def test_task_store_cross_process_transactions_do_not_lose_updates(tmp_path):
    data_dir = tmp_path / "data"
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_create_tasks_in_process,
            args=(
                str(data_dir),
                "concurrent-session",
                prefix,
                8,
                start_event,
                result_queue,
            ),
        )
        for prefix in ("left", "right")
    ]
    for process in processes:
        process.start()
    start_event.set()
    results = [result_queue.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    assert all(result.startswith("Created task T") for batch in results for result in batch)
    document = json.loads(
        (
            data_dir
            / "tasks"
            / "concurrent-session"
            / "tasks.json"
        ).read_text(encoding="utf-8")
    )
    assert len(document["tasks"]) == 16
    assert document["next_id"] == 17
    assert {task["summary"].split("-")[0] for task in document["tasks"].values()} == {
        "left",
        "right",
    }


def test_shell_uses_bound_session_cwd_inside_workspace(tmp_path, monkeypatch):
    import RxyCode.RxyCode1_1_0.utils.shell as shell_module
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
        set_working_directory,
    )

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)
    monkeypatch.setattr(
        shell_module,
        "load_config",
        lambda: {
            "execution": {
                "sandbox_mode": "workspace",
                "workspace_root": str(workspace),
            }
        },
    )

    token = bind_session("shell-session")
    try:
        set_working_directory(nested)
        policy = shell_module.shell_executor._execution_policy("")
    finally:
        reset_session_binding(token)

    assert policy.workspace_root == workspace.resolve()
    assert policy.cwd == nested.resolve()


def test_sync_shell_thread_bridge_preserves_session_binding(tmp_path, monkeypatch):
    import asyncio

    import RxyCode.RxyCode1_1_0.utils.shell as shell_module
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        current_working_directory,
        reset_session_binding,
        set_working_directory,
    )

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    session_dir = tmp_path / "thread-session"
    session_dir.mkdir()

    async def capture_context(_command, _workdir, _timeout):
        return {
            "stdout": str(current_working_directory()),
            "stderr": "",
            "success": True,
            "exit_code": 0,
        }

    monkeypatch.setattr(shell_module.shell_executor, "execute_async", capture_context)

    async def invoke_sync_bridge():
        token = bind_session("thread-bridge")
        try:
            set_working_directory(session_dir)
            return shell_module.shell_executor.execute("ignored")
        finally:
            reset_session_binding(token)

    result = asyncio.run(invoke_sync_bridge())
    assert result["stdout"] == str(session_dir.resolve())


def test_workspace_cd_rejects_session_escape(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
    )
    from RxyCode.RxyCode1_1_0.tools.change_directory import change_directory
    import RxyCode.RxyCode1_1_0.config.settings as settings

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        settings,
        "load_config",
        lambda: {
            "execution": {
                "sandbox_mode": "workspace",
                "workspace_root": str(workspace),
            }
        },
    )

    token = bind_session("bounded-session")
    try:
        result = change_directory(str(outside))
    finally:
        reset_session_binding(token)

    assert result.startswith("[error: directory escapes")


async def _workflow_result_for_args(_script, args, *, timeout_seconds):
    return str(args["value"])


def test_workflow_run_ids_and_status_are_session_isolated(monkeypatch):
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
    )
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    monkeypatch.setattr(
        workflow,
        "_execute_script_async",
        _workflow_result_for_args,
    )
    run_id = "shared-workflow-id"

    first_token = bind_session("workflow-a")
    try:
        first = workflow.manage_workflow(
            "run",
            script="ignored",
            args='{"value":"first"}',
            run_id=run_id,
        )
    finally:
        reset_session_binding(first_token)

    second_token = bind_session("workflow-b")
    try:
        second = workflow.manage_workflow(
            "run",
            script="ignored",
            args='{"value":"second"}',
            run_id=run_id,
        )
        second_status = workflow.manage_workflow("status", run_id=run_id)
    finally:
        reset_session_binding(second_token)

    first_token = bind_session("workflow-a")
    try:
        first_status = workflow.manage_workflow("status", run_id=run_id)
    finally:
        reset_session_binding(first_token)

    assert "first" in first and "second" not in first
    assert "second" in second and "first" not in second
    assert '"result": "first"' in first_status
    assert '"result": "second"' in second_status
