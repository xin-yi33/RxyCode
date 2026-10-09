"""模型输出上限解析契约（Phase 3）。

职责边界（见 00-EXECUTION-PLAN.md §7.0.1）：
- Phase A 的 ``ModelCapabilities.max_output_tokens`` 是"能力调研值"，不是"请求值"；
- 本模块回答"这次请求最终发多少 max_tokens"，产出 ``OutputLimitResolution.resolved_max_tokens``。
  用户显式配置、模型目录/能力值、Provider 默认、未知模型兜底和上下文钳制
  在这里组合成唯一进入 SDK 的值。

解析优先级（§7.2 冻结）：
1. explicit_config   用户显式 max_tokens 正整数
2. catalog_exact_provider  provider_id + model_id 精确目录项
3. catalog_exact_model     model_id 精确目录项（无 Provider 冲突时）
4. catalog_family         已审计的 family pattern
5. provider_default       Provider 明确默认
6. unknown_fallback       未知模型高位兜底（默认 32768，不再回退 8192）

另：``context_cap`` / ``explicit_clamped`` 是钳制后的来源标注。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注
    from .model_catalog import ModelCatalog

LimitSource = Literal[
    "explicit_config",
    "catalog_exact_provider",
    "catalog_exact_model",
    "catalog_family",
    "provider_default",
    "unknown_fallback",
    "context_cap",
    "explicit_clamped",
]

#: 未知模型高位兜底默认值（§7.2 优先级 6；不再回退 8192）。
UNKNOWN_MODEL_FALLBACK = 32_768
#: 上下文安全余量默认（token）。
DEFAULT_CONTEXT_SAFETY_MARGIN = 1024

#: 结构化错误码（§7.2）。
MODEL_CONTEXT_BUDGET_EXHAUSTED = "MODEL_CONTEXT_BUDGET_EXHAUSTED"
MODEL_METADATA_NOT_FOUND = "MODEL_METADATA_NOT_FOUND"
MODEL_OUTPUT_LIMIT_REJECTED = "MODEL_OUTPUT_LIMIT_REJECTED"


class ModelLimitError(Exception):
    """Structured error carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ModelLimitRecord:
    """版本化模型目录中的一条能力记录（§7.2 目录层）。"""

    provider_id: str
    model_id: str
    model_context_window: int | None
    model_max_output_tokens: int | None
    source: str
    source_url: str | None
    as_of: str | None


@dataclass(frozen=True)
class OutputLimitResolution:
    """一次请求的最终输出上限解析结果。"""

    provider_id: str
    model_id: str
    requested_max_tokens: int | None
    resolved_max_tokens: int
    context_window: int | None
    estimated_input_tokens: int | None
    source: LimitSource
    matched_catalog_key: str | None
    warnings: tuple[str, ...]


def normalize_model_key(value: str) -> str:
    """目录查找键：小写去空白。发请求仍用原始 model_id。"""
    return (value or "").strip().casefold()


def _validate_positive_int(value: int | None, field: str, *, allow_zero: bool = False) -> None:
    if value is None:
        return
    if not isinstance(value, int) or value < (0 if allow_zero else 1):
        cmp = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field} must be a {cmp} integer, got {value!r}")


