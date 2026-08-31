"""PhaseG-B18 plugin market. Assembles skills/MCP into B11; no handlers/."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import urlopen

from .settings import redact_text
from .workspace import PathBoundaryError, canonicalize, is_inside

try:
    from ..config.settings import get_data_dir
except ImportError:
    from config.settings import get_data_dir


NAME_OK = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")


class PluginError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = redact_text(message)


def default_plugin_root() -> Path:
    return get_data_dir() / "plugins"


class PluginService:
    def __init__(
        self,
        root: Path | None = None,
        *,
        persistent: bool = True,
        capabilities: Any = None,
        permission_store: Any = None,
        registry: str | Path | None = None,
    ) -> None:
        self.persistent = persistent
        if root is not None:
            self.root = Path(root)
        elif persistent:
            self.root = default_plugin_root()
        else:
            self.root = Path(tempfile.mkdtemp(prefix="rxy-plugins-"))
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise PluginError("PLUGIN_PATH_UNSAFE", "plugin root must not be a symlink")
        self.root = canonicalize(self.root)
        self._capabilities = capabilities
        self._permissions = permission_store
        self.registry = registry
        self._index: dict[str, dict[str, Any]] = {}
        self._attached = False
        self._load()

    def _authorize(self, action: str) -> None:
        store = self._permissions
        if store is None:
            raise PluginError("PLUGIN_PERMISSION_DENIED", "permission_store required")
        scope = str(self.root)
        verdict = store.evaluate(action=action, actor="user", scope=scope, workspace=scope)
        if verdict != "allow":
            raise PluginError("PLUGIN_PERMISSION_DENIED", "plugin write denied")

    def attach_to_capabilities(self) -> None:
        if self._capabilities is None or self._attached:
            return
        base_skills = self._capabilities._skill_lister
        base_mcp = self._capabilities._mcp_lister
        previous_extra = getattr(self._capabilities, "_extra_lister", None)

        def skills() -> list[dict[str, Any]]:
            return list(base_skills() or []) + self.skill_rows()

        def mcp() -> dict[str, Any]:
            merged = dict(base_mcp() or {})
            merged.update(self.mcp_overlay())
            return merged

        def extra() -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            if previous_extra is not None:
                try:
                    rows.extend(previous_extra() or [])
                except Exception:
                    pass
            rows.extend(self.extra_rows())
            return rows

        self._capabilities._skill_lister = skills
        self._capabilities._mcp_lister = mcp
        self._capabilities._extra_lister = extra
        self._attached = True

    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _load(self) -> None:
        path = self._index_path()
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(raw, dict) and isinstance(raw.get("plugins"), dict):
            loaded = {str(k): dict(v) for k, v in raw["plugins"].items() if isinstance(v, dict)}
            safe: dict[str, dict[str, Any]] = {}
            for name, record in loaded.items():
                dest = Path(str(record.get("path") or ""))
                try:
                    if dest.is_symlink():
                        continue
                    resolved = canonicalize(dest)
                    if resolved == self.root or not is_inside(self.root, resolved):
                        continue
                except (PathBoundaryError, OSError, ValueError):
                    continue
                record["path"] = str(resolved)
                safe[name] = record
            self._index = safe

    def _save(self) -> None:
        if not self.persistent:
            return
        payload = json.dumps({"plugins": self._index}, ensure_ascii=False, indent=2, sort_keys=True)
        fd, tmp = tempfile.mkstemp(prefix="plugins-", suffix=".json", dir=str(self.root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
            os.replace(tmp, self._index_path())
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _safe_name(self, name: str) -> str:
        raw = (name or "").strip()
        if not raw or raw in {".", ".."} or any(ch in raw for ch in "/\\") or any(ch not in NAME_OK for ch in raw):
            raise PluginError("PLUGIN_NAME_INVALID", "invalid plugin name")
        return raw

    def _read_manifest(self, folder: Path) -> dict[str, Any]:
        for filename in ("plugin.json", "manifest.json"):
            path = folder / filename
            if path.is_file() and not path.is_symlink():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise PluginError("PLUGIN_MANIFEST_INVALID", "manifest is not valid json") from exc
                if isinstance(raw, dict):
                    return raw
        raise PluginError("PLUGIN_MANIFEST_INVALID", "plugin.json or manifest.json required")

    def _escaped_token(self, raw: str) -> bool:
        text = str(raw or "").replace("\\", "/")
        if not text:
            return False
        if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
            return True
        return ".." in [part for part in text.split("/") if part]

    def _resolve_member(self, folder: Path, raw: str) -> Path:
        if not raw or self._escaped_token(raw) or "\\" in raw or raw.startswith("/"):
            raise PluginError("PLUGIN_PATH_UNSAFE", "manifest path must be relative with / only")
        target = canonicalize(folder / raw.replace("\\", "/"))
        if not is_inside(canonicalize(folder), target):
            raise PluginError("PLUGIN_PATH_UNSAFE", "manifest path escaped package")
        return target

    def validate_manifest(self, folder: Path) -> dict[str, Any]:
        manifest = self._read_manifest(folder)
        name = self._safe_name(str(manifest.get("name") or ""))
        version = str(manifest.get("version") or "").strip()
        if not VERSION_RE.fullmatch(version):
            raise PluginError("PLUGIN_MANIFEST_INVALID", "version must be semver like 1.0.0")
        for group in ("skills", "commands", "tools"):
            if group in manifest and not isinstance(manifest.get(group), list):
                raise PluginError("PLUGIN_MANIFEST_INVALID", f"{group} must be a list")
            rows = manifest.get(group, [])
            if rows is None:
                rows = []
            if not isinstance(rows, list):
                raise PluginError("PLUGIN_MANIFEST_INVALID", f"{group} must be a list")
            for item in rows:
                if not isinstance(item, dict) or not item.get("name") or not item.get("path"):
                    raise PluginError("PLUGIN_MANIFEST_INVALID", f"{group} entries need name and path")
                self._safe_name(str(item["name"]))
                target = self._resolve_member(folder, str(item["path"]))
                if not target.exists():
                    raise PluginError("PLUGIN_MANIFEST_INVALID", f"{group} path does not exist: {item['path']}")
                if group == "skills":
                    skill_md = target if target.name == "SKILL.md" else target / "SKILL.md"
                    if not skill_md.is_file():
                        raise PluginError("PLUGIN_MANIFEST_INVALID", "skill path must contain SKILL.md")
        if "mcp" in manifest and manifest.get("mcp") is not None and not isinstance(manifest.get("mcp"), dict):
            raise PluginError("PLUGIN_MANIFEST_INVALID", "mcp must be an object")
        mcp = manifest.get("mcp")
        if mcp is None:
            mcp = {}
        if not any((manifest.get("skills") or [], manifest.get("commands") or [], manifest.get("tools") or [], mcp)):
            raise PluginError("PLUGIN_MANIFEST_INVALID", "plugin must declare skills, commands, tools, or mcp")
        for key, spec in mcp.items():
            self._safe_name(str(key))
            if not isinstance(spec, dict):
                raise PluginError("PLUGIN_MANIFEST_INVALID", "mcp entries must be objects")
            self._validate_mcp_spec(folder, spec)
        return {"name": name, "version": version, "manifest": manifest}

    def _validate_mcp_spec(self, folder: Path, spec: dict[str, Any]) -> None:
        for key in ("cwd", "path"):
            if spec.get(key):
                self._resolve_member(folder, str(spec[key]))
        command = str(spec.get("command") or "")
        if command and self._escaped_token(command):
            raise PluginError("PLUGIN_PATH_UNSAFE", "mcp command path escaped package")
        for arg in spec.get("args") or []:
            if not isinstance(arg, str):
                continue
            if self._escaped_token(arg):
                raise PluginError("PLUGIN_PATH_UNSAFE", "mcp arg path escaped package")

    def _copy_tree(self, src: Path, dest: Path) -> None:
        src = canonicalize(src)
        if src.is_symlink() or not src.is_dir():
            raise PluginError("PLUGIN_PATH_UNSAFE", "plugin source must be a real directory")
        dest.mkdir(parents=True, exist_ok=True)
        for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
            current = Path(dirpath)
            if current.is_symlink():
                raise PluginError("PLUGIN_PATH_UNSAFE", "refuse symlink during install")
            for child in list(dirnames) + list(filenames):
                if (current / child).is_symlink():
                    raise PluginError("PLUGIN_PATH_UNSAFE", "refuse symlink during install")
            rel = current.relative_to(src)
            if any(part == ".." for part in rel.parts):
                raise PluginError("PLUGIN_PATH_UNSAFE", "path traversal during install")
            target_dir = dest / rel
            dest_root = canonicalize(dest)
            if not is_inside(dest_root, canonicalize(target_dir)):
                raise PluginError("PLUGIN_PATH_UNSAFE", "copy escaped plugin dir")
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in filenames:
                source_file = current / name
                if source_file.is_symlink():
                    raise PluginError("PLUGIN_PATH_UNSAFE", "refuse symlink file during install")
                shutil.copy2(source_file, target_dir / name)

    def _cap_name(self, plugin: str, raw: str) -> str:
        return f"{plugin}.{raw}"

    def _capability_ids(self, plugin: str, manifest: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for item in manifest.get("skills") or []:
            if isinstance(item, dict) and item.get("name"):
                ids.append(f"skill:{self._cap_name(plugin, str(item['name']))}")
        for item in manifest.get("commands") or []:
            if isinstance(item, dict) and item.get("name"):
                ids.append(f"command:{self._cap_name(plugin, str(item['name']))}")
        for item in manifest.get("tools") or []:
            if isinstance(item, dict) and item.get("name"):
                ids.append(f"tool:{self._cap_name(plugin, str(item['name']))}")
        for key in manifest.get("mcp") or {}:
            ids.append(f"mcp:{self._cap_name(plugin, str(key))}")
        return ids

    def _record(self, name: str, version: str, dest: Path, manifest: dict[str, Any], *, source: str) -> dict[str, Any]:
        record = {
            "name": name,
            "version": version,
            "path": str(dest),
            "source": source,
            "enabled": True,
            "capability_ids": self._capability_ids(name, manifest),
            "manifest": {
                "skills": manifest.get("skills") or [],
                "commands": manifest.get("commands") or [],
                "tools": manifest.get("tools") or [],
                "mcp": manifest.get("mcp") or {},
            },
        }
        self._index[name] = record
        self._save()
        return dict(record)

    def skill_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in self._index.values():
            if record.get("enabled") is False:
                continue
            dest = Path(str(record.get("path") or ""))
            for item in record.get("manifest", {}).get("skills") or []:
                if not isinstance(item, dict):
                    continue
                rel = str(item.get("path") or "")
                try:
                    folder = self._resolve_member(dest, rel)
                except PluginError:
                    continue
                if folder.is_file():
                    folder = folder.parent
                rows.append(
                    {
                        "name": self._cap_name(str(record["name"]), str(item.get("name") or "")),
                        "path": str(folder),
                        "has_skill_md": (folder / "SKILL.md").is_file(),
                        "plugin": record["name"],
                    }
                )
        return rows

    def extra_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in self._index.values():
            if record.get("enabled") is False:
                continue
            dest = Path(str(record.get("path") or ""))
            for group, kind in (("commands", "command"), ("tools", "tool")):
                for item in record.get("manifest", {}).get(group) or []:
                    if not isinstance(item, dict) or not item.get("name"):
                        continue
                    rel = str(item.get("path") or "")
                    try:
                        target = self._resolve_member(dest, rel)
                    except PluginError:
                        continue
                    cap_id = f"{kind}:{self._cap_name(str(record['name']), str(item['name']))}"
                    enabled = True
                    authorized = False
                    if self._capabilities is not None:
                        enabled = bool(self._capabilities._enabled(cap_id, default=True))
                        authorized = bool(self._capabilities._authorized_flag(cap_id))
                    rows.append(
                        {
                            "capability_id": cap_id,
                            "kind": kind,
                            "name": self._cap_name(str(record["name"]), str(item["name"])),
                            "source": f"plugin:{record['name']}",
                            "installed": target.exists(),
                            "enabled": enabled,
                            "authorized": authorized,
                            "available": target.exists() and enabled and authorized,
                            "connection": "n/a",
                            "permissions": [f"{kind}.invoke"],
                            "origin": str(target),
                            "locator": cap_id,
                            "error": None,
                            "cancellable": True,
                            "copyable": True,
                            "collapsible": True,
                            "plugin": record["name"],
                        }
                    )
        return rows

    def mcp_overlay(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for record in self._index.values():
            if record.get("enabled") is False:
                continue
            dest = Path(str(record.get("path") or ""))
            mcp = record.get("manifest", {}).get("mcp") or {}
            if not isinstance(mcp, dict):
                continue
            for key, spec in mcp.items():
                if not isinstance(spec, dict):
                    continue
                rewritten = dict(spec)
                for field in ("cwd", "path"):
                    if rewritten.get(field):
                        rewritten[field] = str(self._resolve_member(dest, str(rewritten[field])))
                merged[self._cap_name(str(record["name"]), str(key))] = rewritten
        return merged

    def list_plugins(self) -> dict[str, Any]:
        return {"plugins": [dict(item) for item in self._index.values()], "root": str(self.root)}

    def _load_registry(self) -> list[dict[str, Any]]:
        if self.registry is None:
            return []
        raw = str(self.registry)
        if raw.startswith("http://") or raw.startswith("https://"):
            try:
                with urlopen(raw, timeout=5) as resp:  # noqa: S310 — configurable registry, tests use file
                    payload = json.loads(resp.read().decode("utf-8"))
            except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                raise PluginError("PLUGIN_REGISTRY_UNAVAILABLE", "registry fetch failed") from exc
        else:
            path = Path(raw)
            index = path / "registry.json" if path.is_dir() else path
            try:
                payload = json.loads(index.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PluginError("PLUGIN_REGISTRY_UNAVAILABLE", "registry index missing") from exc
        rows = payload.get("plugins") if isinstance(payload, dict) else payload
        return [row for row in rows or [] if isinstance(row, dict)]

    def _is_http(self, raw: str) -> bool:
        return raw.startswith("http://") or raw.startswith("https://")

    def _extract_zip(self, archive: Path) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="rxy-plugin-zip-"))
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or self._escaped_token(name) or any(part == ".." for part in Path(name).parts):
                    raise PluginError("PLUGIN_PATH_UNSAFE", "zip slip rejected")
                if ((info.external_attr >> 16) & 0xF000) == 0xA000:
                    raise PluginError("PLUGIN_PATH_UNSAFE", "zip symlink rejected")
            zf.extractall(tmp)
        for child in tmp.rglob("*"):
            if child.is_symlink():
                shutil.rmtree(tmp, ignore_errors=True)
                raise PluginError("PLUGIN_PATH_UNSAFE", "zip produced a symlink")
        if (tmp / "plugin.json").is_file() or (tmp / "manifest.json").is_file():
            return tmp
        children = [child for child in tmp.iterdir() if child.is_dir() and not child.name.startswith(".")]
        if len(children) == 1 and ((children[0] / "plugin.json").is_file() or (children[0] / "manifest.json").is_file()):
            return children[0]
        raise PluginError("PLUGIN_MANIFEST_INVALID", "zip does not contain a plugin manifest")

    def _fetch_remote_plugin(self, url: str) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="rxy-plugin-dl-"))
        archive = tmp / "pkg.bin"
        try:
            with urlopen(url, timeout=10) as resp:
                archive.write_bytes(resp.read())
        except (URLError, TimeoutError, OSError) as exc:
            raise PluginError("PLUGIN_REGISTRY_UNAVAILABLE", "plugin package fetch failed") from exc
        if zipfile.is_zipfile(archive):
            return self._extract_zip(archive)
        raise PluginError("PLUGIN_SOURCE_INVALID", "remote plugin must be a zip package")

    def _open_package(self, raw: Path) -> Path:
        if raw.is_file() and zipfile.is_zipfile(raw):
            return self._extract_zip(raw)
        return raw

    def _source_from_registry(self, name: str) -> Path:
        wanted = self._safe_name(name)
        registry = str(self.registry or "")
        for row in self._load_registry():
            if str(row.get("name") or "") != wanted:
                continue
            url = str(row.get("url") or "")
            raw_path = str(row.get("path") or "")
            loc = url or raw_path
            if not loc:
                continue
            if self._is_http(loc):
                return self._fetch_remote_plugin(loc)
            if self._is_http(registry):
                return self._fetch_remote_plugin(urljoin(registry, loc))
            base = Path(registry)
            root = canonicalize(base if base.is_dir() else base.parent)
            folder = Path(loc) if os.path.isabs(loc) else (base / loc if base.is_dir() else base.parent / loc)
            if folder.is_symlink():
                raise PluginError("PLUGIN_PATH_UNSAFE", "registry package is a symlink")
            resolved = canonicalize(folder)
            if not is_inside(root, resolved):
                raise PluginError("PLUGIN_PATH_UNSAFE", "registry path escaped registry root")
            return self._open_package(resolved)
        raise PluginError("PLUGIN_NOT_FOUND", f"registry has no plugin {wanted}")

    def _forget_capabilities(self, cap_ids: list[str]) -> None:
        if self._capabilities is None:
            return
        data = getattr(self._capabilities, "_data", None)
        if not isinstance(data, dict):
            return
        for bucket in ("enabled", "authorized"):
            flags = data.setdefault(bucket, {})
            if isinstance(flags, dict):
                for cap_id in cap_ids:
                    flags.pop(cap_id, None)
        saver = getattr(self._capabilities, "_save", None)
        if callable(saver):
            saver()

    def install(self, *, source: str, path: str | None = None, name: str | None = None) -> dict[str, Any]:
        self._authorize("capability.write")
        kind = (source or "").strip().lower()
        if kind == "registry":
            src = self._source_from_registry(str(name or ""))
            origin = "registry"
        elif kind in {"url", "github"}:
            loc = str(path or name or "")
            if not self._is_http(loc):
                raise PluginError("PLUGIN_SOURCE_INVALID", "github/url install requires an http(s) zip")
            src = self._fetch_remote_plugin(loc)
            origin = "github" if kind == "github" else "url"
        elif kind == "local":
            if not path:
                raise PluginError("PLUGIN_SOURCE_INVALID", "local install requires path")
            raw = Path(path)
            if raw.is_symlink():
                raise PluginError("PLUGIN_PATH_UNSAFE", "plugin source must not be a symlink")
            src = self._open_package(canonicalize(raw))
            origin = "local"
        else:
            raise PluginError("PLUGIN_SOURCE_INVALID", "source must be local, registry, url, or github")
        if src.is_symlink() or not src.is_dir():
            raise PluginError("PLUGIN_PATH_UNSAFE", "plugin source must be a real directory")
        checked = self.validate_manifest(src)
        plugin_name = checked["name"]
        if plugin_name in self._index:
            raise PluginError("PLUGIN_ALREADY_INSTALLED", f"{plugin_name} already installed")
        dest = self.root / plugin_name
        if dest.is_symlink():
            raise PluginError("PLUGIN_PATH_UNSAFE", "plugin dest is a symlink")
        if dest.exists():
            leftovers = [item for item in dest.iterdir() if item.name != "user.json"]
            if leftovers:
                raise PluginError("PLUGIN_ALREADY_INSTALLED", f"{plugin_name} directory exists")
        staging = self.root / f".install-{plugin_name}-{uuid.uuid4().hex[:8]}"
        try:
            self._copy_tree(src, staging)
            installed = self.validate_manifest(staging)
            user_keep = dest / "user.json" if dest.exists() else None
            kept = user_keep.read_text(encoding="utf-8") if user_keep and user_keep.is_file() and not user_keep.is_symlink() else None
            if dest.exists():
                shutil.rmtree(dest)
            os.replace(staging, dest)
            if kept is not None:
                (dest / "user.json").write_text(kept, encoding="utf-8")
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
        try:
            record = self._record(installed["name"], installed["version"], dest, installed["manifest"], source=origin)
        except Exception:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            raise
        return {"ok": True, "plugin": record}

    def toggle(self, name: str, enabled: object) -> dict[str, Any]:
        self._authorize("capability.write")
        if enabled is not True and enabled is not False:
            raise PluginError("PLUGIN_TOGGLE_INVALID", "plugin/toggle requires enabled boolean")
        plugin_name = self._safe_name(name)
        record = self._index.get(plugin_name)
        if record is None:
            raise PluginError("PLUGIN_NOT_FOUND", f"unknown plugin {plugin_name}")
        if enabled is True:
            record["enabled"] = True
            self._save()
        if self._capabilities is not None:
            for cap_id in record.get("capability_ids") or []:
                try:
                    self._capabilities.set_enabled(
                        str(cap_id),
                        bool(enabled),
                        permission_store=self._permissions,
                    )
                except Exception as exc:
                    code = getattr(exc, "code", "")
                    if code in {"CAPABILITY_UNAVAILABLE", "CAPABILITY_NOT_FOUND"}:
                        continue
                    raise PluginError(code or "PLUGIN_TOGGLE_FAILED", str(exc)) from exc
        record["enabled"] = bool(enabled)
        self._save()
        return {"name": plugin_name, "enabled": bool(enabled), "capability_ids": list(record.get("capability_ids") or [])}

    def uninstall(self, name: str, *, keep_user_config: object = False) -> dict[str, Any]:
        self._authorize("capability.write")
        if keep_user_config is not True and keep_user_config is not False:
            raise PluginError("PLUGIN_UNINSTALL_INVALID", "keep_user_config must be boolean")
        keep_user_config = keep_user_config is True
        plugin_name = self._safe_name(name)
        record = self._index.get(plugin_name)
        if record is None:
            raise PluginError("PLUGIN_NOT_FOUND", f"unknown plugin {plugin_name}")
        cap_ids = [str(item) for item in record.get("capability_ids") or []]
        dest = Path(str(record.get("path") or self.root / plugin_name))
        root = canonicalize(self.root)
        try:
            target = canonicalize(dest)
        except (PathBoundaryError, OSError) as exc:
            raise PluginError("PLUGIN_PATH_UNSAFE", "cannot resolve plugin dir") from exc
        if target == root or not is_inside(root, target):
            raise PluginError("PLUGIN_PATH_UNSAFE", "refuse to delete outside plugin root")
        if target.is_symlink():
            raise PluginError("PLUGIN_PATH_UNSAFE", "refuse to delete symlink plugin dir")
        if self._capabilities is not None:
            for cap_id in cap_ids:
                try:
                    self._capabilities.set_enabled(
                        cap_id,
                        False,
                        authorize=False,
                        permission_store=self._permissions,
                    )
                except Exception:
                    pass
        kept = None
        if target.is_dir():
            user = target / "user.json"
            if keep_user_config and user.is_file() and not user.is_symlink():
                kept = user.read_text(encoding="utf-8")
            try:
                shutil.rmtree(target)
            except OSError as exc:
                raise PluginError("PLUGIN_UNINSTALL_INCOMPLETE", "failed to remove plugin files") from exc
            if kept is not None:
                target.mkdir(parents=True, exist_ok=True)
                (target / "user.json").write_text(kept, encoding="utf-8")
        self._index.pop(plugin_name, None)
        self._save()
        self._forget_capabilities(cap_ids)
        return {"ok": True, "name": plugin_name, "keep_user_config": bool(keep_user_config), "removed": True}
