"""按 ModelCapabilities.tokenizer 规格估算 token 数。

规格格式：
  "tiktoken:<encoding_name>"  用 tiktoken 具名编码（精确）
  "chars:<ratio>"             字符数 / ratio（无官方分词器时的兜底估算）

tiktoken 的 encoding 对象构造开销不小，按名字缓存。
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

#: tiktoken 不可用或规格无法解析时的兜底比例。
_FALLBACK_RATIO = 4.0


@lru_cache(maxsize=16)
def _get_tiktoken_encoding(name: str):
    try:
        import tiktoken
    except ImportError:
        return None
    try:
        return tiktoken.get_encoding(name)
    except (ValueError, KeyError):
        return None


def _coerce_text(text: Any) -> str:
    if text is None:
        return ""
    if isinstance(text, str):
        return text
    try:
        return str(text)
    except Exception:
        return ""


def _coerce_spec(spec: Any) -> str:
    if spec is None:
        return ""
    if isinstance(spec, str):
        return spec
    try:
        return str(spec)
    except Exception:
        return ""


def _parse_chars_ratio(raw: str) -> float:
    try:
        ratio = float(raw)
    except (ValueError, TypeError):
        return _FALLBACK_RATIO
    if not math.isfinite(ratio) or ratio <= 0:
        return _FALLBACK_RATIO
    return ratio


def _char_estimate(text: str, ratio: float) -> int:
    try:
        return int(len(text) / ratio) + 1
    except (ValueError, OverflowError, ZeroDivisionError):
        return int(len(text) / _FALLBACK_RATIO) + 1


def count_tokens(text: str, spec: str) -> int:
    """按 *spec* 估算 *text* 的 token 数。

    永不抛异常：任何解析失败都退化为字符比估算，因为 token 计数只用于
    压缩时机和显示，估错不应该让请求失败。
    """
    text = _coerce_text(text)
    spec = _coerce_spec(spec)
    if not text:
        return 0

    try:
        if spec.startswith("tiktoken:"):
            encoding = _get_tiktoken_encoding(spec.split(":", 1)[1])
            if encoding is not None:
                return len(encoding.encode(text, disallowed_special=()))
            return _char_estimate(text, _FALLBACK_RATIO)

        if spec.startswith("chars:"):
            ratio = _parse_chars_ratio(spec.split(":", 1)[1])
            return _char_estimate(text, ratio)

        return _char_estimate(text, _FALLBACK_RATIO)
    except Exception:
        return _char_estimate(text, _FALLBACK_RATIO)