def resolve_output_limit(
    *,
    provider_id: str,
    model_id: str,
    configured_max_tokens: int | str | None,
    catalog_record: ModelLimitRecord | None,
    provider_default: int | None,
    input_tokens: int | None,
    context_safety_margin: int = DEFAULT_CONTEXT_SAFETY_MARGIN,
    catalog_max_age_days: int | None = None,
) -> OutputLimitResolution:
    """按冻结优先级解析一次请求的输出上限。

    - ``configured_max_tokens``：int = 用户显式覆盖；"auto" / None = 走目录解析。
    - 返回的 ``resolved_max_tokens`` 是唯一允许进入 SDK 的值。
    - 已知 ``context_window`` 时还会按输入 token + 安全余量钳制；
      钳制结果 < 1 时抛 ``ModelLimitError(MODEL_CONTEXT_BUDGET_EXHAUSTED)``。
    """
    provider_id = (provider_id or "").strip()
    model_id = (model_id or "").strip()
    if not provider_id or not model_id:
        raise ValueError("provider_id and model_id are required")
    if not isinstance(context_safety_margin, int) or context_safety_margin < 0:
        raise ValueError("context_safety_margin must be a non-negative integer")
    _validate_positive_int(input_tokens, "input_tokens", allow_zero=True)
    _validate_positive_int(provider_default, "provider_default")
    # 允许调用方传 dict 形态的目录记录（与 ModelCatalog.add_record 一致）。
    if catalog_record is not None and not isinstance(catalog_record, ModelLimitRecord):
        if isinstance(catalog_record, dict):
            catalog_record = ModelLimitRecord(
                provider_id=str(catalog_record.get("provider_id") or ""),
                model_id=str(catalog_record.get("model_id") or ""),
                model_context_window=catalog_record.get("model_context_window"),
                model_max_output_tokens=catalog_record.get("model_max_output_tokens"),
                source=str(catalog_record.get("source") or ""),
                source_url=catalog_record.get("source_url"),
                as_of=catalog_record.get("as_of"),
            )
        else:
            raise TypeError(
                "catalog_record must be a ModelLimitRecord or dict; "
                f"got {type(catalog_record).__name__}"
            )

    warnings: list[str] = []
    matched_key: str | None = None
    context_window: int | None = None
    source: LimitSource

    # 1. 用户显式覆盖
    if isinstance(configured_max_tokens, int):
        _validate_positive_int(configured_max_tokens, "configured_max_tokens")
        selected = configured_max_tokens
        source = "explicit_config"
        # 已知硬上限钳制（优先级 1 说明：超硬上限只能钳并记 warning）
        if catalog_record is not None:
            cap = catalog_record.model_max_output_tokens
            context_window = catalog_record.model_context_window
            if cap is not None and cap > 0 and selected > cap:
                warnings.append(
                    f"explicit max_tokens {selected} exceeds known hard limit "
                    f"{cap}; clamped"
                )
                selected = cap
                source = "explicit_clamped"
        if context_window is None and catalog_record is not None:
            context_window = catalog_record.model_context_window
    elif configured_max_tokens == "auto" or configured_max_tokens is None:
        # 2. catalog 精确 provider+id
        if catalog_record is not None:
            context_window = catalog_record.model_context_window
            cap = catalog_record.model_max_output_tokens
            matched_key = f"{provider_id}:{model_id}"
            # 精确命中即 source=catalog_exact_provider；cap 未知时
            # resolved 由 provider_default / unknown_fallback 兜底，
            # 但来源标注仍体现"目录命中"。
            source = "catalog_exact_provider"
            _warn_if_source_stale(catalog_record, warnings, catalog_max_age_days)
            if cap is not None:
                selected = cap
            else:
                selected = None
        else:
            selected = None
            source = "provider_default" if provider_default is not None else "unknown_fallback"
        if selected is None:
            # catalog 命中时 source 保持 catalog_exact_provider；值从
            # provider_default / unknown_fallback 兜底（matched_key 保留）。
            selected = (
                provider_default
                if provider_default is not None
                else UNKNOWN_MODEL_FALLBACK
            )
            if source == "unknown_fallback" and provider_default is not None:
                source = "provider_default"
    else:
        raise ValueError(
            "configured_max_tokens must be a positive integer, 'auto', or None; "
            f"got {configured_max_tokens!r}"
        )

    # context window 钳制（§7.2）
    if context_window is not None and context_window > 0:
        effective_cap = context_window - (input_tokens or 0) - context_safety_margin
        if effective_cap < 1:
            raise ModelLimitError(
                MODEL_CONTEXT_BUDGET_EXHAUSTED,
                "effective_max_tokens < 1 after context clamping; "
                "request budget exhausted",
            )
        if selected > effective_cap:
            warnings.append(
                f"output limit {selected} exceeds context budget "
                f"{effective_cap}; clamped"
            )
            selected = effective_cap
            if source != "explicit_clamped":
                source = "context_cap"

    if selected < 1:
        raise ModelLimitError(
            MODEL_CONTEXT_BUDGET_EXHAUSTED,
            "effective_max_tokens < 1 after context clamping; "
            "request budget exhausted",
        )

    return OutputLimitResolution(
        provider_id=provider_id,
        model_id=model_id,
        requested_max_tokens=(
            configured_max_tokens
            if isinstance(configured_max_tokens, int)
            else None
        ),
        resolved_max_tokens=selected,
        context_window=context_window,
        estimated_input_tokens=input_tokens,
        source=source,
        matched_catalog_key=matched_key,
        warnings=tuple(warnings),
    )


#: 惰性加载的全局目录实例（跨请求共享，避免每次请求都读 JSON）。
_catalog_cache: ModelCatalog | None = None


def _global_catalog() -> ModelCatalog:
    """返回全局 ModelCatalog（惰性加载，缓存）。"""
    global _catalog_cache
    if _catalog_cache is None:
        from .model_catalog import ModelCatalog as _Catalog

        _catalog_cache = _Catalog.load()
    return _catalog_cache


