"""Tokenizer 适配层测试."""

import builtins

import pytest

from core.providers import tokenizers
from core.providers.tokenizers import count_tokens


def test_empty_string_returns_zero():
    assert count_tokens("", "chars:4.0") == 0
    assert count_tokens("", "tiktoken:cl100k_base") == 0
    assert count_tokens(None, "chars:4.0") == 0


def test_chars_path_uses_ratio():
    # 10 chars / 2.0 + 1 = 6
    assert count_tokens("0123456789", "chars:2.0") == 6


def test_chars_path_invalid_ratio_falls_back_to_default():
    text = "abcd"
    expected = int(len(text) / 4.0) + 1
    assert count_tokens(text, "chars:not-a-number") == expected
    assert count_tokens(text, "chars:0") == expected
    assert count_tokens(text, "chars:-1") == expected
    assert count_tokens(text, "chars:nan") == expected
    assert count_tokens(text, "chars:inf") == expected
    assert count_tokens(text, "chars:-inf") == expected


def test_tiktoken_path_uses_encoding():
    text = "hello world"
    exact = count_tokens(text, "tiktoken:cl100k_base")
    fallback = int(len(text) / 4.0) + 1
    assert exact > 0
    # tiktoken 可用时应比纯字符比更精确（通常更少 token）
    assert exact <= fallback


def test_tiktoken_unknown_encoding_falls_back_to_chars_ratio():
    text = "hello"
    expected = int(len(text) / 4.0) + 1
    assert count_tokens(text, "tiktoken:definitely-not-an-encoding") == expected


def test_illegal_spec_falls_back_to_default_ratio():
    text = "hello"
    expected = int(len(text) / 4.0) + 1
    assert count_tokens(text, "unknown:4.0") == expected
    assert count_tokens(text, "") == expected
    assert count_tokens(text, None) == expected


def test_non_string_inputs_are_coerced_without_raising():
    expected = int(len("123") / 4.0) + 1
    assert count_tokens(123, "chars:4.0") == expected
    # 非 str 可强制转换时不应抛异常
    result = count_tokens(["not", "a", "string"], "chars:4.0")
    assert isinstance(result, int) and result >= 0


def test_tiktoken_import_failure_degrades_gracefully(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tiktoken":
            raise ImportError("tiktoken unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    tokenizers._get_tiktoken_encoding.cache_clear()

    text = "hello"
    expected = int(len(text) / 4.0) + 1
    assert count_tokens(text, "tiktoken:cl100k_base") == expected

    tokenizers._get_tiktoken_encoding.cache_clear()


@pytest.mark.parametrize(
    ("text", "spec"),
    [
        ("", "chars:0.7"),
        ("x", "chars:2.0"),
        ("你好世界", "chars:0.7"),
        ("a" * 1000, "chars:4.0"),
        ("emoji 🚀 test", "tiktoken:cl100k_base"),
        ("mixed", "not-a-valid-spec"),
        ("tabs\tand\nnewlines", "chars:bad"),
        ("unicode—dash", "tiktoken:also-bad"),
        ("hello", "chars:nan"),
        ("hello", "chars:inf"),
        (123, "chars:2.0"),
        ("hello", None),
        (None, "chars:4.0"),
        (object(), 42),
    ],
)
def test_count_tokens_never_raises(text, spec):
    """fuzz 风格：任意输入组合都不应抛异常。"""
    result = count_tokens(text, spec)
    assert isinstance(result, int)
    assert result >= 0
