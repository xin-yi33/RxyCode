import httpx
import hmac
import os
import re
import time
from typing import Literal, Optional
from urllib.parse import urlsplit

from .credential_store import delete_credential, store_credential
from .model_endpoint import (
    detect_explicit_transport,
    ensure_resource_path_rewritable,
    infer_transport_from_resource_path,
    llm_endpoint_url,
    normalize_llm_endpoint,
    normalize_resource_path,
    validate_llm_base_url,
)
from .model_transport import (
    ANTHROPIC_MESSAGES_TRANSPORT,
    OPENAI_CHAT_TRANSPORT,
    OPENAI_RESPONSES_TRANSPORT,
    normalize_api_transport,
    normalize_transport_candidates,
)
from .settings import get_config_path, get_model_config, load_config, save_config


DISCOVERY_UNSUPPORTED_MESSAGE = (
    "该服务商未提供 OpenAI 兼容的模型目录（GET /models）。"
    "请改用「自定义」手动填写模型 ID。"
)

# Stable codes for TUI routing. Do not rename without updating DialogAddModel.
DISCOVER_ERROR_UNSUPPORTED = "unsupported_catalogue"
DISCOVER_ERROR_AUTH = "auth"
DISCOVER_ERROR_HTTPS = "https"
DISCOVER_ERROR_INVALID = "invalid"
DISCOVER_ERROR_TRANSPORT = "transport"

# Provider connection presets.
#
# Deliberately provider-level only: id / name / base_url / category.  A preset
# must never carry a concrete model id — model ids are discovered from the live
# provider catalogue (see ``discover_provider_models``) or typed by the user,
# so this table cannot go stale when a vendor renames or retires a model.
PROVIDER_PRESETS: tuple[dict, ...] = (
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "category": "常用"},
    {"id": "moonshot", "name": "Moonshot Kimi", "base_url": "https://api.moonshot.cn/v1", "category": "常用"},
    {"id": "dashscope", "name": "阿里云百炼 / 通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "category": "常用"},
    {"id": "volces_ark", "name": "火山方舟 Ark", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "category": "常用"},
    {"id": "zhipu", "name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4", "category": "常用"},
    {"id": "siliconflow", "name": "SiliconFlow 硅基流动", "base_url": "https://api.siliconflow.cn/v1", "category": "常用"},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "category": "其他"},
    {"id": "zen", "name": "OpenCode Zen", "base_url": "https://opencode.ai/zen/v1", "category": "其他"},
    {"id": "opencode-go", "name": "OpenCode Go", "base_url": "https://opencode.ai/zen/go/v1", "category": "其他"},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "category": "其他"},
    {"id": "groq", "name": "Groq", "base_url": "https://api.groq.com/openai/v1", "category": "其他"},
    {"id": "together", "name": "Together AI", "base_url": "https://api.together.xyz/v1", "category": "其他"},
)

PRESET_FIELDS = ("id", "name", "base_url", "category")


HTTP_CODE_MESSAGES = {
    400: "请求无效。请检查 API URL 和 API Key 是否正确。(HTTP 400 Bad Request)",
    401: "认证失败。API Key 可能错误或已过期。(HTTP 401 Unauthorized)",
    403: "访问被拒绝。API Key 没有访问此模型的权限。(HTTP 403 Forbidden)",
    404: "API 端点未找到。请检查 API URL 是否正确。(HTTP 404 Not Found)",
    405: "方法不允许。该 API 端点可能不支持 chat completions 格式。(HTTP 405 Method Not Allowed)",
    413: "请求太大。模型可能有较小的上下文限制。(HTTP 413 Payload Too Large)",
    422: "请求格式无效。API 可能有不同的参数要求。(HTTP 422 Unprocessable Entity)",
    429: "请求过于频繁，已被限流。请稍后重试。(HTTP 429 Too Many Requests)",
    500: "API 服务器遇到内部错误。请稍后重试。(HTTP 500 Internal Server Error)",
    502: "API 服务器暂时不可用或已宕机。(HTTP 502 Bad Gateway)",
    503: "API 服务器过载或正在维护。(HTTP 503 Service Unavailable)",
    504: "API 服务器超时。可能速度较慢或无法访问。(HTTP 504 Gateway Timeout)",
}


def normalize_provider_base_url(
    value: str,
    *,
    require_https: bool = False,
) -> str:
    """Validate and normalize an HTTP(S) provider API root."""
    return validate_llm_base_url(value, require_https=require_https)


def list_provider_presets() -> list[dict]:
    """Return connection presets (provider + base URL only, never a model id)."""
    return [{field: preset[field] for field in PRESET_FIELDS} for preset in PROVIDER_PRESETS]