def resolve_configured_max_tokens(
    *,
    model_config: dict,
    capability_max_output_tokens: int | None,
    configured_max_tokens: int | str | None,
    model_limits_config: dict | None = None,
    input_tokens: int | None = None,
    catalog: ModelCatalog | None = None,
) -> OutputLimitResolution:
    """高层接线辅助：从 model_config + 全局目录组合解析请求上限。

    供 ``llm_kwargs`` 与 ``_raw_stream`` 复用（Phase 3 M4）：
    - ``model_config`` 含 provider_id / model_name / max_tokens / base_url；
    - ``capability_max_output_tokens`` 来自 Provider 的 ``ModelCapabilities``
      （Phase A 能力调研值），作为 ``provider_default`` 之外的目录来源之一；
    - ``configured_max_tokens`` 是用户配置的 max_tokens（int / "auto" / None）；
    - ``model_limits_config`` 是 config 的 ``model_limits`` 段
      （unknown_model_max_tokens / context_safety_margin_tokens）。

    返回值只允许 ``resolved_max_tokens`` 进入 SDK。
    """
    provider_id = str(model_config.get("provider_id") or "").strip()
    model_id = str(model_config.get("model_name") or model_config.get("model_name") or "").strip()
    if not model_id:
        raise ValueError("model_config must include model_name (provider model id)")

    limits_cfg = model_limits_config or {}
    unknown_fallback = int(limits_cfg.get("unknown_model_max_tokens", 32768) or 0)
    if unknown_fallback <= 0:
        unknown_fallback = 32768
    margin = int(limits_cfg.get("context_safety_margin_tokens", 1024) or 0)
    if margin < 0:
        margin = 1024
    max_age = limits_cfg.get("catalog_max_age_days")
    if max_age is None:
        max_age = 90  # 来源超过 90 天视为过期（可配置）
    try:
        max_age = int(max_age)
    except (TypeError, ValueError):
        max_age = 90
    if max_age <= 0:
        max_age = None  # 0 或负数 = 不检查过期

    catalog = catalog if catalog is not None else _global_catalog()
    catalog_record = None
    if catalog is not None:
        catalog_record, _matched_key, _family_pattern = catalog.lookup(
            provider_id, model_id
        )

    # provider_default：能力调研值优先，其次才是全局兜底
    provider_default = capability_max_output_tokens

    resolution = resolve_output_limit(
        provider_id=provider_id or "unknown",
        model_id=model_id,
        configured_max_tokens=configured_max_tokens,
        catalog_record=catalog_record,
        provider_default=provider_default,
        input_tokens=input_tokens,
        context_safety_margin=margin,
        catalog_max_age_days=max_age,
    )
    return resolution


# 废弃代码（2026-10-09 死代码复核）：全仓零调用（含 tests，docstring 自称
# 测试用但无测试在用）——目录缓存随进程生命周期失效；测试如需重置，直接
# 操作模块内 `_catalog_cache`，勿新调用。
def reset_catalog_cache() -> None:
    """清空目录缓存（测试用）。"""
    global _catalog_cache
    _catalog_cache = None


def _warn_if_source_stale(
    record: ModelLimitRecord,
    warnings: list[str],
    catalog_max_age_days: int | None,
) -> None:
    """ML6：目录来源过期/缺失 as_of 时追加可解释 warning（不静默降级）。

    - ``as_of`` 缺失 → warning（来源不可核验时点）。
    - ``as_of`` 超过 ``catalog_max_age_days``（默认 90）→ warning。
    仅追加 warning，不改变 source（目录命中仍可信，但调用方可感知过期）。
    """
    from datetime import date, datetime

    max_age = 90
    if catalog_max_age_days is not None and catalog_max_age_days > 0:
        max_age = catalog_max_age_days

    as_of = record.as_of
    if not as_of:
        warnings.append(
            f"catalog source for {record.provider_id}:{record.model_id} "
            "has no as_of date; staleness cannot be verified"
        )
        return
    try:
        parsed = datetime.strptime(as_of, "%Y-%m-%d").date()
    except ValueError:
        warnings.append(
            f"catalog source as_of={as_of!r} is not a valid YYYY-MM-DD date"
        )
        return
    age = (date.today() - parsed).days
    if age > max_age:
        warnings.append(
            f"catalog source for {record.provider_id}:{record.model_id} "
            f"is {age} days old (as_of={as_of}, max allowed {max_age}); "
            "consider refreshing"
        )
