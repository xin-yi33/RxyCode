"""Model-management endpoints for the RxyCode API server."""

from __future__ import annotations

import asyncio as _asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, SecretStr, field_validator

router = APIRouter()


def _redact_explicit(value: object, *secrets_to_remove: str) -> str:
    from .api_server import _redact_sensitive

    result = str(value)
    for secret_value in secrets_to_remove:
        if secret_value:
            result = result.replace(secret_value, "[REDACTED]")
    return str(_redact_sensitive(result))


class ModelOnboardingRequest(BaseModel):
    provider_model_id: str
    nickname: str | None = None
    api_key: SecretStr
    base_url: str

    @field_validator("provider_model_id")
    @classmethod
    def validate_provider_model_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("provider_model_id must not be empty")
        return value

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        return value or None

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("api_key must not be empty")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        from .config.model_manager import normalize_provider_base_url

        return normalize_provider_base_url(value, require_https=True)


class ModelBatchOnboardingRequest(BaseModel):
  api_key: SecretStr
  base_url: str
  model_ids: list[str]
  provider_id: str | None = None
  provider_name: str | None = None
  active_model_id: str | None = None
  skip_probe: bool = True

  @field_validator("api_key")
  @classmethod
  def validate_api_key(cls, value: SecretStr) -> SecretStr:
    if not value.get_secret_value().strip():
      raise ValueError("api_key must not be empty")
    return value

  @field_validator("base_url")
  @classmethod
  def validate_base_url(cls, value: str) -> str:
    from .config.model_manager import normalize_provider_base_url

    return normalize_provider_base_url(value, require_https=True)

  @field_validator("model_ids")
  @classmethod
  def validate_model_ids(cls, value: list[str]) -> list[str]:
    cleaned = [item.strip() for item in value if item and item.strip()]
    if not cleaned:
      raise ValueError("model_ids must not be empty")
    return cleaned


class ModelDiscoveryRequest(BaseModel):
    """Credentials for a read-only provider catalogue lookup.

    Deliberately has no ``provider_model_id``: discovery exists precisely for
    the case where the user does not know a model id yet.
    """

    api_key: SecretStr
    base_url: str

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("api_key must not be empty")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        from .config.model_manager import normalize_provider_base_url

        return normalize_provider_base_url(value, require_https=True)


@router.get("/models")
async def get_models():
    """Return structured model list for the model selection panel."""
    from .config.settings import load_config
    from .config.model_manager import (
        ensure_models_provider_metadata,
        infer_provider_group,
        prune_recent_models,
    )

    # Use settings.load_config so tests can monkeypatch it; stamp in-memory only.
    cfg = ensure_models_provider_metadata(load_config(), persist=False)
    models = cfg.get("models", {})
    active = cfg.get("active_model", "")
    result = []
    for name, mcfg in models.items():
        vendor_id = mcfg.get("model_name", name)
        # Display alias defaults to vendor model id (not the namespaced config key).
        display = mcfg.get("nickname") or vendor_id
        # Grouping is driven by endpoint host so the same vendor id from DeepSeek
        # vs OpenCode Go never collapses into one /model section.
        inferred = infer_provider_group(mcfg.get("base_url", ""))
        provider_name = (
            inferred.get("name")
            or mcfg.get("provider_name")
            or mcfg.get("category")
            or "其他"
        )
        provider_id = inferred.get("id") or mcfg.get("provider_id") or ""
        result.append({
            "id": name,
            "name": vendor_id,
            "nickname": display,
            "provider_model_id": vendor_id,
            "base_url": mcfg.get("base_url", ""),
            "active": name == active,
            "category": provider_name or "其他",
            "provider_name": provider_name or "",
            "provider_id": provider_id or "",
        })
    return {"models": result, "active": active, "recent": prune_recent_models(cfg)}


@router.get("/models/presets")
async def get_model_presets():
    """Connection presets for the add-model flow: provider + base URL only.

    No preset carries a model id — the TUI must discover ids from the live
    provider catalogue (``POST /models/discover``) or take user input.
    """
    from .config.model_manager import list_provider_presets

    return {"presets": list_provider_presets()}


