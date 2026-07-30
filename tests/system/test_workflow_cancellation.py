"""Real-process cancellation contract for foreground workflow runs."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
from pathlib import Path
import time

import psutil
import pytest

from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow


pytestmark = pytest.mark.system


def _wait_for_file(path: Path, timeout: float = 10) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        time.sleep(0.01)
    raise AssertionError(f"workflow did not create {path}")


def test_cancel_terminates_workflow_process_and_preserves_cancelled_status(tmp_path):
    ready_file = tmp_path / "workflow.pid"
    script = (
        "import os, time\n"
        "from pathlib import Path\n"
        f"Path({str(ready_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        "time.sleep(30)\n"
    )

    run_id = "wf-system-cancel"
    with ThreadPoolExecutor(max_workers=1) as executor:
        run_context = copy_context()
        running = executor.submit(
            run_context.run,
            workflow.manage_workflow,
            "run",
            "",
            script,
            "{}",
            run_id,
        )
        child_pid = int(_wait_for_file(ready_file))
        assert psutil.pid_exists(child_pid)
        assert not running.done()

        result = workflow.manage_workflow("cancel", run_id=run_id)
        run_result = running.result(timeout=10)
        waited = json.loads(workflow.manage_workflow("wait", run_id=run_id))

    assert "cancelled" in result.lower()
    assert run_result.startswith("[workflow cancelled]")
    assert waited["status"] == "cancelled"
    assert not psutil.pid_exists(child_pid)


def test_completed_workflow_cannot_be_relabelled_cancelled(tmp_path):
    output_file = tmp_path / "done.txt"
    script = (
        "from pathlib import Path\n"
        f"Path({str(output_file)!r}).write_text('done', encoding='utf-8')\n"
    )
    run_id = "wf-system-complete"
    result = workflow.manage_workflow("run", script=script, run_id=run_id)
    completed = json.loads(workflow.manage_workflow("status", run_id=run_id))
    after_cancel = json.loads(workflow.manage_workflow("cancel", run_id=run_id))

    assert "status: completed" in result
    assert completed["status"] == "completed"
    assert after_cancel["status"] == "completed"
    assert output_file.read_text(encoding="utf-8") == "done"
