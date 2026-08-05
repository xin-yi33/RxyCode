"""P6 request routing: explicit directives and inventory coverage."""

from RxyCode.RxyCode1_1_0.core.request_routing import (
    ROUTING_INVENTORY,
    RoutingDirective,
    has_structured_pipeline_signal,
    is_simple_query,
    parse_routing_directive,
)


def test_routing_inventory_has_twenty_five_sites():
    assert len(ROUTING_INVENTORY) == 25


def test_full_directive_forces_complex_path():
    directive, stripped = parse_routing_directive("/full explain decorators")
    assert directive == RoutingDirective.FORCE_FULL
    assert stripped == "explain decorators"
    assert is_simple_query(stripped, directive=directive) is False


def test_pipeline_alias_forces_complex_path():
    directive, stripped = parse_routing_directive("/pipeline build auth service")
    assert directive == RoutingDirective.FORCE_FULL
    assert is_simple_query(stripped, directive=directive) is False


def test_fast_directive_forces_simple_path_even_for_game_request():
    directive, stripped = parse_routing_directive("/fast 写一个跑酷小游戏")
    assert directive == RoutingDirective.FORCE_FAST
    assert is_simple_query(stripped, directive=directive) is True


def test_auto_keeps_parkour_game_on_tool_pipeline():
    assert is_simple_query("帮我写一个跑酷小游戏") is False


def test_auto_keeps_plain_chat_simple():
    assert is_simple_query("what happened?") is True


def test_file_bugfix_request_uses_full_path():
    text = (
        "当前目录下有一个 calc.py，"
        "请修复 sum_up_to(n) 的 off-by-one bug，"
        "然后运行 pytest。"
    )
    assert has_structured_pipeline_signal(text) is True
    assert is_simple_query(text) is False


def test_mutable_default_bugfix_request_uses_full_path():
    text = (
        "当前目录下的 cart.py 里 Cart 类使用了可变默认参数 items=[]，"
        "请修复这个经典 bug，然后运行 python -m pytest test_cart.py -q 确认通过。"
    )
    assert has_structured_pipeline_signal(text) is True
    assert is_simple_query(text) is False


def test_relative_py_mention_without_modify_stays_simple():
    assert has_structured_pipeline_signal("calc.py is a common filename") is False
    assert is_simple_query("what does calc.py usually contain?") is True


def test_agent_v2_compat_routing_reexports():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import (
        GIT_ONLY_TOOL_NAMES,
        _GIT_FORCE_RE,
        _PURE_SOCIAL_GREETING_RE,
    )

    assert _PURE_SOCIAL_GREETING_RE.match("hello")
    assert "git" in GIT_ONLY_TOOL_NAMES
    assert _GIT_FORCE_RE.search("必须调用 git 工具")
