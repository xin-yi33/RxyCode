"""PhaseG-B13 runtime packaging, version bind, update rollback, crash redaction."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import redact_text

try:
    from protocol.version import APPSERVER_VERSION, PROTOCOL_VERSION
except ImportError:
    from protocol.version import APPSERVER_VERSION, PROTOCOL_VERSION

PLATFORMS = ("windows", "macos", "linux")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def host_platform() -> str:
    system = platform.system().lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


def schema_digest(schema_path: Path | None = None) -> str:
    path = schema_path or Path(__file__).resolve().parents[1] / "protocol" / "schema.json"
    data = path.read_bytes() if path.is_file() else b""
    data = data.replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(data).hexdigest()


class ReleaseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ReleaseService:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(tempfile.mkdtemp(prefix="rxy-release-"))
        self.root.mkdir(parents=True, exist_ok=True)
        self._legacy = self.root / "current"
        self._legacy.mkdir(parents=True, exist_ok=True)

    @property
    def current_dir(self) -> Path:
        pointer = self.root / "CURRENT.txt"
        if pointer.is_file():
            target = self.root / pointer.read_text(encoding="utf-8").strip()
            if target.is_dir():
                return target
        return self._legacy

    def runtime_manifests(self) -> dict[str, Any]:
        base = Path(__file__).resolve().parents[1] / "packaging" / "runtimes"
        rows = {}
        for name in PLATFORMS:
            path = base / f"{name}.json"
            if path.is_file():
                rows[name] = json.loads(path.read_text(encoding="utf-8"))
        return rows

    def compatibility(self) -> dict[str, Any]:
        digest = schema_digest()
        runtimes = self.runtime_manifests()
        compatible = set(runtimes) == set(PLATFORMS)
        for name in PLATFORMS:
            spec = runtimes.get(name) or {}
            if spec.get("platform") != name:
                compatible = False
            if spec.get("protocol_version") != PROTOCOL_VERSION:
                compatible = False
            if spec.get("appserver_version") != APPSERVER_VERSION:
                compatible = False
            if spec.get("schema_digest") != digest:
                compatible = False
        return {
            "platform": host_platform(),
            "platforms": list(PLATFORMS),
            "runtimes": runtimes,
            "appserver_version": APPSERVER_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "schema_digest": digest,
            "python": platform.python_version(),
            "compatible": compatible,
        }

    def diagnose_mismatch(self, client: dict[str, Any]) -> dict[str, Any]:
        server = self.compatibility()
        reasons: list[str] = []
        if client.get("protocol_version") and client["protocol_version"] != server["protocol_version"]:
            reasons.append("PROTOCOL_MISMATCH")
        if client.get("appserver_version") and client["appserver_version"] != server["appserver_version"]:
            reasons.append("APPSERVER_VERSION_MISMATCH")
        if client.get("schema_digest") and client["schema_digest"] != server["schema_digest"]:
            reasons.append("SCHEMA_DIGEST_MISMATCH")
        return {
            "ok": not reasons,
            "reasons": reasons,
            "server": server,
            "client": {
                key: client.get(key)
                for key in ("protocol_version", "appserver_version", "schema_digest")
            },
        }

    def _bound_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        bound = dict(payload)
        expected = self.compatibility()
        for key in ("protocol_version", "appserver_version", "schema_digest"):
            if key not in bound:
                bound[key] = expected[key]
            elif bound[key] != expected[key]:
                raise ReleaseError("VERSION_BIND_MISMATCH", f"{key} does not match runtime bind")
        return bound

    def stage_update(self, payload: dict[str, Any], *, fail: bool = False) -> dict[str, Any]:
        """Write a new version beside current. Failure never deletes current."""
        old_dir = self.current_dir
        old = (old_dir / "manifest.json").read_text(encoding="utf-8") if (old_dir / "manifest.json").is_file() else None
        version_id = "v-" + hashlib.sha1(os.urandom(8)).hexdigest()[:10]
        staged = self.root / version_id
        staged.mkdir(parents=True)
        bound = self._bound_payload(payload)
        manifest = {
            "created_at": _now(),
            "payload": bound,
            "checksum": "sha256:" + hashlib.sha256(json.dumps(bound, sort_keys=True).encode()).hexdigest(),
        }
        (staged / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if fail:
            shutil.rmtree(staged)
            raise ReleaseError("UPDATE_FAILED", "update failed; previous version kept")
        pointer = self.root / "CURRENT.txt"
        tmp_pointer = self.root / f"CURRENT.{version_id}.tmp"
        tmp_pointer.write_text(version_id, encoding="utf-8")
        os.replace(str(tmp_pointer), str(pointer))
        return {
            "ok": True,
            "manifest": manifest,
            "previous_kept": old is not None or old_dir.exists(),
            "version_id": version_id,
        }

    def crash_report(self, *, secret: str, prompt: str, tool_output: str, traceback: str) -> dict[str, Any]:
        report = {
            "created_at": _now(),
            "traceback": redact_text(traceback, secret, prompt, tool_output),
            "prompt": "[REDACTED]",
            "tool_output": "[REDACTED]",
            "secret": "[REDACTED]",
        }
        text = json.dumps(report)
        if secret in text or prompt in text or tool_output in text:
            raise ReleaseError("CRASH_LEAK", "refusing to emit a leaky crash report")
        return report

    def diagnose_bundle(self) -> dict[str, Any]:
        files = {}
        for path in self.current_dir.rglob("*"):
            if path.is_file() and path.name not in {"CHECKSUMS.json", "CHECKSUMS.sha256"}:
                files[str(path.relative_to(self.current_dir)).replace("\\", "/")] = (
                    "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                )
        bundle = {
            "platform": host_platform(),
            "compatibility": self.compatibility(),
            "checksums": files,
            "created_at": _now(),
        }
        checksums_path = self.current_dir / "CHECKSUMS.json"
        checksums_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
        (self.current_dir / "CHECKSUMS.sha256").write_text(
            "sha256:" + hashlib.sha256(checksums_path.read_bytes()).hexdigest() + "\n",
            encoding="utf-8",
        )
        bundle["path"] = str(checksums_path)
        return bundle

    def rollback(self) -> dict[str, Any]:
        """Point CURRENT.txt back at the previous version directory."""
        pointer = self.root / "CURRENT.txt"
        current_id = pointer.read_text(encoding="utf-8").strip() if pointer.is_file() else ""
        versions = sorted(
            [path for path in self.root.iterdir() if path.is_dir() and path.name.startswith("v-")],
            key=lambda item: item.stat().st_mtime,
        )
        previous = None
        for path in reversed(versions):
            if path.name != current_id:
                previous = path
                break
        if previous is None:
            raise ReleaseError("ROLLBACK_UNAVAILABLE", "no previous version to restore")
        tmp = self.root / f"CURRENT.rollback.{previous.name}.tmp"
        tmp.write_text(previous.name, encoding="utf-8")
        os.replace(str(tmp), str(pointer))
        return {"ok": True, "version_id": previous.name, "current": str(self.current_dir)}

    def sign_entry(self, path: Path) -> dict[str, Any]:
        """Signing/notarization hook. Does not invent a signature."""
        if not path.exists():
            raise ReleaseError("SIGN_TARGET_MISSING", "nothing to sign")
        return {
            "path": str(path),
            "signed": False,
            "notary": False,
            "entry": "packaging/sign",
            "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