def infer_provider_group(base_url: str) -> dict:
    """Map a base URL to a provider group via preset host match, else 其他.

    Host matching is exact / parent-domain only — never loose substring (that
    incorrectly collapsed distinct providers into one /model group).
    """
    try:
        normalized = normalize_provider_base_url(base_url, require_https=False)
    except ValueError:
        return {"id": "custom", "name": "其他"}
    host = (urlsplit(normalized).hostname or "").casefold()
    if not host:
        return {"id": "custom", "name": "其他"}
    # Both OpenCode gateways share a host.  Prefer the longer path first so
    # the Go endpoint cannot capture the general Zen endpoint.
    for preset in sorted(PROVIDER_PRESETS, key=lambda item: len(item["base_url"]), reverse=True):
        preset_host = (urlsplit(preset["base_url"]).hostname or "").casefold()
        if not preset_host:
            continue
        if (
            host == preset_host
            or host.endswith("." + preset_host)
            or preset_host.endswith("." + host)
        ):
            preset_path = urlsplit(preset["base_url"]).path.rstrip("/")
            request_path = urlsplit(normalized).path.rstrip("/")
            if request_path == preset_path or request_path.startswith(preset_path + "/"):
                return {"id": preset["id"], "name": preset["name"]}
    return {"id": "custom", "name": "其他"}


def resolve_provider_meta(
    base_url: str,
    provider_id: Optional[str] = None,
    provider_name: Optional[str] = None,
) -> dict:
    """Prefer explicit provider labels; otherwise infer from base_url."""
    inferred = infer_provider_group(base_url)
    pid = (provider_id or "").strip() or inferred["id"]
    pname = (provider_name or "").strip() or inferred["name"]
    return {"id": pid, "name": pname}


def local_model_key(model_id: str, provider_id: Optional[str] = None) -> str:
    """Config key: provider_id/model_id so the same vendor id can live in two groups."""
    mid = model_id.strip()
    pid = (provider_id or "").strip()
    if pid:
        return f"{pid}/{mid}"
    return mid


def ensure_models_provider_metadata(
    cfg: Optional[dict] = None,
    *,
    persist: bool = True,
) -> dict:
    """Stamp provider_id/name from base_url onto entries that lack them.

    Does not rename legacy bare keys (active_model / recent may still point at
    them). Grouping for /model uses base_url via GET /models.
    """
    owned = cfg is None
    if owned:
        cfg = load_config()
    models = cfg.get("models") or {}
    dirty = False
    for _name, entry in models.items():
        if not isinstance(entry, dict):
            continue
        base_url = entry.get("base_url") or ""
        if not base_url:
            continue
        inferred = infer_provider_group(base_url)
        if not entry.get("provider_id") or not entry.get("provider_name"):
            entry["provider_id"] = inferred["id"]
            entry["provider_name"] = inferred["name"]
            dirty = True
        elif inferred["id"] != "custom" and (
            entry.get("provider_id") != inferred["id"]
            or entry.get("provider_name") != inferred["name"]
        ):
            # Endpoint host wins over a stale stored label.
            entry["provider_id"] = inferred["id"]
            entry["provider_name"] = inferred["name"]
            dirty = True
    if persist and dirty and (owned or cfg is not None):
        save_config(cfg)
    return cfg


def _credential_config(api_key: str) -> dict:
    """Prefer an environment reference, otherwise use protected local storage.

    When the pasted key matches an existing ``*_API_KEY`` / ``*_ACCESS_TOKEN``
    environment variable, persist **both** ``api_key_env`` and
    ``api_key_secret``. Child processes (embedded API / appserver worker) often
    do not inherit the operator shell env; the secret is the durable fallback
    already supported by ``resolve_model_config``.
    """
    value = api_key.strip()
    match = re.fullmatch(r"(?:env:|\$\{)([A-Za-z_][A-Za-z0-9_]*)\}?", value)
    if match:
        return {"api_key_env": match.group(1)}

    for name, configured in os.environ.items():
        if not name.upper().endswith(("API_KEY", "ACCESS_TOKEN")) or not configured:
            continue
        if hmac.compare_digest(configured, value):
            return {
                "api_key_env": name,
                "api_key_secret": store_credential(value, get_config_path()),
            }
    return {"api_key_secret": store_credential(value, get_config_path())}


