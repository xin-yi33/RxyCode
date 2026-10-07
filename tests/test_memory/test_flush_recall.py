"""layer=unit/module F4-3 flush/recall + user memory 注入。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager
from RxyCode.RxyCode1_1_0.memory.user_memory import UserMemory


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    return tmp_path


def _preference_chain():
    return [
        HumanMessage(content="我喜欢用 pytest 而不是 unittest，以后测试都用 pytest。"),
        AIMessage(content="明白，之后测试统一用 pytest。"),
        HumanMessage(content="先帮我把断言补全。"),
        AIMessage(content="已补全。"),
    ]


def test_u_f4_3_01_flush_writes_experience_only(tmp_data_dir):
    """layer=unit U-F4-3-01（裁定 A）
    压缩前 flush：≤200 字符首人称偏好短句只进 experience（kind=preference、
    source="flush_before_compaction"）；UserMemory 绝对零写；返回键到新名。
    """
    manager = MemoryManager(session_id="sess_f43")
    before = len(UserMemory().list_all())
    result = manager.flush_before_compaction(_preference_chain())
    assert result == {"preference_added": 1, "artifact_added": 0}
    assert len(UserMemory().list_all()) == before         # user memory 恒不变（绝不双写）
    records = manager.experience._load_records()
    flushed = [r for r in records if "我喜欢用 pytest" in str(r.get("text") or "")]
    assert len(flushed) == 1
    assert flushed[0].get("kind") == "preference"
    assert flushed[0].get("source") == "flush_before_compaction"
    assert flushed[0].get("session") == "sess_f43"
    recalled = manager.experience.retrieve_context("pytest", top_k=1)
    assert "pytest" in recalled
    ctx = manager.get_context_for_prompt("pytest")
    assert "[User memory]" not in ctx                  # 无手写条目 → 整段不出现（flush 不进 excerpt）


def test_u_f4_3_02_excerpt_global_handwritten_only_dedup(tmp_data_dir):
    """layer=unit U-F4-3-02（裁定 A）
    [User memory] 只呈现 global 手写确认条目；与 [Long-term memory] 逐字重复 → 去重；
    flush 的 project 条目（experience 库）不进 excerpt。
    （2026-10-02 修复：同名重复 def :1054/:1071 已删除并唯一化。）
    """
    UserMemory().add("用户偏好：回答使用中文。")               # 手写条目 = global（与 long-term 重复）
    UserMemory().add("用户偏好：单测都跑 pytest。")               # 手写条目 = global（不重复 → 段内可见）
    manager = MemoryManager(session_id="sess_f43b")
    manager.long_term.save_session_context("用户偏好：回答使用中文。老会话事实ABC。")
    manager.flush_before_compaction(_preference_chain())       # flush（只进 experience）
    ctx = manager.get_context_for_prompt("pytest 怎么写夹具")
    assert "[User memory]" in ctx
    assert "[Long-term memory]" in ctx
    body = _memory_user_section_body(ctx)
    assert "用户偏好：单测都跑 pytest。" in body                 # 非重复手写条目可见
    assert "我喜欢用 pytest" not in body                    # flush 的内容不进 excerpt
    assert "用户偏好：回答使用中文。" not in body               # 与 long-term 逐字重复 → 去重
    assert ctx.count("用户偏好：回答使用中文。") == 1


_KNOWN_SECTION_HEADERS = (
    "[Long-term memory]",
    "[Relevant verified experience]",
    "[Relevant code context]",
    "[Recent conversation]",
)


def _memory_user_section_body(ctx: str) -> str:
    """[User memory] 段体（§1.5 切片规则：到下一个已知段头为止）。"""
    assert "[User memory]" in ctx
    section = ctx.split("[User memory]", 1)[1]
    ends = [section.find(h) for h in _KNOWN_SECTION_HEADERS if section.find(h) >= 0]
    end = min(ends) if ends else len(section)
    return section[:end]


def test_u_f4_3_03_user_memory_excerpt_bounded_800_chars(tmp_data_dir):
    """layer=unit U-F4-3-03
    user memory 无限增长时 excerpt 有界：段体 <= USER_MEMORY_EXCERPT_MAX_CHARS（800），
    且原文总量确实 > 800（截断真发生，不是刚好够短）。
    """
    from RxyCode.RxyCode1_1_0.memory.manager import USER_MEMORY_EXCERPT_MAX_CHARS

    assert USER_MEMORY_EXCERPT_MAX_CHARS == 800
    um = UserMemory()
    for i in range(40):
        um.add(f"第{i}条偏好" + "很长的说明文字" * 20)
    assert len(um.get_all_text()) > 800
    manager = MemoryManager(session_id="sess_f43c")
    ctx = manager.get_context_for_prompt("偏好")
    body = _memory_user_section_body(ctx)
    assert len(body) <= USER_MEMORY_EXCERPT_MAX_CHARS
    assert "偏好" in body                                  # 截断后仍有内容（非空段）


def test_u_f4_3_04_flush_rejects_long_path_and_sensitive_hits(tmp_data_dir):
    """layer=unit U-F4-3-04（三条拒绝线，裁定 A 落点 = experience）
    超长（>200 字符）/含路径/含疑似敏感信息的"偏好句式命中"一律不写入；
    合法短句仍入库（preference_added == 1）；UserMemory 恒空。
    """
    manager = MemoryManager(session_id="sess_f43d")
    long_pref = "我喜欢详细的输出格式，以后都用它。" + "补充说明" * 60      # >200 字符
    messages = [
        HumanMessage(content=long_pref),
        HumanMessage(content="我喜欢用 D:\\proj\\tools\\fix.ps1，以后都用它。"),   # 含路径
        HumanMessage(content="我喜欢的 sk-abcdefghijklmnop 很好记，以后都用它。"),  # 疑似密钥
        HumanMessage(content="我的 password 是 hunter2，以后都用它。"),            # 敏感关键词
        HumanMessage(content="我喜欢中文回答，以后都用中文。"),                    # 合法短句
    ]
    result = manager.flush_before_compaction(messages)
    assert result == {"preference_added": 1, "artifact_added": 0}
    assert UserMemory().list_all() == []                    # 绝不写 UserMemory
    records = manager.experience._load_records()
    texts = [str(r.get("text") or "") for r in records]
    assert texts == ["我喜欢中文回答，以后都用中文。"]
    joined = "\n".join(texts)
    assert "D:\\proj" not in joined
    assert "sk-abcdefghijklmnop" not in joined
    assert "hunter2" not in joined
    assert records[0].get("source") == "flush_before_compaction"


def test_u_f4_3_05_duplicate_preference_not_rewritten(tmp_data_dir):
    """layer=unit U-F4-3-05（裁定 A）
    与 experience 既有条目逐字重复的偏好：跳过、不写、不计数（第二次 flush 全 0，fingerprint 去重）。
    """
    manager = MemoryManager(session_id="sess_f43e")
    first = manager.flush_before_compaction(_preference_chain())
    assert first == {"preference_added": 1, "artifact_added": 0}
    second = manager.flush_before_compaction(_preference_chain())
    assert second == {"preference_added": 0, "artifact_added": 0}
    records = [r for r in manager.experience._load_records() if "我喜欢用 pytest" in str(r.get("text") or "")]
    assert len(records) == 1


def test_u_f4_3_06_write_evidence_only_from_tool_results(tmp_data_dir):
    """layer=unit U-F4-3-06（裁定 A）
    文件证据只看工具结果：参数有 path 但结果为 [error → 该文件不进经验库；
    write 成功结果 → 以 kind="artifact" 进库。human 自称"我改了 x.py"不构成证据。
    """
    chain = [
        HumanMessage(content="帮我把 login.py 补上设备校验"),
        AIMessage(
            content="写 login.py",
            tool_calls=[{"id": "c1", "name": "write_file", "args": {"path": "login.py", "content": "x"}}],
        ),
        ToolMessage(content="[error: permission denied]", tool_call_id="c1"),
        AIMessage(
            content="改写 auth.py",
            tool_calls=[{"id": "c2", "name": "write_file", "args": {"path": "auth.py", "content": "y"}}],
        ),
        ToolMessage(content="write ok, 128 bytes", tool_call_id="c2"),
        HumanMessage(content="我自己手动也改了 config.py 但没用工具"),
    ]
    manager = MemoryManager(session_id="sess_f43f")
    result = manager.flush_before_compaction(chain)
    assert result == {"preference_added": 0, "artifact_added": 1}      # 仅 auth.py 一条 artifact
    records = [
        r for r in manager.experience._load_records()
        if str(r.get("kind") or "") == "artifact"
    ]
    assert len(records) == 1
    artifact_text = str(records[0].get("text") or "")
    assert "auth.py" in artifact_text
    assert "login.py" not in artifact_text                   # error 结果 → 不进库
    assert "config.py" not in artifact_text                  # human 自称不构成证据
    assert records[0].get("source") == "flush_before_compaction"


def test_u_f4_3_07_remove_honored_by_excerpt(tmp_data_dir):
    """layer=unit U-F4-3-07（读取面不落灰）
    原删除能力有断言：UserMemory.remove 后该条目从 excerpt 消失。
    """
    um = UserMemory()
    entry = um.add("临时事实：本条将删除。")
    manager = MemoryManager(session_id="sess_f43g")
    ctx_before = manager.get_context_for_prompt("临时事实")
    assert "临时事实：本条将删除。" in _memory_user_section_body(ctx_before)
    assert um.remove(entry["id"]) is True
    ctx_after = manager.get_context_for_prompt("临时事实")
    assert "临时事实：本条将删除。" not in ctx_after


def test_u_f4_3_08_cross_project_experience_isolation(tmp_data_dir):
    """layer=unit U-F4-3-08（裁定 A·新增：跨项目隔离）
    两个不同 project 的 ExperienceVectorMemory 实例（共享同一 vectors.jsonl）：
    项目 A flush 的偏好/产物项目 B **互不可见**（search/retrieve 层被 project 过滤），
    但项目 A 自己可见（伪隔离=红灯的反例；隔离按真实构造面 vector_memory.py:207 锚）。
    """
    from RxyCode.RxyCode1_1_0.memory.vector_memory import ExperienceVectorMemory

    shared = tmp_data_dir / "memory" / "experiences" / "vectors.jsonl"
    exp_a = ExperienceVectorMemory(project="proj-alpha", path=shared)
    exp_b = ExperienceVectorMemory(project="proj-beta", path=shared)
    assert exp_a.path == exp_b.path                        # 同一物理文件，隔离靠 project 过滤

    manager = MemoryManager(session_id="sess_f43h")
    manager.experience = exp_a                              # 注入项目 A 库（同 bind 通道）
    result = manager.flush_before_compaction(_preference_chain())
    assert result == {"preference_added": 1, "artifact_added": 0}

    rec_a = exp_a.search("我喜欢用 pytest", top_k=5, kind="preference")
    assert len(rec_a) == 1
    assert "我喜欢用 pytest" in rec_a[0].text
    assert exp_a.path.read_text(encoding="utf-8").count("我喜欢用 pytest") >= 1  # 物理落盘反假绿
    assert exp_b.search("我喜欢用 pytest", top_k=5, kind="preference") == []     # B 完全不可见
    assert "我喜欢用 pytest" not in exp_b.retrieve_context("pytest", top_k=5)

    exp_b.add("项目 B 自己的偏好", kind="preference", outcome="stated", session="sess_f43h")
    assert exp_b.search("项目 B 自己的偏好", top_k=5) != []
    assert exp_a.search("项目 B 自己的偏好", top_k=5, kind="preference") == []     # 反向同样成立


def test_mo_f4_3_01_memory_in_user_suffix_prefix_bytes_unchanged(tmp_data_dir):
    """layer=module MO-F4-3-01
    _continue_agent_prefix 链路回归：memory 注入只进 user 后缀，S1 冻结前缀逐字节不变。
    （对 _continue_agent_prefix 的回归断言，B5/Phase-Fix 前缀纪律。）
    """
    from langchain_core.messages import SystemMessage

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.prompts.registry import build_user_message

    UserMemory().add("用户偏好：回答使用中文。")
    manager = MemoryManager(session_id="sess_f43m")
    memory_ctx = manager.get_context_for_prompt("继续")
    assert "[User memory]" in memory_ctx

    s1 = "S1-FROZEN-PREFIX-逐字节"
    agent = object.__new__(AgentV2)
    agent._agent_prefix_messages = [
        SystemMessage(content=s1),
        HumanMessage(content="旧问题"),
        AIMessage(content="旧回答"),
    ]
    user_msg = build_user_message("", "新问题", memory_ctx)
    assert "[User memory]" in user_msg
    assert s1 not in user_msg                            # S1 不得被搬进 user 后缀
    continue_msgs = agent._continue_agent_prefix(s1, user_msg)
    assert continue_msgs[0].content == s1                # 前缀首条逐字节 = S1
    assert agent._agent_prefix_is_live(s1) is True
    assert continue_msgs[-1].content == user_msg         # 注入落在新的 user 后缀
    assert continue_msgs[1].content == "旧问题"          # 历史轮次保持
