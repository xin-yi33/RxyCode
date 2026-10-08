"""F5-9：大输出在第一次截断前落盘，墓碑后路径还在。"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from RxyCode.RxyCode1_1_0.config.settings import get_data_dir
from RxyCode.RxyCode1_1_0.core.compaction import (
    TOOL_RESULT_TOMBSTONE,
    compact_messages,
    microcompact_messages,
)
from RxyCode.RxyCode1_1_0.core.session_runtime import bind_session, reset_session_binding
from RxyCode.RxyCode1_1_0.tools.bash import _format_result, _truncate_output

_BEARER = "SUPERSECRETBODYTOKEN"


_SHORT_BEARER = "DEMO123"
_JSON_SECRET = "jsonsecretvalue"


def _raw() -> str:
    return (
        "api_key=SUPERSECRETVALUE\n"
        f"Authorization: Bearer {_BEARER}\n"
        f"Authorization: Bearer {_SHORT_BEARER}\n"
        + '{"api_key":"'
        + _JSON_SECRET
        + '"}\n'
        + '{"password":"alpha beta"}\n'
        + '{"secret":"alpha,beta"}\n'
        + '{"authorization":"Bearer DEMO123","ok":true}\n'
        + ("x" * 22000)
        + "MIDDLE-MARKER"
        + ("y" * 22000)
    )


def _result(text: str) -> dict:
    return {"stdout": text, "stderr": "", "success": True, "exit_code": 0}


def _path_from(message: str) -> Path:
    for line in message.splitlines():
        if line.startswith("Full output saved to:"):
            return Path(line.split(":", 1)[1].strip())
    raise AssertionError(message)


def test_u_f5_9_01_spill_before_truncation_and_dedupe_raw_text(caplog, monkeypatch, tmp_path):
    token = bind_session("spill-unit-01")
    spill_dir = get_data_dir() / "spill" / "spill-unit-01"
    try:
        caplog.set_level(logging.DEBUG)
        raw = _raw()
        first = _format_result(_result(raw))
        path = _path_from(first)
        assert path.is_file()
        assert path.read_text(encoding="utf-8") == raw
        assert "MIDDLE-MARKER" not in first
        assert "SUPERSECRETVALUE" not in first
        assert _BEARER not in first
        assert _SHORT_BEARER not in first
        assert _JSON_SECRET not in first
        assert "alpha beta" not in first
        assert "alpha,beta" not in first
        assert '"ok":true' in first
        assert "Full output saved to:" in first
        assert "SUPERSECRETVALUE" not in caplog.text
        assert _BEARER not in caplog.text
        assert _JSON_SECRET not in caplog.text
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

        cleaned = ToolOrchestrator._clean_tool_output(first)
        assert _BEARER not in cleaned
        assert _SHORT_BEARER not in cleaned
        assert _JSON_SECRET not in cleaned
        assert "alpha beta" not in cleaned
        assert "alpha,beta" not in cleaned
        assert '"ok":true' in cleaned
        direct = ToolOrchestrator._clean_tool_output(
            f"Authorization: Bearer {_BEARER}\n"
            f"Authorization: Bearer {_SHORT_BEARER}\n"
            + '{"api_key":"'
            + _JSON_SECRET
            + '"}\n'
            + '{"password":"alpha beta"}\n'
            + '{"secret":"alpha,beta"}\n'
            + '{"authorization":"Bearer DEMO123","ok":true}'
        )
        assert _BEARER not in direct
        assert _SHORT_BEARER not in direct
        assert _JSON_SECRET not in direct
        assert "alpha beta" not in direct
        assert "alpha,beta" not in direct
        assert '"ok":true' in direct
        from RxyCode.RxyCode1_1_0.tools.bash import _redact_preview

        for sample in (
            "token=\nFull output saved to: C:/spill/keep.txt",
            "Bearer\nFull output saved to: C:/spill/keep.txt",
        ):
            assert "Full output saved to: C:/spill/keep.txt" in _redact_preview(sample)
            assert "Full output saved to: C:/spill/keep.txt" in ToolOrchestrator._clean_tool_output(sample)
        dangling = 'password="SECRET\\\nnext'
        split_key = '"api_key":\n"JSONLINESECRET"'
        quoted_key = '{"token":987654321}'
        assert "SECRET" not in _redact_preview(dangling)
        assert "next" in _redact_preview(dangling)
        assert "SECRET" not in ToolOrchestrator._clean_tool_output(dangling)
        assert "JSONLINESECRET" not in _redact_preview(split_key)
        assert "JSONLINESECRET" not in ToolOrchestrator._clean_tool_output(split_key)
        assert "987654321" not in _redact_preview(quoted_key)
        assert _redact_preview(quoted_key).endswith("}")
        assert "987654321" not in ToolOrchestrator._clean_tool_output(quoted_key)
        assert ToolOrchestrator._clean_tool_output(quoted_key).endswith("}")
        folded_key = '{"api_key"\n:\n"FOLDSECRET"}'
        mixed = "{'password': \"alpha'MIXSECRET\"}"
        single_key = "{'token':246813579}"
        for sample, secret in (
            (folded_key, "FOLDSECRET"),
            (mixed, "MIXSECRET"),
            (single_key, "246813579"),
        ):
            assert secret not in _redact_preview(sample)
            assert secret not in ToolOrchestrator._clean_tool_output(sample)
        assert ToolOrchestrator._clean_tool_output(single_key).endswith("}")
        escaped = '{"password":"Bearer DEMO123\\"TAIL_CREDENTIAL"}'
        assert "TAIL_CREDENTIAL" not in _redact_preview(escaped)
        assert "TAIL_CREDENTIAL" not in ToolOrchestrator._clean_tool_output(escaped)
        fake_prefix = ToolOrchestrator._clean_tool_output("Full output saved to: api_key=SECRET")
        assert "SECRET" not in fake_prefix
        outside = tmp_path / "workspace" / "spill" / "api_key=SECRET"
        outside.parent.mkdir(parents=True)
        outside.write_text("x", encoding="utf-8")
        outside_cleaned = ToolOrchestrator._clean_tool_output(f"Full output saved to: {outside}")
        assert "SECRET" not in outside_cleaned
        data = tmp_path / "token=archive"
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(data))
        bad_session = data / "spill" / "token=SECRET" / ("ab" * 16 + ".txt")
        bad_session.parent.mkdir(parents=True)
        bad_session.write_text("x", encoding="utf-8")
        bad_cleaned = ToolOrchestrator._clean_tool_output(f"Full output saved to: {bad_session}")
        assert "SECRET" not in bad_cleaned
        spilled = _format_result(_result("api_key=BODYSECRET\n" + ("q" * 40000)))
        preserved = ToolOrchestrator._clean_tool_output(spilled)
        assert "BODYSECRET" not in preserved
        preserved_path = _path_from(preserved)
        assert "token=archive" in str(preserved_path)
        assert preserved_path.is_file()
        dashes = "-" * 90000
        started = time.perf_counter()
        _redact_preview(dashes)
        ToolOrchestrator._clean_tool_output(dashes)
        assert time.perf_counter() - started < 0.2
        assert "LINESECRET" not in _redact_preview('password="LINESECRET\nnext')
        assert "LINESECRET" not in ToolOrchestrator._clean_tool_output('password="LINESECRET\nnext')
        bomb = 'password="' + ("\\" * 32)
        started = time.perf_counter()
        _redact_preview(bomb)
        ToolOrchestrator._clean_tool_output(bomb)
        assert time.perf_counter() - started < 0.2
        failed = _format_result(
            {"stdout": raw, "stderr": "", "success": False, "exit_code": 2},
            command="python boom.py",
        )
        path_line = next(
            line for line in failed.splitlines() if line.startswith("Full output saved to:")
        )
        assert not path_line.endswith("]")
        failed_path = Path(path_line.split(":", 1)[1].strip())
        assert failed_path.is_file()
        assert failed_path.read_text(encoding="utf-8").startswith("api_key=SUPERSECRETVALUE")
        assert _BEARER not in failed
        second = _format_result(_result(raw))
        assert "去重" in second
        assert "Full output saved to:" not in second

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RXYCODE_DATA_DIR", "rel-data")
        relative = _format_result(_result("RELATIVE-MARKER\n" + ("q" * 40000)))
        relative_path = _path_from(relative)
        assert relative_path.is_absolute()
        assert relative_path.is_file()
        assert "RELATIVE-MARKER" in relative_path.read_text(encoding="utf-8")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        from RxyCode.RxyCode1_1_0.tools.read import read_file

        page = read_file(str(relative_path), offset=1, limit=1)
        assert "RELATIVE-MARKER" in page
    finally:
        reset_session_binding(token)
        spill = spill_dir
        if spill.exists():
            for child in spill.iterdir():
                child.unlink()
            spill.rmdir()
        assert not spill.exists()


def test_u_f5_9_02_write_failure_falls_back_without_raising(monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import bash as bash_mod

    def boom(path, text):
        del path, text
        raise OSError("disk full")

    monkeypatch.setattr(bash_mod, "_write_spill_file", boom)
    token = bind_session("spill-unit-02")
    try:
        raw = _raw()
        text = _format_result(_result(raw))
        assert "Full output saved to:" not in text
        assert "spill write failed" in text
        assert "MIDDLE-MARKER" not in text
        assert len(text) < len(raw)

        def data_dir_boom():
            raise OSError("data dir unwritable")

        monkeypatch.setattr(bash_mod, "get_data_dir", data_dir_boom)
        degraded = _format_result(_result(raw + "\nsecond-distinct"))
        assert "Full output saved to:" not in degraded
        assert "spill write failed" in degraded
        assert "MIDDLE-MARKER" not in degraded
    finally:
        reset_session_binding(token)


def test_u_f5_9_03_tombstone_keeps_spill_path_and_drops_inline_promise():
    spilled = "head preview\nFull output saved to: D:/data/spill/sess/abc.txt\ntail"
    inline = "just a short tool result"
    messages = [
        AIMessage(content="a", tool_calls=[{"id": "s", "name": "bash", "args": {}}]),
        ToolMessage(content=spilled, tool_call_id="s"),
        AIMessage(content="b", tool_calls=[{"id": "i", "name": "bash", "args": {}}]),
        ToolMessage(content=inline, tool_call_id="i"),
    ]
    out, _tel = microcompact_messages(messages, keep_recent=0)
    by_id = {message.tool_call_id: str(message.content) for message in out if message.type == "tool"}
    assert "Full output saved to:" in by_id["s"]
    assert "D:/data/spill/sess/abc.txt" in by_id["s"]
    assert by_id["i"] == TOOL_RESULT_TOMBSTONE
    assert "可再 Read" not in by_id["i"]
    source = Path("core/compaction.py").read_text(encoding="utf-8")
    assert "模型可再 Read" not in source
    late = _truncate_output(_raw())
    assert "MIDDLE-MARKER" not in late
    again, tel = microcompact_messages(out, keep_recent=0)
    assert tel["tombstoned"] == 0
    assert tel["cleared_texts"] == []
    again_by_id = {
        message.tool_call_id: str(message.content) for message in again if message.type == "tool"
    }
    assert "D:/data/spill/sess/abc.txt" in again_by_id["s"]
    folded = compact_messages(
        [
            HumanMessage(content="start"),
            AIMessage(content="ran", tool_calls=[{"id": "s", "name": "bash", "args": {}}]),
            ToolMessage(content=by_id["s"], tool_call_id="s"),
            HumanMessage(content="later one"),
            HumanMessage(content="later two"),
        ],
        tail_turns=2,
    )
    visible = "\n".join(str(getattr(message, "content", "") or "") for message in folded)
    assert "D:/data/spill/sess/abc.txt" in visible


def _cleanup(session: str) -> None:
    spill = get_data_dir() / "spill" / session
    if spill.exists():
        for child in spill.iterdir():
            child.unlink()
        spill.rmdir()
    assert not spill.exists()


async def test_mo_f5_9_01_real_bash_spills_before_the_clean_limit():
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.bash import bash_tool
    from RxyCode.RxyCode1_1_0.tools.read import read_file

    session = "spill-mo-01"
    token = bind_session(session)
    try:
        ToolOrchestrator.clear_live_dedup()
        orchestrator = ToolOrchestrator()
        orchestrator.register("bash", bash_tool)
        command = "python -c \"print('A'*20000 + 'MIDDLE-MARKER' + 'B'*25000)\""
        text = await orchestrator.execute_tool("bash", {"command": command})
        path = _path_from(text)
        stored = path.read_text(encoding="utf-8")
        assert "MIDDLE-MARKER" in stored
        assert "MIDDLE-MARKER" not in text
        assert "Full output saved to:" in text
        page = read_file(str(path), offset=1, limit=1)
        assert page.startswith("1:")
        assert "AAAA" in page
        late = ToolOrchestrator._clean_tool_output(stored)
        assert "MIDDLE-MARKER" not in late
        assert len(late) < len(stored)
    finally:
        reset_session_binding(token)
        _cleanup(session)


async def test_e_f5_e2e_06_spill_read_tombstone_and_dedupe():
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.bash import bash_tool
    from RxyCode.RxyCode1_1_0.tools.read import read_file

    session = "spill-e2e-06"
    token = bind_session(session)
    try:
        ToolOrchestrator.clear_live_dedup()
        orchestrator = ToolOrchestrator()
        orchestrator.register("bash", bash_tool)
        command = "python -c \"print('A'*20000 + 'MIDDLE-MARKER' + 'B'*25000)\""
        first = await orchestrator.execute_tool("bash", {"command": command})
        path = _path_from(first)
        stored = path.read_text(encoding="utf-8")
        assert "MIDDLE-MARKER" in stored
        assert "MIDDLE-MARKER" not in first
        assert "Full output saved to:" in first
        page = read_file(str(path), offset=1, limit=1)
        assert page.startswith("1:")
        messages = [
            AIMessage(content="a", tool_calls=[{"id": "s", "name": "bash", "args": {}}]),
            ToolMessage(content=first, tool_call_id="s"),
            AIMessage(content="b", tool_calls=[{"id": "i", "name": "bash", "args": {}}]),
            ToolMessage(content="inline small", tool_call_id="i"),
        ]
        out, _tel = microcompact_messages(messages, keep_recent=0)
        by_id = {
            message.tool_call_id: str(message.content) for message in out if message.type == "tool"
        }
        assert "Full output saved to:" in by_id["s"]
        assert str(path) in by_id["s"]
        again = read_file(str(path), offset=1, limit=1)
        assert again.startswith("1:")
        assert by_id["i"] == TOOL_RESULT_TOMBSTONE
        assert "Full output saved to:" not in by_id["i"]
        ToolOrchestrator.clear_live_dedup()
        second = await orchestrator.execute_tool("bash", {"command": command})
        assert "已去重" in second
        assert "Full output saved to:" not in second
        assert "重复调用已跳过" not in second
    finally:
        reset_session_binding(token)
        _cleanup(session)
