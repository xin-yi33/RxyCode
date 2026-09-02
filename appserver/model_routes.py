"""JSON-RPC routes for model / credential management (Phase 4 D5 unblock).

Exposes the same capabilities as the HTTP API (``api_server_models.py``)
as JSON-RPC methods so the Desktop shell (DC1: protocol-client only) can
manage models and API keys without calling HTTP.

Frozen entry names:
  - ``models/list``            — structured model list (provider grouping, Phase 3 limit summary)
  - ``models/presets``         — provider presets (base URL only, no model ids)
  - ``models/discover``        — probe a provider catalogue with a credential (never persists)
  - ``models/onboard``         — probe + persist a single working model (credential via DPAPI)
  - ``models/onboard_batch``   — probe + persist multiple models with one credential
  - ``models/remove``          — remove a model by config key
  - ``models/set_active``      — switch the active model
  - ``models/test_connection`` — live credential test for an existing model
  - ``credentials/upsert``     — store/refresh a model's API key (DPAPI encrypted, never echoed)
  - ``credentials/delete``     — remove a stored credential

All routes delegate to ``config.model_manager`` / ``config.credential_store``;
this module is a thin transport adapter and never reimplements business logic.
"""

from __future__ import annotations

import asyncio
from importlib import import_module
from typing import Any


def _load_module(relative_name: str, top_level_name: str):
    """Import in both installed-package and source-tree appserver modes."""
    try:
        return import_module(relative_name, package=__package__)
    except ImportError:
        return import_module(top_level_name)


def _run(coro):
    """Run a synchronous model_manager call off the event loop."""
    return asyncio.to_thread(coro)


def _redact(value: object, *secrets: str) -> str:
    _redact_sensitive = _load_module("..api_server", "api_server")._redact_sensitive

    result = str(value)
    for secret_value in secrets:
        if secret_value:
            result = result.replace(secret_value, "[REDACTED]")
    return str(_redact_sensitive(result))


def list_models() -> dict[str, Any]:
    """models/list — structured model list with provider grouping + limit summary."""
    settings = _load_module("..config.settings", "config.settings")
    manager = _load_module("..config.model_manager", "config.model_manager")
    load_config = settings.load_config
    ensure_models_provider_metadata = manager.ensure_models_provider_metadata
    infer_provider_group = manager.infer_provider_group
    prune_recent_models = manager.prune_recent_models

    cfg = ensure_models_provider_metadata(load_config(), persist=False)
    models = cfg.get("models", {})
    active = cfg.get("active_model", "")
    model_limits_cfg = cfg.get("model_limits") or {}
    get_effort = manager.get_effort
    result = []
    for name, mcfg in models.items():
        vendor_id = mcfg.get("model_name", name)
        display = mcfg.get("nickname") or vendor_id
        inferred = infer_provider_group(mcfg.get("base_url", ""))
        provider_name = (
            inferred.get("name")
            or mcfg.get("provider_name")
            or mcfg.get("category")
            or "其他"
        )
        provider_id = inferred.get("id") or mcfg.get("provider_id") or ""
        item: dict[str, Any] = {
            "id": name,
            "name": vendor_id,
            "nickname": display,
            "provider_model_id": vendor_id,
            "base_url": mcfg.get("base_url", ""),
            "active": name == active,
            "category": provider_name or "其他",
            "provider_name": provider_name or "",
            "provider_id": provider_id or "",
        }
        try:
            resolve_configured_max_tokens = _load_module(
                "..config.model_limits", "config.model_limits"
            ).resolve_configured_max_tokens

            resolution = resolve_configured_max_tokens(
                model_config=mcfg,
                capability_max_output_tokens=None,
                configured_max_tokens=mcfg.get("max_tokens"),
                model_limits_config=model_limits_cfg,
                input_tokens=None,
            )
            item["max_tokens_mode"] = (
                "auto" if mcfg.get("max_tokens") in (None, "auto") else "explicit"
            )
            item["resolved_max_tokens"] = resolution.resolved_max_tokens
            item["limit_source"] = resolution.source
            item["context_window"] = resolution.context_window
            item["warning"] = "; ".join(resolution.warnings) or None
        except Exception:
            item["max_tokens_mode"] = "auto"
            item["resolved_max_tokens"] = None
            item["limit_source"] = "legacy_server"
            item["context_window"] = None
            item["warning"] = None
        try:
            resolved = settings.resolve_model_config(mcfg)
            has_credential = bool(str(resolved.get("api_key") or "").strip())
        except Exception:
            resolved = mcfg
            has_credential = False
        if not has_credential:
            env_name = resolved.get("api_key_env") or "the configured environment variable"
            cred_warning = (
                f"API credential is unavailable; set {env_name} "
                "or re-add the model with its API key."
            )
            existing = item.get("warning")
            item["warning"] = f"{existing}; {cred_warning}" if existing else cred_warning
        # /effort 扩展（2026-08-12）：该模型的厂商档位全集（effort_options），
        # 供 /effort 命令与设置页渲染档位选择列表；空列表 = 不支持档位选择。
        try:
            providers = _load_module("..core.providers", "core.providers")
            caps = providers.resolve(mcfg).capabilities(mcfg)
            item["effort_options"] = list(caps.effort_options or ())
        except Exception:
            item["effort_options"] = []
        result.append(item)
    return {
        "models": result,
        "active": active,
        "recent": prune_recent_models(cfg),
        "effort": get_effort(),
    }


