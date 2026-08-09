"""Provider 注册表。

解析顺序：
  1. model_config 里显式写了 "provider" 字段 → 按名字直取
  2. 依次问每个已注册 provider 的 matches(base_url, model_name)
  3. 全部落空 → OpenAIProvider（行为等同 Phase A 之前）
"""

from __future__ import annotations

from functools import lru_cache

from .anthropic import AnthropicProvider
from .base import BaseProvider
from .deepseek import DeepSeekProvider
from .doubao import DoubaoProvider
from .openai import OpenAIProvider
from .qwen import QwenProvider

_FALLBACK = OpenAIProvider()

#: 注册顺序即匹配优先级。越具体的越靠前。
_PROVIDERS: list[BaseProvider] = [
    DeepSeekProvider(),
    DoubaoProvider(),
    AnthropicProvider(),
    QwenProvider(),
]

_BY_NAME: dict[str, BaseProvider] = {p.name: p for p in _PROVIDERS}
_BY_NAME[_FALLBACK.name] = _FALLBACK


def resolve(model_config: dict) -> BaseProvider:
    """为一份模型配置选出 provider。"""
    explicit = str(model_config.get("provider") or "").strip().lower()
    if explicit and explicit in _BY_NAME:
        return _BY_NAME[explicit]

    base_url = str(model_config.get("base_url") or "")
    model_name = str(model_config.get("model_name") or "")
    for provider in _PROVIDERS:
        if provider.matches(base_url, model_name):
            return provider
    return _FALLBACK


def get_by_name(name: str) -> BaseProvider | None:
    return _BY_NAME.get(name.strip().lower())


def list_providers() -> list[str]:
    return sorted(_BY_NAME)


@lru_cache(maxsize=256)
def _cached_caps_key(base_url: str, model_name: str, provider_hint: str) -> str:
    """capabilities 解析的缓存键。provider 无状态，结果可安全缓存。"""
    return f"{provider_hint}|{base_url}|{model_name}"


__all__ = ["BaseProvider", "resolve", "get_by_name", "list_providers"]