def add_model(
    name: str,
    api_key: str,
    base_url: str,
    model_name: Optional[str] = None,
    max_tokens: int | Literal["auto"] | None = None,
    temperature: float = 0.7,
    provider_id: Optional[str] = None,
    provider_name: Optional[str] = None,
    nickname: Optional[str] = None,
    api_transport: Optional[str] = None,
    resource_path: Optional[str] = None,
) -> dict:
    """M5：max_tokens 只接受正整数 / "auto" / None；0/负数/空串/浮点拒绝。"""
    if max_tokens is not None and max_tokens != "auto":
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool):
            raise ValueError(
                "max_tokens must be a positive integer, 'auto', or omitted; "
                f"got {max_tokens!r}"
            )
        if max_tokens <= 0:
            raise ValueError(f"max_tokens must be a positive integer; got {max_tokens}")
    base_url = normalize_provider_base_url(base_url, require_https=True)
    exact_resource = normalize_resource_path(resource_path)
    requested_transport = normalize_api_transport(
        api_transport, allow_auto=True
    )
    if exact_resource:
        inferred_from_path = infer_transport_from_resource_path(exact_resource)
        if (
            requested_transport != "auto"
            and requested_transport != inferred_from_path
        ):
            raise ValueError(
                "resource_path does not match api_transport: "
                f"{exact_resource} != {requested_transport}"
            )
        ensure_resource_path_rewritable(
            exact_resource,
            requested_transport
            if requested_transport != "auto"
            else inferred_from_path,
        )
    explicit_transport = detect_explicit_transport(base_url)
    if requested_transport != "auto":
        if (
            explicit_transport is not None
            and explicit_transport != requested_transport
        ):
            raise ValueError(
                "base_url explicit resource conflicts with api_transport"
            )
        explicit_transport = requested_transport
    if explicit_transport is not None:
        base_url = normalize_llm_endpoint(
            base_url, explicit_transport, require_https=True
        )
    meta = resolve_provider_meta(base_url, provider_id, provider_name)
    cfg = load_config()
    models = cfg.setdefault("models", {})
    # M5.5：同 Provider + 同 model_name 已存在（不同 key）→ fail closed，不静默覆盖。
    vendor_id = model_name or name
    for existing_key, existing in models.items():
        if existing_key == name:
            continue  # 同 key 更新是允许的（重新保存/改配置）
        if not isinstance(existing, dict):
            continue
        try:
            same_url = normalize_provider_base_url(
                existing.get("base_url", ""), require_https=False
            ) == base_url
        except ValueError:
            same_url = False
        existing_vendor = (existing.get("model_name") or existing_key).strip()
        if (
            same_url
            and existing_vendor == vendor_id
            and (existing.get("provider_id") or meta["id"]) == meta["id"]
        ):
            raise ValueError(
                f"model '{vendor_id}' already exists for provider '{meta['id']}' "
                f"at key '{existing_key}'; use that key instead of adding a duplicate"
            )
    previous_reference = models.get(name, {}).get("api_key_secret", "")
    entry = {
        **_credential_config(api_key),
        "base_url": base_url,
        "model_name": vendor_id,
        "max_tokens": max_tokens if max_tokens is not None else "auto",
        "temperature": temperature,
        "provider_id": meta["id"],
        "provider_name": meta["name"],
    }
    if explicit_transport is not None:
        entry["api_transport"] = explicit_transport
    if exact_resource:
        entry["resource_path"] = exact_resource
        entry["api_transport"] = infer_transport_from_resource_path(exact_resource)
    if nickname and nickname.strip() and nickname.strip() != vendor_id:
        entry["nickname"] = nickname.strip()
    models[name] = entry
    if not cfg.get("active_model"):
        cfg["active_model"] = name
    try:
        save_config(cfg)
    except BaseException:
        delete_credential(entry.get("api_key_secret", ""), get_config_path())
        raise
    if previous_reference != entry.get("api_key_secret"):
        delete_credential(previous_reference, get_config_path())
    return entry


def onboard_models_batch(
    *,
    api_key: str,
    base_url: str,
    model_ids: list[str],
    provider_id: Optional[str] = None,
    provider_name: Optional[str] = None,
    active_model_id: Optional[str] = None,
    skip_probe: bool = True,
) -> dict:
    """Add multiple provider models in one pass.

    When ``skip_probe`` is True (preset batch path), nothing is chat-probed.
    Config keys default to each ``provider_model_id``.
    """
    if not model_ids:
        return {
            "added": [],
            "skipped": [],
            "active": None,
            "message": "No models selected",
        }

    base_url = normalize_provider_base_url(base_url, require_https=True)
    probe_base_url = base_url
    explicit_transport = detect_explicit_transport(base_url)
    if explicit_transport is not None:
        base_url = normalize_llm_endpoint(
            base_url, explicit_transport, require_https=True
        )
    added: list[str] = []
    skipped: list[str] = []
    cfg_snapshot = load_config()
    models_snapshot = dict(cfg_snapshot.get("models") or {})
    known = set(models_snapshot)

    meta = resolve_provider_meta(base_url, provider_id, provider_name)
    provider_id = meta["id"]
    provider_name = meta["name"]
    normalized_url = base_url

    legacy_same_endpoint: set[str] = set()
    for existing_key, entry in models_snapshot.items():
        if not isinstance(entry, dict):
            continue
        mid = (entry.get("model_name") or existing_key).strip()
        try:
            entry_url = normalize_provider_base_url(
                entry.get("base_url", ""), require_https=False
            )
        except ValueError:
            continue
        if entry_url == normalized_url:
            legacy_same_endpoint.add(mid)
            # Bare key itself also counts as occupying that vendor id on this URL.
            if "/" not in existing_key:
                legacy_same_endpoint.add(existing_key)

    for model_id in model_ids:
        mid = model_id.strip()
        if not mid:
            continue
        key = local_model_key(mid, provider_id)
        if key in known or mid in legacy_same_endpoint:
            skipped.append(key)
            continue
        if not skip_probe:
            probe = probe_model_connection(
                api_key=api_key,
                # Preserve an explicitly pasted terminal resource for the
                # probe so it tests that protocol instead of reverting to
                # Other/custom auto-discovery after persistence normalization.
                base_url=probe_base_url,
                provider_model_id=mid,
            )
            if not probe.get("success"):
                skipped.append(key)
                continue
        add_model(
            key,
            api_key,
            base_url,
            model_name=mid,
            provider_id=provider_id,
            provider_name=provider_name,
            api_transport=explicit_transport,
        )
        added.append(key)
        known.add(key)
        legacy_same_endpoint.add(mid)

    active: Optional[str] = None
    if added:
        # active_model_id may be a raw vendor id or an already-namespaced key.
        candidates = []
        if active_model_id:
            candidates.append(active_model_id.strip())
            candidates.append(local_model_key(active_model_id.strip(), provider_id))
        active = next((c for c in candidates if c in added), added[0])
        set_active_model(active)

    count = len(added)
    message = f"已添加 {count} 个模型，请到 /model 查看"
    return {
        "added": added,
        "skipped": skipped,
        "active": active,
        "message": message,
    }


