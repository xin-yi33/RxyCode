"""layer=unit/module F5-1 todo_write on the existing tasks.json ledger."""
from __future__ import annotations

import json
import threading
import time

import pytest

from RxyCode.RxyCode1_1_0.config import settings
from RxyCode.RxyCode1_1_0.core.session_runtime import bind_session, reset_session_binding
from RxyCode.RxyCode1_1_0.tools.task_tool import manage_tasks


pytestmark = pytest.mark.usefixtures("_todo_data_dir")


@pytest.fixture
def _todo_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "get_data_dir", lambda: tmp_path)


@pytest.fixture
def session():
    token = bind_session("sess_f5_1")
    try:
        yield "sess_f5_1"
    finally:
        reset_session_binding(token)


def _store_bytes() -> bytes:
    path = settings.get_data_dir() / "tasks" / "sess_f5_1" / "tasks.json"
    if not path.exists():
        return b""
    return path.read_bytes()


def _models():
    from RxyCode.RxyCode1_1_0.tools.todo_write import read_todo_models

    return read_todo_models()


def test_u_f5_1_01_merge_replace_and_auto_merge(session):
    """layer=unit U-F5-1-01 merge/replace/自动 merge 三路径。"""
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_write

    first = todo_write(
        [{"id": "t1", "content": "搭骨架", "status": "in_progress"}],
        merge=True,
    )
    assert first.snapshot.revision == 1
    second = todo_write([{"id": "t1", "status": "completed"}, {"id": "t2", "content": "装依赖", "status": "pending"}], merge=True)
    assert second.snapshot.revision == 2
    viewed = {item.id: (item.content, item.status) for item in _models()}
    assert viewed == {"t1": ("搭骨架", "completed"), "t2": ("装依赖", "pending")}

    replaced = todo_write(
        [{"id": "only", "content": "只留这一条", "status": "pending"}],
        merge=False,
    )
    assert [item.id for item in _models()] == ["only"]
    assert replaced.snapshot.revision == 3

    todo_write(
        [
            {"id": "a", "content": "甲", "status": "pending"},
            {"id": "b", "content": "乙", "status": "pending"},
        ],
        merge=False,
    )
    explicit = todo_write([{"id": "a", "status": "completed"}], merge=True)
    todo_write(
        [
            {"id": "a", "content": "甲", "status": "pending"},
            {"id": "b", "content": "乙", "status": "pending"},
        ],
        merge=False,
    )
    implied = todo_write([{"id": "a", "status": "completed"}])
    assert [ (item.id, item.content, item.status) for item in _models() ] == [
        (item.id, item.content, item.status) for item in explicit.snapshot.items
    ]
    assert implied.snapshot.revision == explicit.snapshot.revision + 2


def test_u_f5_1_02_two_in_progress_rejected_without_write(session):
    """layer=unit U-F5-1-02 两条 in_progress 拒绝且不落盘。"""
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_write

    todo_write([{"id": "t1", "content": "正在做", "status": "in_progress"}], merge=True)
    before = _store_bytes()
    rejected = todo_write(
        [{"id": "t2", "content": "另一件", "status": "in_progress"}],
        merge=True,
    )
    text = rejected if isinstance(rejected, str) else rejected.text
    assert text.startswith("[todo_write rejected]")
    assert "t1" in text and "t2" in text
    assert _store_bytes() == before
    unknown_before = _store_bytes()
    unknown = todo_write([{"id": "t3", "content": "坏状态", "status": "unknown"}], merge=True)
    unknown_text = unknown if isinstance(unknown, str) else unknown.text
    assert unknown_text.startswith("[todo_write rejected]")
    assert "t3" in unknown_text
    assert _store_bytes() == unknown_before
    ok = todo_write([{"id": "t2", "content": "另一件", "status": "pending"}], merge=True)
    assert not str(getattr(ok, "text", ok)).startswith("[todo_write rejected]")


def test_u_f5_1_03_missing_content_rejected(session):
    """layer=unit U-F5-1-03 content 丢失拒绝。"""
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_write

    todo_write([{"id": "t1", "content": "有内容", "status": "pending"}], merge=False)
    # Strip stored content/summary so the existing row has nothing to keep.
    path = settings.get_data_dir() / "tasks" / session / "tasks.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["tasks"]["t1"]["content"] = ""
    document["tasks"]["t1"]["summary"] = ""
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    before = path.read_bytes()
    rejected = todo_write([{"id": "t1", "status": "completed"}], merge=True)
    text = rejected if isinstance(rejected, str) else rejected.text
    assert text.startswith("[todo_write rejected]")
    assert "t1" in text
    assert path.read_bytes() == before