def list_presets() -> dict[str, Any]:
    """models/presets — provider connection presets (base URL only)."""
    list_provider_presets = _load_module(
        "..config.model_manager", "config.model_manager"
    ).list_provider_presets

    return {"presets": list_provider_presets()}


async def discover(params: dict[str, Any]) -> dict[str, Any]:
    """models/discover — probe a provider catalogue; never persists.

    params: {api_key, base_url}
    """
    discover_provider_models = _load_module(
        "..config.model_manager", "config.model_manager"
    ).discover_provider_models

    api_key = str(params.get("api_key", "")).strip()
    base_url = str(params.get("base_url", "")).strip()
    result = await asyncio.to_thread(
        discover_provider_models, api_key=api_key, base_url=base_url
    )
    if not result.get("success"):
        safe_error = _redact(result.get("error", "Discovery failed"), api_key)
        return {
            "ok": False,
            "error_code": result.get("error_code") or "transport",
            "message": f"Model discovery failed: {safe_error}",
        }
    return {
        "ok": True,
        "models": result.get("models", []),
        "base_url": base_url,
        "probe": {"elapsed": result.get("elapsed")},
    }


async def onboard(params: dict[str, Any]) -> dict[str, Any]:
    """models/onboard — probe credentials and persist a working model mapping.

    params: {provider_model_id, api_key, base_url, nickname?}
    """
    manager = _load_module("..config.model_manager", "config.model_manager")
    add_model = manager.add_model
    configured_models = manager.list_models
    local_model_key = manager.local_model_key
    probe_model_connection = manager.probe_model_connection
    resolve_provider_meta = manager.resolve_provider_meta
    set_active_model = manager.set_active_model

    provider_model_id = str(params.get("provider_model_id", "")).strip()
    api_key = str(params.get("api_key", "")).strip()
    base_url = str(params.get("base_url", "")).strip()
    nickname = str(params.get("nickname") or "").strip() or None

    if not provider_model_id:
        return {"ok": False, "error_code": "invalid", "message": "provider_model_id must not be empty"}
    if not api_key:
        return {"ok": False, "error_code": "invalid", "message": "api_key must not be empty"}
    if not base_url:
        return {"ok": False, "error_code": "invalid", "message": "base_url must not be empty"}

    normalize_provider_base_url = manager.normalize_provider_base_url

    try:
        base_url = normalize_provider_base_url(base_url, require_https=True)
    except Exception as exc:
        return {"ok": False, "error_code": "invalid", "message": f"Invalid base_url: {exc}"}

    meta = resolve_provider_meta(base_url)
    config_key = local_model_key(provider_model_id, meta["id"])
    if config_key in configured_models():
        return {"ok": False, "error_code": "exists", "message": f"Model already exists: {config_key}"}

    probe = await asyncio.to_thread(probe_model_connection, api_key, base_url, provider_model_id)
    if not probe.get("ok"):
        safe_error = _redact(probe.get("error", "probe failed"), api_key)
        return {"ok": False, "error_code": probe.get("error_code") or "probe", "message": safe_error}

    await asyncio.to_thread(
        add_model,
        name=config_key,
        api_key=api_key,
        base_url=base_url,
        model_name=provider_model_id,
        nickname=nickname,
    )
    await asyncio.to_thread(set_active_model, config_key)
    return {"ok": True, "id": config_key, "probe": {"elapsed": probe.get("elapsed")}}