def remove_model(name: str) -> bool:
    cfg = load_config()
    models = cfg.get("models", {})
    if name not in models:
        return False
    removed = models.pop(name)
    if cfg.get("active_model") == name:
        cfg["active_model"] = next(iter(models), None)
    previous = cfg.get("recent_models")
    if isinstance(previous, list):
        cfg["recent_models"] = [
            item for item in previous if isinstance(item, str) and item != name
        ]
    save_config(cfg)
    delete_credential(removed.get("api_key_secret", ""), get_config_path())
    return True


def list_models() -> dict:
    cfg = load_config()
    return cfg.get("models", {})


RECENT_MODELS_LIMIT = 5


def _touch_recent_models(cfg: dict, name: str) -> list[str]:
    """Move ``name`` to the front of the real switch history (most recent first)."""
    history = [item for item in prune_recent_models(cfg) if item != name]
    history.insert(0, name)
    cfg["recent_models"] = history[:RECENT_MODELS_LIMIT]
    return cfg["recent_models"]


def prune_recent_models(cfg: dict) -> list[str]:
    """Read the switch history from a config mapping, newest first.

    Drops malformed entries and models that no longer exist, so a stale name can
    never be offered as a switch target.
    """
    previous = cfg.get("recent_models")
    if not isinstance(previous, list):
        return []
    known = cfg.get("models", {})
    return [
        item
        for item in previous
        if isinstance(item, str) and item in known
    ][:RECENT_MODELS_LIMIT]


def list_recent_models() -> list[str]:
    """Return the persisted switch history, newest first, pruned to live models."""
    return prune_recent_models(load_config())


def set_active_model(name: str) -> bool:
    cfg = load_config()
    if name not in cfg.get("models", {}):
        return False
    cfg["active_model"] = name
    _touch_recent_models(cfg, name)
    save_config(cfg)
    return True


#: /effort 全局思考强度档位的配置键（2026-08-12）。
#: 值 = 厂商档位（如 "medium"）或抽象档位（"fast"/"balanced"/"deep"，A21
#: 兼容）；未设置 = None（agent_v2 保持默认 balanced 现状行为）。
EFFORT_CONFIG_KEY = "effort"


def get_effort() -> str | None:
    """返回全局思考强度档位；未设置返回 None（调用方回退默认 balanced）。"""
    value = load_config().get(EFFORT_CONFIG_KEY)
    return value if isinstance(value, str) and value.strip() else None


def set_effort(value: str) -> bool:
    """持久化全局思考强度档位。

    校验：非空字符串。不校验模型档位集——档位在模型间切换后可能失效，
    由消费方（providers.llm_kwargs）在注入时回退（effort_options 不命中
    且 presets 无映射 → 不注入，保持现状行为）。
    """
    if not isinstance(value, str) or not value.strip():
        return False
    cfg = load_config()
    cfg[EFFORT_CONFIG_KEY] = value.strip()
    save_config(cfg)
    return True


def backfill_missing_api_key_secrets(cfg: Optional[dict] = None) -> int:
    """Persist ``api_key_secret`` for models that only reference an env var.

    Returns the number of models updated. Safe no-op when the env var is unset
    or a secret already exists. Does not change resolve priority.
    """
    if cfg is None:
        cfg = load_config()
    models = cfg.get("models", {})
    updated = 0
    for entry in models.values():
        if not isinstance(entry, dict):
            continue
        env_name = entry.get("api_key_env")
        if not env_name or entry.get("api_key_secret"):
            continue
        value = os.environ.get(str(env_name), "")
        if not str(value).strip():
            continue
        entry["api_key_secret"] = store_credential(value, get_config_path())
        updated += 1
    if updated:
        save_config(cfg)
    return updated


def test_model_connection(name: str) -> dict:
    """Probe an already persisted model by its local nickname."""
    cfg = load_config()
    models = cfg.get("models", {})
    if name not in models:
        return {"success": False, "error": f"Model '{name}' not found"}

    model = get_model_config(name, cfg)
    if not model.get("api_key"):
        env_name = model.get("api_key_env", "the configured environment variable")
        return {
            "success": False,
            "error": f"API credential is unavailable; set {env_name} and retry.",
        }
    return probe_model_connection(
        api_key=model["api_key"],
        base_url=model["base_url"],
        provider_model_id=model["model_name"],
    )


