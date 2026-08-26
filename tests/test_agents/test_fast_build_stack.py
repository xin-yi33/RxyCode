"""FAST_LOCAL_BUILD_INSTRUCTION must not force Java/Spring or data-analysis stacks."""

from __future__ import annotations

from core.agent_v2 import FAST_LOCAL_BUILD_INSTRUCTION


def test_explain_prompts_are_not_nudged_to_write_java() -> None:
    from core.agent_v2 import _should_nudge_build_to_write

    assert _should_nudge_build_to_write("build", False, 0) is True
    assert (
        _should_nudge_build_to_write(
            "build", False, 0, user_input="这段代码干什么？不要改任何文件。"
        )
        is False
    )
    assert (
        _should_nudge_build_to_write(
            "build",
            False,
            0,
            user_input=(
                "这段代码干什么？\n\n```python\ndef add(a, b):\n    return a + b\n```"
            ),
        )
        is False
    )
    assert (
        _should_nudge_build_to_write("build", False, 0, user_input="/solo 用一句话介绍你自己")
        is False
    )


def test_nudge_continues_until_named_pytest_file_exists(tmp_path) -> None:
    from core.agent_v2 import _should_nudge_build_to_write

    prompt = "/solo 实现 calc 并写 tests/test_calc.py"
    (tmp_path / "calc").mkdir()
    (tmp_path / "calc" / "eval.py").write_text("x = 1\n", encoding="utf-8")
    assert (
        _should_nudge_build_to_write(
            "build", True, 0, user_input=prompt, workspace_root=tmp_path
        )
        is True
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_calc.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    assert (
        _should_nudge_build_to_write(
            "build", True, 0, user_input=prompt, workspace_root=tmp_path
        )
        is False
    )
    (tests / "test_calc.py").unlink()
    assert (
        _should_nudge_build_to_write(
            "build", True, 2, user_input=prompt, workspace_root=tmp_path
        )
        is True
    )


def test_fast_build_instruction_follows_user_stack() -> None:
    text = FAST_LOCAL_BUILD_INSTRUCTION
    lowered = text.lower()
    assert "use the write/edit tools for source files" in lowered
    assert "issue tool calls directly" in lowered
    assert "do not narrate" in lowered
    assert "do not write _probe.py" in lowered
    assert "replace the complete file" in lowered
    assert "do not invent java/spring/maven/pom.xml" in lowered
    assert "if the user asked only to explain or chat, do not write files" in lowered
    assert "do not pip show or pip install" in lowered
    assert "do not import jwt" in lowered
    assert "lru_cache.py" in lowered
    assert "tests/test_calc.py" in lowered
    assert "write pom.xml and java sources first" not in lowered
    assert "*controller.java" not in lowered
    assert "黄金" not in text
    assert "nasdaq" not in lowered
    assert "autoconfiguremockmvc" not in lowered
