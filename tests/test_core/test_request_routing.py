"""P6 request routing: explicit directives and inventory coverage."""

from RxyCode.RxyCode1_1_0.core.request_routing import (
    ROUTING_INVENTORY,
    RoutingDirective,
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
