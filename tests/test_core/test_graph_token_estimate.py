"""layer=unit/module F4-9 graph token 估算统一 tiktoken。"""
from __future__ import annotations

import inspect

SAMPLES = [
    "hello world " * 100,
    "中文密集文本" * 80,
    "def f(x):\n    return x * 2\n" * 30,
    "",
]


def test_u_f4_9_01_graph_estimate_equals_compaction_counter():
    """layer=unit U-F4-9-01
    graph 估算与 core/providers/tokenizers.count_tokens 同值（同一实现，逐样本对表）。
    """
    from RxyCode.RxyCode1_1_0.core.graph import _estimate_text_tokens
    from RxyCode.RxyCode1_1_0.core.providers.tokenizers import count_tokens

    for text in SAMPLES:
        assert _estimate_text_tokens(text, spec="tiktoken:o200k_base") == count_tokens(
            text, "tiktoken:o200k_base"
        )
    # 已知精确值对表（tiktoken o200k_base 编码长度，防实现漂移换库）
    import tiktoken

    enc = tiktoken.get_encoding("o200k_base")
    expected = len(enc.encode(SAMPLES[0], disallowed_special=()))
    assert _estimate_text_tokens(SAMPLES[0], spec="tiktoken:o200k_base") == expected


def test_u_f4_9_02_unknown_spec_falls_back_char_ratio():
    """layer=unit U-F4-9-02
    spec 未知 → 字符比回退：与 count_tokens(unknown) 同值，
    公式精确值 int(len/4)+1（tokenizer 垫底 _FALLBACK_RATIO=4.0，
    core/providers/tokenizers.py:17，非 graph 自写一份）。
    2026-10-01 勘误：初稿误写 int(10/3)+1，与现状 _FALLBACK_RATIO=4.0 矛盾，
    按 scheme-A 修正为 4.0 口径（F4-9 卡「已经替你决定好的」第 4 条同口径）。
    """
    from RxyCode.RxyCode1_1_0.core.graph import _estimate_text_tokens
    from RxyCode.RxyCode1_1_0.core.providers.tokenizers import count_tokens

    for text in SAMPLES:
        assert _estimate_text_tokens(text, spec="unknown-model") == count_tokens(
            text, "unknown-model"
        )
    assert _estimate_text_tokens("0123456789", spec="unknown-model") == int(10 / 4) + 1


def test_mo_f4_9_01_route_next_no_longer_uses_char_div_3():
    """layer=module MO-F4-9-01
    源码门（同 V13/V3 手法）：route_next 不得再含 `// 3` 估算；必须经
    _estimate_text_tokens（或显式 count_tokens）这一份实现。
    """
    from RxyCode.RxyCode1_1_0.core import graph as graph_mod

    src = inspect.getsource(graph_mod.route_next)
    assert "// 3" not in src
    assert "_estimate_text_tokens" in src or "count_tokens" in src