def _friendly_transport_error(error_text: str) -> Optional[str]:
    """Map a transport exception string onto an operator-readable message."""
    if "Name or service not known" in error_text or "getaddrinfo" in error_text:
        return "无法解析 API 地址。请检查域名是否正确。(DNS 解析失败)"
    if "Connection refused" in error_text:
        return "API 服务器拒绝连接。请检查 URL 和端口是否正确。"
    if "Connection timed out" in error_text or "timeout" in error_text.lower():
        return "连接超时。API 服务器可能过慢、无法访问，或 URL 不正确。"
    if "SSLError" in error_text or "ssl" in error_text.lower():
        return "SSL/TLS 错误。API 服务器可能有无效或自签名证书。"
    return None


#: Discovery allowlist（§7.2 / M3 步骤 1）：只有这些字段能进入发现记录，
#: 未知字段一律不得当成能力。任何额外能力字段必须显式加入 allowlist。
_DISCOVERY_ALLOWLIST = (
    "id",
    "owned_by",
    "context_window",
    "max_output_tokens",
    "max_completion_tokens",
)


def _discovery_allow_int(entry: dict, key: str) -> int | None:
    """Allowlist 内的可选整型能力字段；非正整数一律视为缺失。"""
    raw = entry.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw if raw > 0 else None


def _parse_discovered_models(payload: object) -> list[dict]:
    """Extract model entries from an OpenAI-compatible ``GET /models`` body.

    M3：只保留 allowlist 字段（id / owned_by / context_window /
    max_output_tokens / max_completion_tokens），未知字段忽略。model id 是
    唯一主键；nickname / owned_by / UI label 不得替代它。
    """
    if isinstance(payload, dict):
        entries = payload.get("data")
        if not isinstance(entries, list):
            entries = payload.get("models")
    else:
        entries = payload
    if not isinstance(entries, list):
        return []

    models: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            model_id = entry.strip()
            owned_by = ""
            advertised_ctx = advertised_max_out = advertised_max_completion = None
        elif isinstance(entry, dict):
            model_id = str(entry.get("id") or entry.get("model") or entry.get("name") or "").strip()
            owned_by = str(entry.get("owned_by") or "").strip()
            advertised_ctx = _discovery_allow_int(entry, "context_window")
            advertised_max_out = _discovery_allow_int(entry, "max_output_tokens")
            advertised_max_completion = _discovery_allow_int(entry, "max_completion_tokens")
        else:
            continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        model: dict = {"id": model_id}
        if owned_by:
            model["owned_by"] = owned_by
        if advertised_ctx is not None:
            model["context_window"] = advertised_ctx
        if advertised_max_out is not None:
            model["max_output_tokens"] = advertised_max_out
        if advertised_max_completion is not None:
            model["max_completion_tokens"] = advertised_max_completion
        models.append(model)
    return models


def discover_provider_models(*, api_key: str, base_url: str) -> dict:
    """List a provider's model catalogue without persisting anything.

    Calls ``GET {base_url}/models`` (the OpenAI-compatible discovery route) so
    the user never has to know a model id in advance.  Nothing touches disk:
    this is the read-only counterpart of ``probe_model_connection``.
    """
    api_key = api_key.strip()
    try:
        base_url = normalize_provider_base_url(base_url, require_https=True)
        explicit_transport = detect_explicit_transport(base_url)
        if explicit_transport is not None:
            base_url = normalize_llm_endpoint(
                base_url, explicit_transport, require_https=True
            )
    except ValueError as exc:
        message = str(exc)
        code = (
            DISCOVER_ERROR_HTTPS
            if "https://" in message.casefold() or "must use https" in message.casefold()
            else DISCOVER_ERROR_INVALID
        )
        return {"success": False, "error": message, "error_code": code}
    if not api_key:
        return {
            "success": False,
            "error": "Missing API credential",
            "error_code": DISCOVER_ERROR_INVALID,
        }

    def safe_error(value: object) -> str:
        text = str(value)
        return text.replace(api_key, "[REDACTED]") if api_key else text

    url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    start = time.time()
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, headers=headers)
            elapsed = round(time.time() - start, 2)
            if resp.status_code == 200:
                try:
                    models = _parse_discovered_models(resp.json())
                except Exception:
                    return {
                        "success": False,
                        "elapsed": elapsed,
                        "error": DISCOVERY_UNSUPPORTED_MESSAGE,
                        "error_code": DISCOVER_ERROR_UNSUPPORTED,
                    }
                if not models:
                    return {
                        "success": False,
                        "elapsed": elapsed,
                        "error": DISCOVERY_UNSUPPORTED_MESSAGE,
                        "error_code": DISCOVER_ERROR_UNSUPPORTED,
                    }
                return {"success": True, "elapsed": elapsed, "models": models}
            if resp.status_code in {404, 405}:
                return {
                    "success": False,
                    "elapsed": elapsed,
                    "error": DISCOVERY_UNSUPPORTED_MESSAGE,
                    "error_code": DISCOVER_ERROR_UNSUPPORTED,
                }
            if resp.status_code in {401, 403}:
                return {
                    "success": False,
                    "elapsed": elapsed,
                    "error": HTTP_CODE_MESSAGES[resp.status_code],
                    "error_code": DISCOVER_ERROR_AUTH,
                }
            friendly = HTTP_CODE_MESSAGES.get(resp.status_code)
            if friendly:
                return {
                    "success": False,
                    "elapsed": elapsed,
                    "error": friendly,
                    "error_code": DISCOVER_ERROR_TRANSPORT,
                }
            return {
                "success": False,
                "elapsed": elapsed,
                "error": safe_error(f"HTTP {resp.status_code}: {resp.text[:200]}"),
                "error_code": DISCOVER_ERROR_TRANSPORT,
            }
    except Exception as exc:
        elapsed = round(time.time() - start, 2)
        estr = safe_error(exc)
        return {
            "success": False,
            "elapsed": elapsed,
            "error": _friendly_transport_error(estr) or estr,
            "error_code": DISCOVER_ERROR_TRANSPORT,
        }


