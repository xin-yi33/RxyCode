"""B9: per-model 缓存契约层（model_catalog.json cache_contract 唯一入口）。

9 家 provider 的缓存模式/命中折扣/TTL/断点/usage 字段/reasoning 契约各不相同，
通配适配=静默失效（向 DeepSeek 注入 cache_control、向 MiMo 丢 reasoning、
向 Kimi 不传 prompt_cache_key 都是"没报错但缓存归零"）。

本模块是**唯一**契约读取入口：B2 断点分派 / B3 TTL / B4 压缩决策 / B6 token
治理一律经此，禁止在 core/providers/ 等散落 if-elif 判模型代码。

未识别模型 → 返回 None / 0（CB8：调用方兜底为现状行为）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: 契约目录（与 model_catalog.json 同源）。
_CATALOG_PATH = Path(__file__).resolve().parents[1] / "config" / "model_catalog.json"

#: Dotted catalog spellings → official API ids.  Sonnet 4.5 is not Sonnet 5.
_ANTHROPIC_MODEL_ALIASES: dict[str, str] = {
    "claude-sonnet-4.5": "claude-sonnet-4-5",
    "claude-haiku-4.5": "claude-haiku-4-5",
}

#: 模块级缓存：provider:model -> cache_contract（或 None）。
_contracts: dict[str, dict | None] | None = None


def canonical_model_id(provider_id: str, model_id: str) -> str:
    """Return the runtime/API model id for a catalog or user-facing alias."""
    pid = str(provider_id or "").strip().casefold()
    mid = str(model_id or "").strip().casefold()
    if pid == "anthropic":
        return _ANTHROPIC_MODEL_ALIASES.get(mid, mid)
    return mid


def _load_contracts() -> dict[str, dict | None]:
    """加载全部 cache_contract 索引；文件缺失/损坏 → 空索引（CB8）。"""
    global _contracts
    if _contracts is not None:
        return _contracts
    index: dict[str, dict | None] = {}
    try:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        for record in data.get("records", []):
            provider = str(record.get("provider_id") or "").strip().casefold()
            model = str(record.get("model_id") or "").strip().casefold()
            contract = record.get("cache_contract")
            if not provider or not model:
                continue
            stored = contract if isinstance(contract, dict) else None
            keys = {model, canonical_model_id(provider, model)}
            if provider == "anthropic":
                canon = canonical_model_id(provider, model)
                for alias, target in _ANTHROPIC_MODEL_ALIASES.items():
                    if target == canon or alias == model or target == model:
                        keys.add(alias)
                        keys.add(target)
            for key in keys:
                index.setdefault(f"{provider}:{key}", stored)
    except (OSError, ValueError, KeyError):
        pass
    _contracts = index
    return _contracts


def reset_contract_cache() -> None:
    """清空契约缓存（测试 / 热加载用）。"""
    global _contracts
    _contracts = None


def get_contract(provider_id: str, model_id: str) -> dict | None:
    """返回 provider:model 的 cache_contract；未识别 → None（CB8）。

    大小写/空白不敏感（与 model_catalog 的 normalize_model_key 一致）。
    """
    if not provider_id or not model_id:
        return None
    pid = provider_id.strip().casefold()
    raw = model_id.strip().casefold()
    index = _load_contracts()
    canon = canonical_model_id(pid, raw)
    return index.get(f"{pid}:{canon}") or index.get(f"{pid}:{raw}")


def _read_path(usage: dict, path: str | None) -> int:
    """按点分路径从 usage dict 读取 int 值；缺失/非 int → 0。"""
    if not path:
        return 0
    node: Any = usage
    for part in path.split("."):
        if not isinstance(node, dict):
            return 0
        node = node.get(part)
    return node if isinstance(node, int) and node >= 0 else 0


def read_cached_tokens(provider_id: str, model_id: str, usage: dict) -> int:
    """按契约 usage_fields.cached / cached_alt 读取缓存命中 token 数。

    双路径取 max：Chat Completions 可能回平铺或 nested。cached_alt 缺省为 0。
    禁止按厂商名 if。未识别模型 / 字段缺失 → 0。
    """
    contract = get_contract(provider_id, model_id)
    if contract is None:
        return 0
    fields = contract.get("usage_fields") or {}
    return max(
        _read_path(usage, fields.get("cached")),
        _read_path(usage, fields.get("cached_alt")),
    )


def read_reasoning_tokens(provider_id: str, model_id: str, usage: dict) -> int:
    """读取 reasoning token 数（Grok/MiMo 单独计费，规范 8）。"""
    contract = get_contract(provider_id, model_id)
    if contract is None:
        return 0
    return _read_path(
        usage, contract.get("usage_fields", {}).get("reasoning")
    )


def read_cost_ticks(provider_id: str, model_id: str, usage: dict) -> int:
    """读取服务端权威成本 ticks（Grok cost_in_usd_ticks，1 tick=1e-10 USD）。"""
    contract = get_contract(provider_id, model_id)
    if contract is None:
        return 0
    return _read_path(
        usage, contract.get("usage_fields", {}).get("cost_ticks")
    )


def hit_discount(provider_id: str, model_id: str) -> float | None:
    """命中价/未命中价折扣；未识别 → None（CB8）。"""
    contract = get_contract(provider_id, model_id)
    if contract is None:
        return None
    return contract.get("cache_hit_discount")


def reasoning_contract(provider_id: str, model_id: str) -> str | None:
    """reasoning 契约：mandatory_echo | thinking_blocks_echo | none | no_thinking。"""
    contract = get_contract(provider_id, model_id)
    if contract is None:
        return None
    return contract.get("reasoning_contract")


def temperature_override(provider_id: str, model_id: str) -> dict | None:
    """thinking 开启时的温度/top_p 强制值（MiMo 1.0/0.95，规范 2）。"""
    contract = get_contract(provider_id, model_id)
    if contract is None:
        return None
    return contract.get("temperature_override")


def injects_cache_control(contract: dict | None) -> bool:
    """Unknown and implicit families never emit Anthropic cache_control."""
    if not contract:
        return False
    mode = str(contract.get("cache_mode") or "auto").casefold()
    if mode != "explicit_breakpoints":
        return False
    return int(contract.get("breakpoints_max") or 0) > 0


def injects_prompt_cache_key(contract: dict | None) -> bool:
    if not contract:
        return False  # 未知模型默认不发 key（§15.3）
    return bool(contract.get("prompt_cache_key_required"))


def unknown_fallback_contract() -> dict:
    """Documented contract for models without a catalog record (FXC6/§15.3).

    Five-point fallback:
      1. Prompt -> default variant (``prompt_variant: "default"``), never a
         guess by id
      2. Protocol -> openai-compatible (``protocol: "openai-compatible"``)
      3. NEVER inject ``cache_control`` (implicit prefix only; never treat
         an unknown model as Claude or invent breakpoints)
      4. still sort tools by name and send session affinity headers
      5. ``prompt_cache_key`` is NOT sent by default

    Callers that receive ``get_contract() -> None`` must behave exactly as
    if this contract were in effect — ``injects_cache_control`` /
    ``injects_prompt_cache_key`` already return False for ``None``.
    """
    return {
        "cache_mode": "auto",
        "breakpoints_max": 0,
        "prompt_cache_key_required": False,
        "prompt_variant": "default",
        "protocol": "openai-compatible",
    }


def requires_prompt_cache_key(provider_id: str, model_id: str) -> bool:
    """是否要求请求级 prompt_cache_key（Kimi 必填，规范 5）。"""
    return injects_prompt_cache_key(get_contract(provider_id, model_id))