def test_u_f5_1_04_legacy_task_roundtrip(session):
    """layer=unit U-F5-1-04 旧 task/task_manage 双向状态兼容。"""
    from RxyCode.RxyCode1_1_0.tools.todo_write import read_todo_models, todo_write

    manage_tasks("create", summary="旧打开")
    manage_tasks("create", summary="旧完成")
    manage_tasks("done", id="T2")
    manage_tasks("create", summary="旧放弃")
    manage_tasks("abandon", id="T3")
    manage_tasks("create", summary="旧进行")
    manage_tasks("start", id="T4")
    manage_tasks("create", summary="旧阻塞")
    manage_tasks("block", id="T5")
    by_id = {item.id: item.status for item in read_todo_models()}
    assert by_id["T1"] == "pending"
    assert by_id["T2"] == "completed"
    assert by_id["T3"] == "cancelled"
    assert by_id["T4"] == "in_progress"
    assert by_id["T5"] == "blocked"
    created = json.loads((settings.get_data_dir() / "tasks" / session / "tasks.json").read_text(encoding="utf-8"))
    assert created["tasks"]["T1"]["created"]
    assert created["tasks"]["T1"]["history"]
    assert created["tasks"]["T1"]["summary"] == "旧打开"

    todo_write([{"id": "T1", "status": "completed"}], merge=True)
    listed = manage_tasks("list", status="done")
    assert "T1" in listed
    got = json.loads(manage_tasks("get", id="T1"))
    assert got["summary"]
    assert got["history"]
    assert got["created"]
    before_rev = json.loads((settings.get_data_dir() / "tasks" / session / "tasks.json").read_text(encoding="utf-8"))["revision"]
    manage_tasks("rename", id="T5", summary="改名后")
    renamed = {item.id: item.content for item in read_todo_models()}
    assert renamed["T5"] == "改名后"
    manage_tasks("start", id="T2")
    assert json.loads(manage_tasks("get", id="T2"))["status"] in {"in_progress", "open"}
    manage_tasks("create", summary="不覆盖 T1")
    kept = json.loads(manage_tasks("get", id="T1"))
    assert kept["summary"] != "不覆盖 T1"
    after = json.loads((settings.get_data_dir() / "tasks" / session / "tasks.json").read_text(encoding="utf-8"))
    assert after["revision"] > before_rev
    assert "T6" in after["tasks"] or any(row.get("summary") == "不覆盖 T1" for row in after["tasks"].values())
    stores = list((settings.get_data_dir() / "tasks" / session).glob("*.json"))
    assert [path.name for path in stores] == ["tasks.json"]


def test_u_f5_1_05_empty_list_is_legal(session):
    """layer=unit U-F5-1-05 空清单合法，且没有 Todo-summary LLM。"""
    from RxyCode.RxyCode1_1_0.tools import todo_write as mod

    result = mod.todo_write([], merge=False)
    assert "0" in result.text
    assert result.snapshot.items == []
    assert result.snapshot.revision >= 1
    assert mod.todo_summary_llm_calls == 0


@pytest.mark.asyncio
async def test_mo_f5_1_01_registered_tool_path(session):
    """layer=module MO-F5-1-01 生产注册路径真实可调用。"""
    from RxyCode.RxyCode1_1_0.core.builtin_tool_registration import register_builtin_tools
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry
    registry = ToolRegistry()
    orch = ToolOrchestrator(tool_registry=registry)
    register_builtin_tools(registry, orch, rag_enabled=False)
    description = orch.get("todo_write").description
    assert "3" in description
    assert "in_progress" in description
    text = await orch.execute_tool(
        "todo_write",
        {"todos": [{"id": "t1", "content": "搭骨架", "status": "in_progress"}], "merge": True},
        mode="full_auto",
    )
    assert "- [" in text
    assert "1" in text
    store = json.loads(_store_bytes().decode("utf-8"))
    assert text.snapshot.revision == store["revision"]
    before = _store_bytes()
    rejected = await orch.execute_tool(
        "todo_write",
        {"todos": [{"id": "t2", "content": "另一件", "status": "in_progress"}], "merge": True},
        mode="full_auto",
    )
    assert rejected.startswith("[todo_write rejected]")
    assert _store_bytes() == before


def test_mo_f5_1_02_file_lock_blocks_until_release(session, tmp_path):
    """layer=module MO-F5-1-02 另一个进程持有文件锁时，写入阻塞到释放后才成功。"""
    import subprocess
    import sys
    from pathlib import Path

    from RxyCode.RxyCode1_1_0.tools.task_tool import _tasks_dir
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_write

    directory = _tasks_dir()
    held = tmp_path / "held"
    release = tmp_path / "release"
    repo = Path(__file__).resolve().parents[2]
    script = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from RxyCode.RxyCode1_1_0.tools.task_tool import _task_file_lock\n"
        "directory, held, release = map(Path, sys.argv[1:4])\n"
        "with _task_file_lock(directory):\n"
        "    held.write_text('1', encoding='utf-8')\n"
        "    while not release.exists():\n"
        "        time.sleep(0.05)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(directory), str(held), str(release)],
        cwd=str(repo),
    )
    worker = None
    try:
        for _ in range(50):
            if held.exists():
                break
            time.sleep(0.05)
        assert held.exists()
        done = threading.Event()
        box: dict = {}

        def writer():
            box["result"] = todo_write(
                [{"id": "locked", "content": "锁后写入", "status": "pending"}],
                merge=True,
                session_id=session,
            )
            done.set()

        worker = threading.Thread(target=writer)
        worker.start()
        assert done.wait(0.4) is False
        release.write_text("1", encoding="utf-8")
        worker.join(5)
        document = json.loads(_store_bytes().decode("utf-8"))
        assert document["tasks"]["locked"]["content"] == "锁后写入"
        assert box["result"].snapshot.revision == document["revision"]
    finally:
        release.write_text("1", encoding="utf-8")
        if worker is not None:
            worker.join(5)
        if proc.poll() is None:
            proc.kill()
        proc.wait(5)