async def onboard_batch(params: dict[str, Any]) -> dict[str, Any]:
    """models/onboard_batch — probe + persist multiple models with one credential.

    params: {api_key, base_url, model_ids: [..], provider_id?, provider_name?,
             active_model_id?, skip_probe?}
    """
    manager = _load_module("..config.model_manager", "config.model_manager")
    normalize_provider_base_url = manager.normalize_provider_base_url
    onboard_models_batch = manager.onboard_models_batch

    api_key = str(params.get("api_key", "")).strip()
    base_url = str(params.get("base_url", "")).strip()
    model_ids = [str(x).strip() for x in params.get("model_ids") or [] if str(x).strip()]
    provider_id = params.get("provider_id") or None
    provider_name = params.get("provider_name") or None
    active_model_id = params.get("active_model_id") or None
    skip_probe = bool(params.get("skip_probe", True))

    if not api_key:
        return {"ok": False, "error_code": "invalid", "message": "api_key must not be empty"}
    if not base_url:
        return {"ok": False, "error_code": "invalid", "message": "base_url must not be empty"}
    if not model_ids:
        return {"ok": False, "error_code": "invalid", "message": "model_ids must not be empty"}

    try:
        base_url = normalize_provider_base_url(base_url, require_https=True)
    except Exception as exc:
        return {"ok": False, "error_code": "invalid", "message": f"Invalid base_url: {exc}"}

    try:
        result = await asyncio.to_thread(
            onboard_models_batch,
            api_key=api_key,
            base_url=base_url,
            model_ids=model_ids,
            provider_id=provider_id,
            provider_name=provider_name,
            active_model_id=active_model_id,
            skip_probe=skip_probe,
        )
    except Exception as exc:
        return {"ok": False, "error_code": "onboard", "message": _redact(str(exc), api_key)}
    return {"ok": True, **result}


def remove(params: dict[str, Any]) -> dict[str, Any]:
    """models/remove — remove a model by config key. params: {id}"""
    remove_model = _load_module(
        "..config.model_manager", "config.model_manager"
    ).remove_model

    model_id = str(params.get("id", "")).strip()
    if not model_id:
        return {"ok": False, "error_code": "invalid", "message": "id must not be empty"}
    removed = remove_model(model_id)
    return {"ok": bool(removed), "removed": removed}


def set_active(params: dict[str, Any]) -> dict[str, Any]:
    """models/set_active — switch the active model. params: {id, effort?}

    ``effort``（optional_field，2026-08-12）：同时设置全局思考强度档位
    （/effort 与设置页共用）。缺失时不改档位。
    """
    manager = _load_module("..config.model_manager", "config.model_manager")
    set_active_model = manager.set_active_model
    set_effort = manager.set_effort

    model_id = str(params.get("id", "")).strip()
    if not model_id:
        return {"ok": False, "error_code": "invalid", "message": "id must not be empty"}
    # 审计修复（luna audit2，2026-08-13）：effort 校验**前置**于模型切换——
    # malformed effort 时不得产生"模型已切换但档位未设置"的部分成功（原子性）。
    effort = params.get("effort")
    if effort is not None:
        if not isinstance(effort, str) or not effort.strip():
            return {
                "ok": False,
                "id": model_id,
                "error_code": "invalid",
                "message": "effort must be a non-empty string",
            }
    ok = set_active_model(model_id)
    if not ok:
        return {"ok": False, "id": model_id}
    if effort is not None:
        if not set_effort(effort):
            return {
                "ok": False,
                "id": model_id,
                "error_code": "invalid",
                "message": "effort must be a non-empty string",
            }
    return {"ok": True, "id": model_id}