@router.post("/models/discover")
async def discover_models(req: ModelDiscoveryRequest):
    """List a provider's models with the supplied credential; never persists."""
    from .config.model_manager import discover_provider_models

    api_key = req.api_key.get_secret_value().strip()
    result = await _asyncio.to_thread(
        discover_provider_models,
        api_key=api_key,
        base_url=req.base_url,
    )
    if not result.get("success"):
        safe_error = _redact_explicit(result.get("error", "Discovery failed"), api_key)
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Model discovery failed: {safe_error}",
                "error_code": result.get("error_code") or "transport",
            },
        )
    return {
        "models": result.get("models", []),
        "base_url": req.base_url,
        "probe": {"elapsed": result.get("elapsed")},
    }


@router.post("/models/onboard", status_code=201)
async def onboard_model(req: ModelOnboardingRequest):
    """Probe credentials in memory and persist only a working model mapping."""
    from .config.model_manager import (
        add_model,
        list_models,
        local_model_key,
        probe_model_connection,
        remove_model,
        resolve_provider_meta,
        set_active_model,
    )

    provider_model_id = req.provider_model_id
    nickname = req.nickname or provider_model_id
    api_key = req.api_key.get_secret_value().strip()
    base_url = req.base_url
    meta = resolve_provider_meta(base_url)
    config_key = local_model_key(provider_model_id, meta["id"])

    if config_key in list_models():
        raise HTTPException(
            status_code=409,
            detail=f"Model already exists: {config_key}",
        )

    probe = await _asyncio.to_thread(
        probe_model_connection,
        api_key=api_key,
        base_url=base_url,
        provider_model_id=provider_model_id,
    )
    if not probe.get("success"):
        safe_error = _redact_explicit(
            probe.get("error", "Connection failed"), api_key
        )
        raise HTTPException(
            status_code=400,
            detail=f"Connection test failed; model was not saved: {safe_error}",
        )

    try:
        add_model(
            config_key,
            api_key,
            base_url,
            model_name=provider_model_id,
            provider_id=meta["id"],
            provider_name=meta["name"],
            nickname=nickname if nickname != provider_model_id else None,
        )
        if not set_active_model(config_key):
            raise RuntimeError("saved model could not be activated")
    except Exception as exc:
        # The preflight is deliberately persistence-free. If the subsequent
        # write is only partly successful, roll it back before reporting.
        try:
            remove_model(config_key)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save model: {_redact_explicit(exc, api_key)}",
        ) from exc

    return {
        "action": "model_added",
        "message": f"Model '{nickname}' added and connection tested successfully",
        "model": {
            "id": config_key,
            "nickname": nickname,
            "provider_model_id": provider_model_id,
            "provider_id": meta["id"],
            "provider_name": meta["name"],
            "base_url": base_url,
            "active": True,
        },
        "probe": {"elapsed": probe.get("elapsed")},
    }


@router.post("/models/onboard/batch", status_code=201)
async def onboard_models_batch(req: ModelBatchOnboardingRequest):
    """Add multiple discovered models without per-model chat probes."""
    from .config.model_manager import onboard_models_batch as batch_onboard

    api_key = req.api_key.get_secret_value().strip()
    result = await _asyncio.to_thread(
        batch_onboard,
        api_key=api_key,
        base_url=req.base_url,
        model_ids=req.model_ids,
        provider_id=req.provider_id,
        provider_name=req.provider_name,
        active_model_id=req.active_model_id,
        skip_probe=req.skip_probe,
    )
    if not result.get("added"):
        raise HTTPException(
            status_code=400,
            detail="No models were added; all selected ids may already exist",
        )
    return {
        "action": "models_added",
        "message": result.get("message", "Models added"),
        "added": result.get("added", []),
        "skipped": result.get("skipped", []),
        "active": result.get("active"),
    }
