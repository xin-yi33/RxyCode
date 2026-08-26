"""FX2 · TurnRouter behavior-equivalent extraction (PHASE-FIX §5 FX2).

The _run_impl heuristic waterfall must be a single route() table now;
these tests pin the extracted decisions.
"""

from __future__ import annotations

from RxyCode.RxyCode1_1_0.core.request_routing import RoutingDirective
from RxyCode.RxyCode1_1_0.core.turn_router import route


def test_hello_is_chat():
    d = route("你好", "build", RoutingDirective.AUTO, file_op=None, download=None)
    assert d.path == "chat"
    assert d.profile_kind == "chat"
    assert d.skip_await == frozenset({"memory.initialize", "session.load", "mcp.refresh"})
    assert "memory.initialize" in d.skip_await
    assert "session.load" in d.skip_await


def test_hello_ah_is_chat():
    """FX6: wide social (incl. 你好啊) rides the frozen ChatPrefix."""
    d = route("你好啊", "build", RoutingDirective.AUTO, file_op=None, download=None)
    assert d.path == "chat"
    assert "session.load" in d.skip_await


def test_declines_tools_is_chat():
    text = "用三句话规划成都两日美食游，不要改文件，不要调用工具。"
    d = route(text, "build", RoutingDirective.AUTO, file_op=None, download=None)
    assert d.path == "chat"


def test_code_task_is_agent():
    d = route(
        "列出当前目录的代码并修改 calc.py 的 bug。",
        "build",
        RoutingDirective.AUTO,
        file_op=None,
        download=None,
    )
    assert d.path == "agent"


def test_full_directive_is_graph():
    d = route(
        "explain decorators",
        "build",
        RoutingDirective.FORCE_FULL,
        file_op=None,
        download=None,
    )
    assert d.path == "graph"


def test_plan_mode_is_plan():
    d = route("写一个计划", "plan", RoutingDirective.AUTO, file_op=None, download=None)
    assert d.path == "plan"


def test_file_op_is_file_op():
    d = route(
        "创建 hello.txt",
        "build",
        RoutingDirective.AUTO,
        file_op={"action": "create"},
        download=None,
    )
    assert d.path == "file_op"


def test_download_is_download():
    d = route(
        "下载报表",
        "build",
        RoutingDirective.AUTO,
        file_op=None,
        download=("http://x/report.xlsx", "report.xlsx"),
    )
    assert d.path == "download"


def test_force_full_skips_chat_fast_paths():
    d = route("你好", "build", RoutingDirective.FORCE_FULL, file_op=None, download=None)
    assert d.path == "graph"


def test_who_are_you_is_chat():
    d = route("你是谁？", "build", RoutingDirective.AUTO, file_op=None, download=None)
    assert d.path == "chat"
    assert d.profile_kind == "chat"
    assert "session.load" in d.skip_await


def test_who_wrote_this_code_stays_agent():
    d = route(
        "你是谁写的这段代码",
        "build",
        RoutingDirective.AUTO,
        file_op=None,
        download=None,
    )
    assert d.path == "agent"