async def test_connection(params: dict[str, Any]) -> dict[str, Any]:
    """models/test_connection — live credential test. params: {id}"""
    test_model_connection = _load_module(
        "..config.model_manager", "config.model_manager"
    ).test_model_connection

    model_id = str(params.get("id", "")).strip()
    if not model_id:
        return {"ok": False, "error_code": "invalid", "message": "id must not be empty"}
    result = await asyncio.to_thread(test_model_connection, model_id)
    return {
        "ok": bool(result.get("ok")),
        "message": result.get("message") or result.get("error") or "",
        "elapsed": result.get("elapsed"),
    }


def upsert_credential(params: dict[str, Any]) -> dict[str, Any]:
    """credentials/upsert — store/refresh a model API key (DPAPI, never echoed).

    Delegates to ``model_manager.add_model`` with the existing model's
    config key so the credential flows through ``_credential_config``
    (env-ref aware, DPAPI-encrypted ``api_key_secret``). The key is never
    returned; only a reference exists inside the backend config.

    params: {id, api_key}
    """
    manager = _load_module("..config.model_manager", "config.model_manager")
    add_model = manager.add_model
    load_config = manager.load_config
    normalize_provider_base_url = manager.normalize_provider_base_url

    model_id = str(params.get("id", "")).strip()
    api_key = str(params.get("api_key", "")).strip()
    if not model_id:
        return {"ok": False, "error_code": "invalid", "message": "id must not be empty"}
    if not api_key:
        return {"ok": False, "error_code": "invalid", "message": "api_key must not be empty"}

    cfg = load_config()
    existing = (cfg.get("models") or {}).get(model_id)
    if not isinstance(existing, dict):
        return {
            "ok": False,
            "error_code": "not_found",
            "message": f"No model with id '{model_id}'",
        }

    try:
        add_model(
            name=model_id,
            api_key=api_key,
            base_url=normalize_provider_base_url(
                str(existing.get("base_url", "")), require_https=False
            ),
            model_name=existing.get("model_name") or model_id,
            nickname=existing.get("nickname"),
        )
    except Exception as exc:
        return {"ok": False, "error_code": "credential", "message": str(exc)}
    return {"ok": True, "id": model_id}


def delete_credential(params: dict[str, Any]) -> dict[str, Any]:
    """credentials/delete — clear a model's API key reference (DPAPI blob removed).

    params: {id}
    """
    credentials = _load_module("..config.credential_store", "config.credential_store")
    manager = _load_module("..config.model_manager", "config.model_manager")
    settings = _load_module("..config.settings", "config.settings")
    _delete_secret = credentials.delete_credential
    load_config = manager.load_config
    save_config = manager.save_config
    get_config_path = settings.get_config_path

    model_id = str(params.get("id", "")).strip()
    if not model_id:
        return {"ok": False, "error_code": "invalid", "message": "id must not be empty"}

    cfg = load_config()
    entry = (cfg.get("models") or {}).get(model_id)
    if not isinstance(entry, dict):
        return {"ok": False, "error_code": "not_found", "message": f"No model with id '{model_id}'"}

    reference = entry.get("api_key_secret")
    if reference:
        _delete_secret(reference, get_config_path())
    entry.pop("api_key_secret", None)
    entry.pop("api_key_env", None)
    save_config(cfg)
    return {"ok": True, "id": model_id}
