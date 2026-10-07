"""layer=e2e E-F4-E2E-03 flush/recall + user memory + cache 不绿命中。"""
from __future__ import annotations

import hashlib
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

pytestmark = pytest.mark.e2e


def test_e2e_f4_03_flush_recall_cache_key_moves(tmp_path, monkeypatch):
    """layer=e2e E-F4-E2E-03（2026-10-02 裁定 A 后）
    setup：真实 tmp 数据目录 + 手写 global 条目 + 消息链（合法偏好 / 敏感命中 / error-write / write 成功）。
    扰动：flush_before_compaction。
    断言：flush 只进 experience（kind/source 命中、user memory 恒不变）；敏感命中不入库；
    error-write 不进 artifact、成功 write 进；excerpt 只呈现手写 global；经验召回改变
    memory_ctx 指纹 → 旧 precise 条目不命中。
    """
    from RxyCode.RxyCode1_1_0.cache.precise_cache import PreciseCache
    from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager, USER_MEMORY_EXCERPT_MAX_CHARS
    from RxyCode.RxyCode1_1_0.memory.user_memory import UserMemory

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    manager = MemoryManager(session_id="sess_e03")
    global_entry = UserMemory().add("手动事实：回答使用中文。")   # 手写（global 唯一该类通道）
    chain = [
        HumanMessage(content="我喜欢中文回答，测试一律 pytest。"),   # 合法偏好 → experience
        AIMessage(content="收到，按此偏好执行。"),
        HumanMessage(content="我的 password 是 hunter2，以后都用它。"),  # 敏感命中（拒绝）
        AIMessage(
            content="写 login.py",
            tool_calls=[{"id": "c1", "name": "write_file", "args": {"path": "login.py", "content": "x"}}],
        ),
        ToolMessage(content="[error: permission denied]", tool_call_id="c1"),   # error 结果（不进库）
        AIMessage(
            content="写 auth.py",
            tool_calls=[{"id": "c2", "name": "write_file", "args": {"path": "auth.py", "content": "y"}}],
        ),
        ToolMessage(content="write ok, 128 bytes", tool_call_id="c2"),          # 成功结果（进库）
    ]
    cache = PreciseCache(cache_dir=tmp_path / "cache")

    ctx_before = manager.get_context_for_prompt("写个测试")
    fp_before = (
        hashlib.sha256(ctx_before.encode("utf-8")).hexdigest() if ctx_before else None
    )
    key_before = json.dumps(["写个测试", fp_before], ensure_ascii=False, separators=(",", ":"))
    cache.put("sys", key_before, "stale-answer", namespace="e03")

    user_count_before = len(UserMemory().list_all())
    result = manager.flush_before_compaction(chain)
    assert result == {"preference_added": 1, "artifact_added": 1}   # 对账钉死（敏感句+error-write 均 +0）
    assert len(UserMemory().list_all()) == user_count_before         # flush 绝不写 user memory
    user_dir = tmp_path / "memory" / "user"
    assert (user_dir / "index.json").exists()
    md_files = list(user_dir.glob("*.md"))
    assert md_files, "手写条目必须真落盘 .md（读取面唯一物理来源）"
    all_text = UserMemory().get_all_text()
    assert "hunter2" not in all_text
    assert "pytest" not in all_text                                 # flush 文本不进 user memory
    records = manager.experience._load_records()
    pref_records = [r for r in records if str(r.get("kind") or "") == "preference"]
    assert len(pref_records) == 1
    assert "pytest" in str(pref_records[0].get("text") or "")
    assert pref_records[0].get("source") == "flush_before_compaction"
    artifact_records = [r for r in records if str(r.get("kind") or "") == "artifact"]
    assert len(artifact_records) == 1
    assert "auth.py" in str(artifact_records[0].get("text") or "")
    assert "login.py" not in str(artifact_records[0].get("text") or "")  # error 结果不进库
    assert artifact_records[0].get("source") == "flush_before_compaction"

    ctx_after = manager.get_context_for_prompt("写个测试")
    assert "[User memory]" in ctx_after
    section = ctx_after.split("[User memory]", 1)[1]
    known = ("[Long-term memory]", "[Relevant verified experience]", "[Relevant code context]", "[Recent conversation]")
    ends = [section.find(h) for h in known if section.find(h) >= 0]
    body = section[: min(ends) if ends else len(section)]
    assert len(body) <= 800
    assert USER_MEMORY_EXCERPT_MAX_CHARS == 800
    assert "手动事实：回答使用中文。" in body                      # excerpt 只呈现手写 global
    assert "测试一律 pytest" not in body                            # flush 内容不进 excerpt

    fp_after = hashlib.sha256(ctx_after.encode("utf-8")).hexdigest()
    assert fp_after != fp_before                                    # 经验召回移动指纹（非 user memory）
    key_after = json.dumps(["写个测试", fp_after], ensure_ascii=False, separators=(",", ":"))
    assert cache.get("sys", key_after, namespace="e03") is None      # 压实不误命中
    assert cache.get("sys", key_before, namespace="e03")["response"] == "stale-answer"
    assert UserMemory().remove(global_entry["id"]) is True           # 删除能力收尾（不落灰）
