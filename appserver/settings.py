"""PhaseG-B10 scoped settings, ModelCatalog summaries, and secret storage.

Desktop and CLI must call this service. Layers are explicit:

    global → project → workspace → thread → turn

Secrets never enter settings JSON, logs, or error text. Output limits come
from Phase 3 ``resolve_output_limit`` (unknown fallback 32768, never 8192).
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workspace import PathBoundaryError, canonicalize

try:
    from config.credential_store import delete_credential, store_credential
    from config.model_catalog import ModelCatalog
    from config.model_limits import UNKNOWN_MODEL_FALLBACK, resolve_output_limit
except ImportError:  # pragma: no cover - installed-package layout
    from config.credential_store import delete_credential, store_credential
    from config.model_catalog import ModelCatalog
    from config.model_limits import UNKNOWN_MODEL_FALLBACK, resolve_output_limit

SETTINGS_SCHEMA_VERSION = 1
LAYERS = ("global", "project", "workspace", "thread", "turn")
ALLOWED_KEYS = frozenset(
    {
        "provider_id",
        "model_id",
        "reasoning_effort",
        "context_strategy",
        "max_tokens",
        "permission_profile",
    }
)
SECRET_INPUT_KEYS = frozenset({"api_key", "secret", "token", "password", "authorization"})
MAX_SNAPSHOTS = 10
_SECRET_SHAPE = re.compile(
    r"(?i)((?:sk|rk|pk)-[A-Za-z0-9_\-]{4,}|Bearer\s+\S+)"
)
_API_KEY_VALUE = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|password|authorization|credential)\s*[:=]\s*)\S+"
)
_logger = logging.getLogger(__name__)


class SettingsError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact_text(value: object, *extras: str) -> str:
    """Strip key-shaped tokens and caller-supplied secrets from any text."""
    text = "" if value is None else str(value)
    for extra in extras:
        if extra:
            text = text.replace(extra, "[REDACTED]")
    text = _API_KEY_VALUE.sub(r"\1[REDACTED]", text)
    return _SECRET_SHAPE.sub("[REDACTED]", text)


def classify_model_error(error_code: str | None, message: str | None) -> str:
    """Split key / quota / unavailable. Never collapse them into one code."""
    code = (error_code or "").strip().lower()
    text = (message or "").strip().lower()
    key_marks = (
        "auth",
        "unauthorized",
        "forbidden",
        "key_invalid",
        "invalid_api_key",
        "invalid key",
        "api key",
        "apikey",
    )
    quota_marks = (
        "quota",
        "rate_limit",
        "rate limit",
        "insufficient_quota",
        "billing",
        "exceeded",
    )
    unavailable_marks = (
        "model_unavailable",
        "not_found",
        "model not found",
        "unknown model",
        "does not exist",
        "unsupported_model",
    )
    if code in {"auth", "unauthorized", "forbidden", "key_invalid"} or any(
        mark in text for mark in key_marks if mark in {"invalid api key", "invalid key", "unauthorized"}
    ):
        return "KEY_INVALID"
    if "invalid api key" in text or "invalid key" in text or "unauthorized" in text:
        return "KEY_INVALID"
    if code in {"quota", "rate_limit", "insufficient_quota"} or any(
        mark in text for mark in ("quota", "rate limit", "insufficient_quota")
    ):
        return "QUOTA_EXCEEDED"
    if code in {"not_found", "model_unavailable", "unsupported_model"} or any(
        mark in text for mark in ("model not found", "unknown model", "does not exist")
    ):
        return "MODEL_UNAVAILABLE"
    if any(mark in code for mark in key_marks):
        return "KEY_INVALID"
    if any(mark in code for mark in quota_marks):
        return "QUOTA_EXCEEDED"
    if any(mark in code for mark in unavailable_marks):
        return "MODEL_UNAVAILABLE"
    return "UNKNOWN"


def _empty_document() -> dict[str, Any]:
    return {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "layers": {
            "global": {"values": {}, "updated_at": None},
            "project": {},
            "workspace": {},
            "thread": {},
            "turn": {},
        },
        "history": {},
        "credentials": {},
        "snapshots": [],
    }


def _workspace_key(workspace: str | None) -> str | None:
    if not workspace:
        return None
    try:
        return str(canonicalize(workspace))
    except (PathBoundaryError, OSError, ValueError):
        return str(workspace).strip()


def summarize_model(
    *,
    provider_id: str,
    model_id: str,
    configured_max_tokens: int | str | None = None,
    catalog: ModelCatalog | None = None,
    input_tokens: int | None = None,
) -> dict[str, Any]:
    """Resolve one model through Phase 3. Unknown ids stay unknown."""
    provider_id = (provider_id or "").strip() or "unknown"
    model_id = (model_id or "").strip()
    if not model_id:
        raise SettingsError("SETTINGS_KEY_INVALID", "model_id is required")
    loaded = catalog if catalog is not None else ModelCatalog.load()
    record, matched, family = loaded.lookup(provider_id, model_id)
    known = record is not None
    resolution = resolve_output_limit(
        provider_id=provider_id,
        model_id=model_id,
        configured_max_tokens=configured_max_tokens,
        catalog_record=record,
        provider_default=None,
        input_tokens=input_tokens,
    )
    warnings = list(resolution.warnings)
    if not known:
        warnings.append(
            f"unknown model {provider_id}:{model_id}; using high fallback "
            f"{UNKNOWN_MODEL_FALLBACK}; identity is not a catalog model"
        )
    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "model_context_window": resolution.context_window,
        "model_max_output_tokens": resolution.resolved_max_tokens,
        "resolved_max_tokens": resolution.resolved_max_tokens,
        "limit_source": resolution.source,
        "is_fallback": resolution.source == "unknown_fallback",
        "warning": "; ".join(warnings) or None,
        "matched_catalog_key": matched if known else None,
        "known_model": known,
        "family_pattern": family,
    }


def handshake_model_summaries(catalog: ModelCatalog | None = None) -> list[dict[str, Any]]:
    """One honest summary per provider for initialize. Uses the resolver."""
    loaded = catalog if catalog is not None else ModelCatalog.load()
    seen: dict[str, dict[str, Any]] = {}
    for record in loaded._exact.values():
        if record.provider_id in seen:
            continue
        seen[record.provider_id] = summarize_model(
            provider_id=record.provider_id,
            model_id=record.model_id,
            catalog=loaded,
        )
    return list(seen.values())


class SettingsService:
    """Scoped settings store. Writes fail closed without PermissionStore."""

    def __init__(self, path: Path | None = None, *, persistent: bool = True) -> None:
        self.persistent = persistent
        self.path = path or Path(os.environ.get("RXYCODE_DATA_DIR", ".")) / "desktop" / "settings.json"
        if persistent:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = _empty_document()
        self._load()

    def _secret_config_path(self) -> Path:
        return self.path.parent / "settings-config.yaml"

    def _load(self) -> None:
        if not self.persistent:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(raw, dict):
            self._data = self.migrate(raw)

    def _save(self) -> None:
        if not self.persistent:
            return
        payload = json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True)
        if _SECRET_SHAPE.search(payload):
            raise SettingsError("SETTINGS_SECRET_LEAK", "refusing to persist secret-shaped text")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="settings-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    def migrate(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Upgrade older documents. Newer schema is rejected, not silently read."""
        version = raw.get("schema_version")
        if version is None:
            migrated = _empty_document()
            values = self._clean_values(
                {key: raw[key] for key in ALLOWED_KEYS if key in raw}
            )
            if values:
                migrated["layers"]["global"] = {"values": values, "updated_at": _now()}
            migrated["migrated_from"] = 0
            return migrated
        try:
            version_i = int(version)
        except (TypeError, ValueError) as exc:
            raise SettingsError("SETTINGS_SCHEMA_UNSUPPORTED", "schema_version is not an integer") from exc
        if version_i > SETTINGS_SCHEMA_VERSION:
            raise SettingsError(
                "SETTINGS_SCHEMA_UNSUPPORTED",
                f"settings schema {version_i} is newer than {SETTINGS_SCHEMA_VERSION}",
            )
        document = _empty_document()
        layers = raw.get("layers") if isinstance(raw.get("layers"), dict) else {}
        for name in LAYERS:
            incoming = layers.get(name)
            if name == "global":
                if isinstance(incoming, dict):
                    document["layers"]["global"] = {
                        "values": self._clean_values(incoming.get("values") or incoming),
                        "updated_at": incoming.get("updated_at"),
                    }
            elif isinstance(incoming, dict):
                document["layers"][name] = {
                    key: {
                        "values": self._clean_values((item or {}).get("values") or item or {}),
                        "updated_at": (item or {}).get("updated_at"),
                    }
                    for key, item in incoming.items()
                    if isinstance(item, dict)
                }
        if isinstance(raw.get("history"), dict):
            document["history"] = {
                key: self._clean_values(item) if isinstance(item, dict) else item
                for key, item in raw["history"].items()
            }
        document["credentials"] = self._clean_credentials(raw.get("credentials"))
        if isinstance(raw.get("snapshots"), list):
            cleaned_snaps: list[dict[str, Any]] = []
            for item in raw["snapshots"][-MAX_SNAPSHOTS:]:
                if not isinstance(item, dict):
                    continue
                data = item.get("data") if isinstance(item.get("data"), dict) else {}
                cleaned_snaps.append(
                    {
                        "snapshot_id": item.get("snapshot_id"),
                        "created_at": item.get("created_at"),
                        "reason": item.get("reason"),
                        "data": {
                            "layers": self._clean_layers(data.get("layers")),
                            "history": data.get("history") if isinstance(data.get("history"), dict) else {},
                            "credentials": self._clean_credentials(data.get("credentials")),
                        },
                    }
                )
            document["snapshots"] = cleaned_snaps
        if isinstance(raw.get("_secret_refs"), list):
            document["_secret_refs"] = [
                str(item) for item in raw["_secret_refs"] if isinstance(item, str)
            ]
        document["schema_version"] = SETTINGS_SCHEMA_VERSION
        if version_i < SETTINGS_SCHEMA_VERSION:
            document["migrated_from"] = version_i
        return document

    @staticmethod
    def _clean_values(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        cleaned: dict[str, Any] = {}
        for key, value in raw.items():
            name = str(key)
            if name in SECRET_INPUT_KEYS or name in {"api_key_secret", "credential"}:
                continue
            if name not in ALLOWED_KEYS:
                continue
            cleaned[name] = value
        return cleaned

    @staticmethod
    def _clean_credentials(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        ref = raw.get("credential_ref") or raw.get("api_key_secret")
        if not isinstance(ref, str) or not re.fullmatch(r"[0-9a-f]{32}", ref):
            return {}
        return {"credential_ref": ref, "updated_at": raw.get("updated_at")}

    def _clean_layers(self, raw: Any) -> dict[str, Any]:
        empty = _empty_document()["layers"]
        if not isinstance(raw, dict):
            return empty
        layers = empty
        incoming_global = raw.get("global")
        if isinstance(incoming_global, dict):
            layers["global"] = {
                "values": self._clean_values(incoming_global.get("values") or incoming_global),
                "updated_at": incoming_global.get("updated_at"),
            }
        for name in ("project", "workspace", "thread", "turn"):
            incoming = raw.get(name)
            if not isinstance(incoming, dict):
                continue
            layers[name] = {
                key: {
                    "values": self._clean_values((item or {}).get("values") or item or {}),
                    "updated_at": (item or {}).get("updated_at"),
                }
                for key, item in incoming.items()
                if isinstance(item, dict)
            }
        return layers

    def _scope_key(self, layer: str, *, project_id: str | None, workspace: str | None, thread_id: str | None, turn_id: str | None) -> str | None:
        if layer == "global":
            return None
        if layer == "project":
            if not (project_id or "").strip():
                raise SettingsError("SETTINGS_SCOPE_REQUIRED", "project layer requires project_id")
            return project_id.strip()
        if layer == "workspace":
            key = _workspace_key(workspace)
            if not key:
                raise SettingsError("SETTINGS_SCOPE_REQUIRED", "workspace layer requires workspace")
            return key
        if layer == "thread":
            if not (thread_id or "").strip():
                raise SettingsError("SETTINGS_SCOPE_REQUIRED", "thread layer requires thread_id")
            return thread_id.strip()
        if layer == "turn":
            if not (thread_id or "").strip() or not (turn_id or "").strip():
                raise SettingsError("SETTINGS_SCOPE_REQUIRED", "turn layer requires thread_id and turn_id")
            return f"{thread_id.strip()}/{turn_id.strip()}"
        raise SettingsError("SETTINGS_LAYER_INVALID", f"unknown layer: {layer}")

    def _layer_values(self, layer: str, key: str | None) -> dict[str, Any]:
        bucket = self._data["layers"][layer]
        if layer == "global":
            values = bucket.get("values") or {}
            return dict(values) if isinstance(values, dict) else {}
        item = bucket.get(key or "")
        if not isinstance(item, dict):
            return {}
        values = item.get("values") or {}
        return dict(values) if isinstance(values, dict) else {}

    def resolve(
        self,
        *,
        project_id: str | None = None,
        workspace: str | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
        keys: list[str] | None = None,
        catalog: ModelCatalog | None = None,
    ) -> dict[str, Any]:
        """Single interpretation for Desktop RPC and in-process CLI."""
        resolved: dict[str, Any] = {}
        sources: dict[str, str] = {}
        scopes = {
            "global": None,
            "project": (project_id or "").strip() or None,
            "workspace": _workspace_key(workspace),
            "thread": (thread_id or "").strip() or None,
            "turn": (
                f"{thread_id.strip()}/{turn_id.strip()}"
                if (thread_id or "").strip() and (turn_id or "").strip()
                else None
            ),
        }
        for layer in LAYERS:
            scope = scopes[layer]
            if layer != "global" and not scope:
                continue
            overlay = self._layer_values(layer, scope)
            for name, value in overlay.items():
                if name not in ALLOWED_KEYS:
                    continue
                resolved[name] = value
                sources[name] = layer
        if keys:
            wanted = set(keys)
            resolved = {name: resolved[name] for name in resolved if name in wanted}
            sources = {name: sources[name] for name in sources if name in wanted}
        history = None
        if thread_id and thread_id in self._data.get("history", {}):
            history = dict(self._data["history"][thread_id])
        summary = None
        model_id = resolved.get("model_id")
        if isinstance(model_id, str) and model_id.strip():
            summary = summarize_model(
                provider_id=str(resolved.get("provider_id") or "unknown"),
                model_id=model_id,
                configured_max_tokens=resolved.get("max_tokens"),
                catalog=catalog,
            )
        cred = self._data.get("credentials") or {}
        return {
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "values": resolved,
            "sources": sources,
            "history": history,
            "model_summary": summary,
            "has_credential": bool(cred.get("credential_ref")),
            "layers": [name for name in LAYERS],
        }

    def get(self, **kwargs: Any) -> dict[str, Any]:
        return self.resolve(**kwargs)

    def _policy_scope(self, workspace: str | None) -> str:
        """B7 workspace_write needs a concrete scope; global writes use the store dir."""
        keyed = _workspace_key(workspace)
        if keyed:
            return keyed
        parent = self.path.parent
        try:
            return str(canonicalize(parent))
        except (PathBoundaryError, OSError, ValueError):
            return str(parent)

    def _authorize(
        self,
        permission_store: Any,
        *,
        action: str,
        actor: str,
        approval_id: str | None,
        project_id: str | None,
        workspace: str | None,
        session_id: str | None,
        turn_id: str | None,
        project_store: Any = None,
        layer: str | None = None,
    ) -> None:
        if permission_store is None:
            raise SettingsError("SETTINGS_PERMISSION_DENIED", "permission_store required")
        if actor == "auto_review":
            raise SettingsError("SETTINGS_PERMISSION_DENIED", "auto_review cannot write settings")
        if layer == "project":
            pid = (project_id or "").strip()
            if not pid:
                raise SettingsError("SETTINGS_SCOPE_REQUIRED", "project layer requires project_id")
            if project_store is not None and project_store.get(pid) is None:
                raise SettingsError("SETTINGS_SCOPE_REQUIRED", "unknown project_id")
        policy_scope = self._policy_scope(workspace)
        verdict = permission_store.evaluate(
            action=action,
            actor=actor,
            approval_id=approval_id,
            scope=policy_scope,
            project_id=project_id,
            workspace=policy_scope,
            session_id=session_id,
            turn_id=turn_id,
        )
        if verdict != "allow":
            raise SettingsError("SETTINGS_PERMISSION_DENIED", "settings write denied")

    def _snapshot(self, reason: str) -> str:
        snapshot_id = uuid.uuid4().hex[:12]
        entry = {
            "snapshot_id": snapshot_id,
            "created_at": _now(),
            "reason": reason,
            "data": {
                "layers": json.loads(json.dumps(self._data["layers"])),
                "history": json.loads(json.dumps(self._data.get("history") or {})),
                "credentials": dict(self._data.get("credentials") or {}),
            },
        }
        rows = list(self._data.get("snapshots") or [])
        rows.append(entry)
        self._data["snapshots"] = rows[-MAX_SNAPSHOTS:]
        return snapshot_id

    def _sanitize_patch(self, values: dict[str, Any], extras: list[str]) -> tuple[dict[str, Any], str | None]:
        if not isinstance(values, dict):
            raise SettingsError("SETTINGS_KEY_INVALID", "values must be an object")
        secret: str | None = None
        patch: dict[str, Any] = {}
        for raw_key, raw_value in values.items():
            key = str(raw_key)
            if key in SECRET_INPUT_KEYS:
                if key == "api_key" and isinstance(raw_value, str) and raw_value.strip():
                    secret = raw_value.strip()
                    extras.append(secret)
                continue
            if key not in ALLOWED_KEYS:
                raise SettingsError("SETTINGS_KEY_INVALID", f"unknown settings key: {key}")
            if key == "max_tokens" and raw_value not in (None, "auto") and not (
                isinstance(raw_value, int) and raw_value > 0
            ):
                raise SettingsError("SETTINGS_KEY_INVALID", "max_tokens must be a positive int, 'auto', or null")
            patch[key] = raw_value
        return patch, secret

    def set(
        self,
        *,
        layer: str,
        values: dict[str, Any],
        permission_store: Any,
        project_id: str | None = None,
        workspace: str | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
        session_id: str | None = None,
        actor: str = "user",
        approval_id: str | None = None,
        project_store: Any = None,
        catalog: ModelCatalog | None = None,
    ) -> dict[str, Any]:
        extras: list[str] = []
        try:
            if layer not in LAYERS:
                raise SettingsError("SETTINGS_LAYER_INVALID", f"unknown layer: {layer}")
            self._scope_key(
                layer,
                project_id=project_id,
                workspace=workspace,
                thread_id=thread_id,
                turn_id=turn_id,
            )
            self._authorize(
                permission_store,
                action="settings.write",
                actor=actor,
                approval_id=approval_id,
                project_id=project_id,
                workspace=workspace,
                session_id=session_id or thread_id,
                turn_id=turn_id,
                project_store=project_store,
                layer=layer,
            )
            patch, secret = self._sanitize_patch(values, extras)
            scope = self._scope_key(
                layer,
                project_id=project_id,
                workspace=workspace,
                thread_id=thread_id,
                turn_id=turn_id,
            )
            snapshot_id = self._snapshot("pre-set")
            if layer == "global":
                bucket = self._data["layers"]["global"]
                current = dict(bucket.get("values") or {})
                self._apply_patch(current, patch)
                bucket["values"] = current
                bucket["updated_at"] = _now()
            else:
                assert scope is not None
                rows = self._data["layers"][layer]
                item = dict(rows.get(scope) or {"values": {}})
                current = dict(item.get("values") or {})
                self._apply_patch(current, patch)
                item["values"] = current
                item["updated_at"] = _now()
                rows[scope] = item
            if secret is not None:
                self._store_secret(secret)
            self._save()
            resolved = self.resolve(
                project_id=project_id,
                workspace=workspace,
                thread_id=thread_id,
                turn_id=turn_id,
                catalog=catalog,
            )
            if thread_id:
                self._freeze_history(thread_id, resolved["values"], current_resolved=resolved["values"])
                self._save()
                resolved = self.resolve(
                    project_id=project_id,
                    workspace=workspace,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    catalog=catalog,
                )
            _logger.info("settings.set layer=%s keys=%s", layer, sorted(patch))
            return {
                **resolved,
                "ok": True,
                "layer": layer,
                "snapshot_id": snapshot_id,
                "impact": {
                    "affected_layer": layer,
                    "affects_existing_thread_history": False,
                    "history_preserved": True,
                },
            }
        except SettingsError as exc:
            raise SettingsError(exc.code, redact_text(exc.message, *extras)) from None
        except Exception as exc:
            raise SettingsError("SETTINGS_WRITE_FAILED", redact_text(exc, *extras)) from None

    def _apply_patch(self, current: dict[str, Any], patch: dict[str, Any]) -> None:
        for key, value in patch.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value

    def _freeze_history(self, thread_id: str, patch: dict[str, Any], current_resolved: dict[str, Any] | None) -> None:
        existing = self._data.setdefault("history", {}).get(thread_id)
        if isinstance(existing, dict) and existing.get("model_id"):
            return
        model_id = (current_resolved or patch).get("model_id")
        provider_id = (current_resolved or patch).get("provider_id")
        if not model_id:
            return
        self._data["history"][thread_id] = {
            "model_id": model_id,
            "provider_id": provider_id,
            "frozen_at": _now(),
        }

    def _store_secret(self, secret: str) -> None:
        reference = store_credential(secret, self._secret_config_path())
        self._data["credentials"] = {
            "credential_ref": reference,
            "updated_at": _now(),
        }
        # Keep previous keychain entries while snapshots still name them.
        # They are only deleted when no live document or snapshot references
        # the ref anymore.
        self._gc_unreferenced_secrets()

    def _referenced_secrets(self) -> set[str]:
        refs: set[str] = set()
        current = (self._data.get("credentials") or {}).get("credential_ref")
        if isinstance(current, str):
            refs.add(current)
        for item in self._data.get("snapshots") or []:
            if not isinstance(item, dict):
                continue
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            creds = data.get("credentials") if isinstance(data, dict) else {}
            ref = creds.get("credential_ref") if isinstance(creds, dict) else None
            if isinstance(ref, str):
                refs.add(ref)
        return refs

    def _gc_unreferenced_secrets(self) -> None:
        previous = self._data.setdefault("_secret_refs", [])
        if not isinstance(previous, list):
            previous = []
        live = self._referenced_secrets()
        self._data["_secret_refs"] = sorted(live)
        path = self._secret_config_path()
        for ref in previous:
            if isinstance(ref, str) and ref not in live:
                try:
                    delete_credential(ref, path)
                except Exception:
                    pass

    def rollback(
        self,
        snapshot_id: str,
        *,
        permission_store: Any,
        actor: str = "user",
        approval_id: str | None = None,
        project_id: str | None = None,
        workspace: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        self._authorize(
            permission_store,
            action="settings.write",
            actor=actor,
            approval_id=approval_id,
            project_id=project_id,
            workspace=workspace,
            session_id=session_id,
            turn_id=turn_id,
        )
        match = None
        for item in self._data.get("snapshots") or []:
            if isinstance(item, dict) and item.get("snapshot_id") == snapshot_id:
                match = item
        if match is None:
            raise SettingsError("SETTINGS_SNAPSHOT_NOT_FOUND", "unknown snapshot_id")
        payload = match.get("data") or {}
        self._snapshot("pre-rollback")
        self._data["layers"] = payload.get("layers") or _empty_document()["layers"]
        self._data["history"] = payload.get("history") or {}
        self._data["credentials"] = payload.get("credentials") or {}
        self._data["schema_version"] = SETTINGS_SCHEMA_VERSION
        self._save()
        return {"ok": True, "snapshot_id": snapshot_id, "schema_version": SETTINGS_SCHEMA_VERSION}

    def diagnose(
        self,
        *,
        error_code: str | None = None,
        message: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        catalog: ModelCatalog | None = None,
    ) -> dict[str, Any]:
        kind = "OK" if not (error_code or "").strip() and not (message or "").strip() else classify_model_error(error_code, message)
        summary = None
        if model_id:
            summary = summarize_model(
                provider_id=provider_id or "unknown",
                model_id=model_id,
                catalog=catalog,
            )
        return {
            "ok": kind == "OK",
            "error_kind": kind,
            "key_invalid": kind == "KEY_INVALID",
            "quota_exceeded": kind == "QUOTA_EXCEEDED",
            "model_unavailable": kind == "MODEL_UNAVAILABLE",
            "message": redact_text(message),
            "model_summary": summary,
        }