def _provider_error_message(resp: httpx.Response) -> str:
    """Prefer a provider JSON error body over a generic HTTP status label."""
    raw = (resp.text or "")[:400]
    try:
        payload = resp.json()
    except ValueError:
        return raw
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message:
            return message
    if isinstance(error, str) and error.strip():
        return error.strip()
    return raw


def probe_model_connection(
    *,
    api_key: str,
    base_url: str,
    provider_model_id: str,
    resource_path: Optional[str] = None,
) -> dict:
    """Test an unsaved provider configuration without touching disk.

    The Provider chooses the preferred interface.  ``Other``/custom endpoints
    try Responses first and fall back to Chat only for an explicit endpoint or
    protocol mismatch.  Auth, policy, rate-limit, timeout, and server failures
    retain their original meaning and never trigger a second request.
    """
    api_key = api_key.strip()
    try:
        base_url = normalize_provider_base_url(base_url, require_https=True)
        explicit_transport = detect_explicit_transport(base_url)
        exact_resource = normalize_resource_path(resource_path)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    provider_model_id = provider_model_id.strip()
    if not api_key or not base_url or not provider_model_id:
        return {"success": False, "error": "Missing API credential, base URL, or provider model ID"}

    def safe_error(value: object) -> str:
        text = str(value)
        return text.replace(api_key, "[REDACTED]") if api_key else text

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Lazy import avoids pulling the Agent/LangGraph stack into ordinary config
    # reads.  The probe and runtime now share the same Provider transport policy.
    from RxyCode.RxyCode1_1_0.core import providers as _providers

    meta = resolve_provider_meta(base_url)
    probe_cfg = {
        "base_url": base_url,
        "model_name": provider_model_id,
        "provider_id": meta["id"],
        "api_key": api_key,
        "resolved_max_tokens": 32,
    }
    if explicit_transport is not None:
        probe_cfg["api_transport"] = explicit_transport
    if exact_resource:
        probe_cfg["resource_path"] = exact_resource
        try:
            ensure_resource_path_rewritable(
                exact_resource,
                explicit_transport
                if explicit_transport is not None
                else infer_transport_from_resource_path(exact_resource),
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
    provider = _providers.resolve(probe_cfg)
    candidates = normalize_transport_candidates(
        provider.transport_candidates(probe_cfg)
    )

    class _ProbeHTTPError(RuntimeError):
        def __init__(
            self, response: httpx.Response, detail: str, request_url: str
        ):
            super().__init__(detail)
            self.status_code = response.status_code
            self.response = response
            self.request_url = request_url

    def request_for(transport: str) -> tuple[str, dict, dict]:
        if transport == OPENAI_RESPONSES_TRANSPORT:
            return (
                llm_endpoint_url(
                    base_url,
                    transport,
                    require_https=True,
                    resource_path=exact_resource,
                ),
                {
                    "model": provider_model_id,
                    "input": "Hi",
                    "max_output_tokens": 32,
                    "stream": False,
                },
                headers,
            )
        if transport == OPENAI_CHAT_TRANSPORT:
            return (
                llm_endpoint_url(
                    base_url,
                    transport,
                    require_https=True,
                    resource_path=exact_resource,
                ),
                {
                    "model": provider_model_id,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 32,
                    "stream": False,
                },
                headers,
            )
        if transport == ANTHROPIC_MESSAGES_TRANSPORT:
            return (
                llm_endpoint_url(
                    base_url,
                    transport,
                    require_https=True,
                    resource_path=exact_resource,
                ),
                {
                    "model": provider_model_id,
                    "max_tokens": 32,
                    "messages": [{"role": "user", "content": "Hi"}],
                },
                {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
        raise ValueError(
            f"connection probe is not implemented for transport {transport}"
        )

    def inspect_probe_body(
        data: object, transport: str
    ) -> tuple[bool, str | None, str]:
        """Return (structurally_valid, visible_text, outcome).

        Connection tests must accept reasoning-only / refusal / empty-text
        completions.  Missing protocol shape is not a successful probe.
        """
        if not isinstance(data, dict):
            return False, None, "invalid_body"
        if transport == OPENAI_CHAT_TRANSPORT:
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                return False, None, "invalid_body"
            first = choices[0]
            message = first.get("message") if isinstance(first, dict) else None
            if not isinstance(message, dict):
                return False, None, "invalid_body"
            content = message.get("content")
            reasoning = message.get("reasoning_content")
            text = content if isinstance(content, str) and content.strip() else None
            if text is None and isinstance(reasoning, str) and reasoning.strip():
                return True, None, "completed_no_text"
            if text is None:
                return True, None, "completed_no_text"
            return True, text, "completed"
        if transport == OPENAI_RESPONSES_TRANSPORT:
            status = str(data.get("status") or "").strip().casefold()
            if status == "failed":
                return False, None, "failed"
            if status == "incomplete":
                details = data.get("incomplete_details") or {}
                reason = (
                    str(details.get("reason") or "").strip().casefold()
                    if isinstance(details, dict)
                    else ""
                )
                if reason not in {"max_output_tokens", "content_filter"}:
                    return False, None, "invalid_body"
            elif status and status != "completed":
                return False, None, "invalid_body"
            items = data.get("output")
            has_items = isinstance(items, list)
            if not has_items and status not in {"completed", "incomplete"}:
                if isinstance(data.get("output_text"), str) and data["output_text"].strip():
                    return True, data["output_text"], "completed"
                return False, None, "invalid_body"
            parts: list[str] = []
            refused = False
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "refusal" or str(
                    item.get("status") or ""
                ).casefold() == "incomplete":
                    refused = refused or item.get("type") == "refusal"
                if item.get("type") == "message":
                    for block in item.get("content") or []:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "refusal":
                            refused = True
                            continue
                        if block.get("type") in {"output_text", "text"}:
                            value = block.get("text")
                            if isinstance(value, str):
                                parts.append(value)
            direct = data.get("output_text")
            if isinstance(direct, str) and direct.strip():
                parts.append(direct)
            text = "".join(parts).strip() or None
            if refused and not text:
                return True, None, "refused"
            if text is None:
                return True, None, "completed_no_text"
            return True, text, "completed"
        if transport == ANTHROPIC_MESSAGES_TRANSPORT:
            items = data.get("content")
            if not isinstance(items, list):
                return False, None, "invalid_body"
            parts: list[str] = []
            for item in items:
                if isinstance(item, dict) and item.get("type") == "text":
                    value = item.get("text")
                    if isinstance(value, str):
                        parts.append(value)
            text = "".join(parts).strip() or None
            if text is None:
                return True, None, "completed_no_text"
            return True, text, "completed"
        raise ValueError(f"unsupported probe response transport {transport}")

    start = time.time()
    try:
        with httpx.Client(timeout=30) as client:
            attempted: list[str] = []
            for index, transport in enumerate(candidates):
                url, payload, request_headers = request_for(transport)
                resp = client.post(url, json=payload, headers=request_headers)
                elapsed = round(time.time() - start, 2)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except (ValueError, AttributeError):
                        data = {}
                    valid, reply, outcome = inspect_probe_body(data, transport)
                    if valid:
                        result = {
                            "success": True,
                            "elapsed": elapsed,
                            "reply": reply,
                            "transport": transport,
                            "outcome": outcome,
                        }
                        if outcome == "refused":
                            result["message"] = (
                                "连接成功，但请求被策略拒绝"
                            )
                        return result
                    next_transport = (
                        candidates[index + 1]
                        if index + 1 < len(candidates)
                        else None
                    )
                    if next_transport:
                        attempted.append(transport)
                        continue
                    return {
                        "success": False,
                        "elapsed": elapsed,
                        "error": (
                            "Provider returned HTTP 200 but no valid "
                            f"{transport} reply body"
                        ),
                        "transport": transport,
                    }

                detail = safe_error(_provider_error_message(resp))
                probe_error = _ProbeHTTPError(resp, detail, url)
                next_transport = (
                    candidates[index + 1] if index + 1 < len(candidates) else None
                )
                unsupported_transport = provider.should_fallback_transport(
                    probe_error,
                    from_transport=transport,
                    to_transport=next_transport or transport,
                )
                if next_transport and unsupported_transport:
                    attempted.append(transport)
                    continue
                if unsupported_transport and attempted:
                    return {
                        "success": False,
                        "elapsed": elapsed,
                        "error": (
                            "No supported LLM API transport; attempted "
                            + ", ".join([*attempted, transport])
                        ),
                    }
                if re.search(
                    r"not supported|unknown model|does not exist|invalid model",
                    detail,
                    flags=re.IGNORECASE,
                ):
                    return {"success": False, "elapsed": elapsed, "error": detail}
                friendly = HTTP_CODE_MESSAGES.get(resp.status_code)
                if friendly:
                    return {"success": False, "elapsed": elapsed, "error": friendly}
                return {
                    "success": False,
                    "elapsed": elapsed,
                    "error": detail or safe_error(f"HTTP {resp.status_code}"),
                }
            return {
                "success": False,
                "elapsed": round(time.time() - start, 2),
                "error": (
                    "No supported LLM API transport; attempted "
                    + ", ".join([*attempted, candidates[-1]])
                ),
            }
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        estr = safe_error(e)
        return {
            "success": False,
            "elapsed": elapsed,
            "error": _friendly_transport_error(estr) or estr,
        }


def inspect_model_limits(model_name: Optional[str] = None) -> dict:
    """M5/M6：只读报告每个模型的 max_tokens 来源（不写磁盘、不泄漏凭证）。

    返回 ``{"models": [ {key, provider_id, model_name, max_tokens_mode,
    resolved_max_tokens, limit_source, context_window, warning} ]}``。
    """
    from .model_limits import resolve_configured_max_tokens
    from .settings import load_config

    cfg = load_config()
    models = cfg.get("models", {})
    model_limits_cfg = cfg.get("model_limits") or {}
    report = []
    for key, entry in models.items():
        if not isinstance(entry, dict):
            continue
        if model_name and key != model_name:
            continue
        try:
            resolution = resolve_configured_max_tokens(
                model_config=entry,
                capability_max_output_tokens=None,
                configured_max_tokens=entry.get("max_tokens"),
                model_limits_config=model_limits_cfg,
                input_tokens=None,
            )
            report.append({
                "key": key,
                "provider_id": entry.get("provider_id", ""),
                "model_name": entry.get("model_name", ""),
                "max_tokens_mode": (
                    "auto"
                    if entry.get("max_tokens") in (None, "auto")
                    else "explicit"
                ),
                "resolved_max_tokens": resolution.resolved_max_tokens,
                "limit_source": resolution.source,
                "context_window": resolution.context_window,
                "warning": "; ".join(resolution.warnings) or None,
            })
        except Exception as exc:  # noqa: BLE001
            report.append({
                "key": key,
                "provider_id": entry.get("provider_id", ""),
                "model_name": entry.get("model_name", ""),
                "max_tokens_mode": "error",
                "resolved_max_tokens": None,
                "limit_source": None,
                "context_window": None,
                "warning": f"{type(exc).__name__}: {exc}",
            })
    return {"models": report}


def set_auto_model_limits(
    model_name: str,
    *,
    dry_run: bool = False,
    backup: bool = True,
) -> dict:
    """M5/M6：把单个模型迁移到 max_tokens: auto。

    - 只迁移**当前为正整数**的模型；已是 auto 的跳过。
    - ``dry_run=True`` 时不写磁盘，只返回将发生的变更。
    - ``backup=True`` 时先写备份文件（``config.yaml.bak-<ts>``）。
    - 旧值写入迁移审计记录（``model_limits_migration`` 段）。
    返回 ``{"dry_run", "changed", "skipped", "backup_path", "old_value",
    "message"}``。
    """
    import shutil
    import time as _time

    from .settings import get_config_path, load_config, save_config

    cfg = load_config()
    models = cfg.get("models", {})
    entry = models.get(model_name)
    if not isinstance(entry, dict):
        return {
            "dry_run": dry_run,
            "changed": False,
            "skipped": True,
            "backup_path": None,
            "old_value": None,
            "message": f"Model '{model_name}' not found",
        }
    old = entry.get("max_tokens")
    if old in (None, "auto"):
        return {
            "dry_run": dry_run,
            "changed": False,
            "skipped": True,
            "backup_path": None,
            "old_value": old,
            "message": f"'{model_name}' already auto (old={old!r})",
        }
    if not isinstance(old, int) or old <= 0:
        return {
            "dry_run": dry_run,
            "changed": False,
            "skipped": True,
            "backup_path": None,
            "old_value": old,
            "message": f"'{model_name}' max_tokens is not a positive integer; "
            f"refusing to auto-migrate ({old!r})",
        }

    backup_path = None
    if backup and not dry_run:
        config_path = get_config_path()
        if config_path.is_file():
            backup_path = config_path.with_name(
                f"config.yaml.bak-{int(_time.time())}"
            )
            shutil.copy2(config_path, backup_path)

    if not dry_run:
        entry["max_tokens"] = "auto"
        migration = cfg.setdefault("model_limits_migration", {})
        migration[model_name] = {
            "from": old,
            "to": "auto",
            "when": _time.strftime("%Y-%m-%dT%H:%M:%S"),
            "backup": str(backup_path) if backup_path else None,
        }
        save_config(cfg)

    return {
        "dry_run": dry_run,
        "changed": True,
        "skipped": False,
        "backup_path": str(backup_path) if backup_path else None,
        "old_value": old,
        "message": (
            f"{'[dry-run] would migrate' if dry_run else 'Migrated'} "
            f"'{model_name}' max_tokens {old} -> auto"
        ),
    }
