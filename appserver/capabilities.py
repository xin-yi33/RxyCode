"""PhaseG-B11 capability / skill / MCP / browser projections.

External abilities are listed and invoked through this service. Browser is a
normal capability: it never bypasses Tool / Approval / Review. Failures are
terminal and cancellable so a Thread cannot stay stuck.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .review import ReviewError
from .settings import redact_text

KINDS = ("skill", "mcp", "browser", "cli")
JOB_STATES = ("started", "progress", "completed", "failed", "cancelled")


class CapabilityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_skills() -> list[dict[str, Any]]:
    try:
        from tools.skill_manager import list_installed_skills

        return list(list_installed_skills() or [])
    except Exception:
        return []


def _default_mcp() -> dict[str, Any]:
    try:
        from tools.mcp_manager import get_mcp_config

        value = get_mcp_config()
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


class CapabilityService:
    def __init__(
        self,
        path: Path | None = None,
        *,
        persistent: bool = True,
        skill_lister: Callable[[], list[dict[str, Any]]] | None = None,
        mcp_lister: Callable[[], dict[str, Any]] | None = None,
        execution_store: Any = None,
        review_service: Any = None,
        mcp_invoker: Callable[..., Any] | None = None,
        invoke_timeout_s: float = 2.0,
        cli_lister: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.persistent = persistent
        self.path = path or Path(os.environ.get("RXYCODE_DATA_DIR", ".")) / "desktop" / "capabilities.json"
        if persistent:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._skill_lister = skill_lister or _default_skills
        self._mcp_lister = mcp_lister or _default_mcp
        self._execution = execution_store
        self._reviews = review_service
        self._mcp_invoker = mcp_invoker
        self._invoke_timeout_s = invoke_timeout_s
        self._cli_lister = cli_lister
        self._cancel_flags: dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {
            "enabled": {},
            "authorized": {},
            "audit": [],
            "jobs": {},
        }
        self._jobs: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.persistent:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(raw, dict):
            self._data.update(raw)
            if not isinstance(self._data.get("enabled"), dict):
                self._data["enabled"] = {}
            if not isinstance(self._data.get("authorized"), dict):
                self._data["authorized"] = {}
            if not isinstance(self._data.get("audit"), list):
                self._data["audit"] = []

    def _save(self) -> None:
        if not self.persistent:
            return
        payload = json.dumps(
            {
                "enabled": self._data.get("enabled") or {},
                "authorized": self._data.get("authorized") or {},
                "audit": (self._data.get("audit") or [])[-200:],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="caps-", suffix=".json", dir=self.path.parent)
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

    def _audit(self, **fields: Any) -> dict[str, Any]:
        record = {
            "audit_id": uuid.uuid4().hex[:12],
            "created_at": _now(),
            **{key: redact_text(value) if isinstance(value, str) else value for key, value in fields.items()},
        }
        self._data.setdefault("audit", []).append(record)
        self._save()
        return dict(record)

    def _enabled(self, capability_id: str, default: bool = True) -> bool:
        flags = self._data.get("enabled") or {}
        if capability_id not in flags:
            return default
        return bool(flags[capability_id])

    def _authorized_flag(self, capability_id: str) -> bool:
        flags = self._data.get("authorized") or {}
        if capability_id not in flags:
            return False
        return bool(flags[capability_id])

    def _project_skills(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in self._skill_lister() or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            cap_id = f"skill:{name}"
            skill_md = Path(str(item.get("path") or "")) / "SKILL.md"
            installed = skill_md.is_file()
            enabled = self._enabled(cap_id, default=True)
            authorized = self._authorized_flag(cap_id)
            available = installed and enabled and authorized
            locator = str(item.get("path") or "")
            rows.append(
                {
                    "capability_id": cap_id,
                    "kind": "skill",
                    "name": name,
                    "source": "local-skill",
                    "installed": installed,
                    "enabled": enabled,
                    "authorized": authorized,
                    "available": available,
                    "connection": "n/a",
                    "permissions": ["skill.invoke"],
                    "origin": locator,
                    "locator": f"skill:{name}/SKILL.md",
                    "error": None if installed else "skill missing SKILL.md",
                    "cancellable": True,
                    "copyable": True,
                    "collapsible": True,
                }
            )
        return rows

    def _project_mcp(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        config = self._mcp_lister() or {}
        for name, spec in config.items():
            cap_id = f"mcp:{name}"
            installed = True
            enabled = self._enabled(cap_id, default=True)
            authorized = self._authorized_flag(cap_id)
            connected = False
            if isinstance(spec, dict):
                connected = bool(spec.get("connected"))
            available = installed and enabled and authorized and connected
            rows.append(
                {
                    "capability_id": cap_id,
                    "kind": "mcp",
                    "name": str(name),
                    "source": "mcp-config",
                    "installed": installed,
                    "enabled": enabled,
                    "authorized": authorized,
                    "available": available,
                    "connection": "connected" if connected else "disconnected",
                    "permissions": ["mcp.invoke"],
                    "origin": str(name),
                    "locator": f"mcp:{name}",
                    "error": None if connected else "mcp disconnected",
                    "cancellable": True,
                    "copyable": True,
                    "collapsible": True,
                    "command_hidden": True,
                }
            )
        return rows

    def _project_browser(self) -> dict[str, Any]:
        cap_id = "browser"
        enabled = self._enabled(cap_id, default=False)
        authorized = self._authorized_flag(cap_id)
        return {
            "capability_id": cap_id,
            "kind": "browser",
            "name": "browser",
            "source": "appserver",
            "installed": False,
            "enabled": enabled,
            "authorized": authorized,
            "available": False,
            "connection": "n/a",
            "permissions": ["browser", "approval", "review"],
            "origin": "appserver",
            "locator": "capability:browser",
            "error": "browser automation is not implemented; no bypass window",
            "cancellable": True,
            "copyable": True,
            "collapsible": True,
            "bypass": False,
        }

    def _project_cli(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if self._cli_lister is None:
            return rows
        try:
            payload = self._cli_lister() or {}
        except Exception:
            return rows
        tools = payload.get("tools")
        software = payload.get("software") if not tools else None
        items = tools if isinstance(tools, list) else (software or [])
        for item in items:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "cli-hub")
            if source not in {"builtin", "cli-hub", "self-generated"}:
                source = "cli-hub"
            cap_id = str(item.get("id") or "")
            if not cap_id:
                continue
            installed = bool(item.get("installed"))
            enabled = self._enabled(cap_id, default=True)
            authorized = self._authorized_flag(cap_id)
            rows.append(
                {
                    "capability_id": cap_id,
                    "kind": "cli",
                    "name": str(item.get("name") or cap_id),
                    "source": source,
                    "installed": installed,
                    "enabled": enabled,
                    "authorized": authorized,
                    "available": installed and enabled and authorized,
                    "connection": "n/a",
                    "permissions": ["cli.list", "cli.run"],
                    "origin": "cli-hub",
                    "locator": cap_id,
                    "error": None,
                    "cancellable": True,
                    "copyable": True,
                    "collapsible": True,
                    "tool_metadata": {
                        "software_id": cap_id,
                        "source": source,
                        "namespace": "cli",
                        "agent_tools": ["cli_list", "cli_run"],
                    },
                }
            )
        return rows

    def list(self, *, kind: str | None = None, available_only: bool = False) -> dict[str, Any]:
        rows = self._project_skills() + self._project_mcp() + [self._project_browser()] + self._project_cli()
        if kind:
            rows = [row for row in rows if row["kind"] == kind]
        if available_only:
            rows = [row for row in rows if row["available"]]
        return {"capabilities": rows, "browser_implemented": False}

    def get(self, capability_id: str) -> dict[str, Any]:
        for row in self.list()["capabilities"]:
            if row["capability_id"] == capability_id:
                return row
        raise CapabilityError("CAPABILITY_NOT_FOUND", f"unknown capability: {capability_id}")

    def _authorize_write(
        self,
        permission_store: Any,
        *,
        action: str,
        actor: str,
        session_id: str | None,
        approval_id: str | None,
        project_id: str | None,
        workspace: str | None,
    ) -> None:
        if permission_store is None:
            self._audit(action=action, status="denied", error_code="CAPABILITY_PERMISSION_DENIED")
            raise CapabilityError("CAPABILITY_PERMISSION_DENIED", "permission_store required")
        if actor == "auto_review":
            self._audit(action=action, status="denied", error_code="CAPABILITY_PERMISSION_DENIED", actor=actor)
            raise CapabilityError("CAPABILITY_PERMISSION_DENIED", "auto_review cannot change capabilities")
        from .workspace import PathBoundaryError, canonicalize

        if workspace:
            try:
                scope = str(canonicalize(workspace))
            except (PathBoundaryError, OSError, ValueError):
                scope = str(workspace)
        else:
            scope = str(self.path.parent)
        verdict = permission_store.evaluate(
            action=action,
            actor=actor,
            approval_id=approval_id,
            scope=scope,
            project_id=project_id,
            workspace=scope,
            session_id=session_id,
        )
        self._audit(action="approval", capability_action=action, verdict=verdict)
        if verdict != "allow":
            self._audit(action=action, status="denied", error_code="CAPABILITY_PERMISSION_DENIED")
            raise CapabilityError("CAPABILITY_PERMISSION_DENIED", "capability write denied")

    def set_enabled(
        self,
        capability_id: str,
        enabled: bool,
        *,
        authorize: bool | None = None,
        permission_store: Any,
        actor: str = "user",
        session_id: str | None = None,
        approval_id: str | None = None,
        project_id: str | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        if capability_id == "browser" and enabled:
            self._audit(action="set_enabled", capability_id="browser", status="denied", error_code="BROWSER_NOT_IMPLEMENTED")
            raise CapabilityError("BROWSER_NOT_IMPLEMENTED", "browser cannot be enabled as a bypass")
        if capability_id != "browser":
            try:
                projection = self.get(capability_id)
            except CapabilityError as exc:
                self._audit(action="set_enabled", capability_id=capability_id, status="denied", error_code=exc.code)
                raise
            if not projection.get("installed"):
                self._audit(action="set_enabled", capability_id=capability_id, status="denied", error_code="CAPABILITY_UNAVAILABLE")
                raise CapabilityError("CAPABILITY_UNAVAILABLE", "cannot enable an uninstalled capability")
        self._authorize_write(
            permission_store,
            action="capability.write",
            actor=actor,
            session_id=session_id,
            approval_id=approval_id,
            project_id=project_id,
            workspace=workspace,
        )
        self._data.setdefault("enabled", {})[capability_id] = bool(enabled)
        if authorize is not None:
            self._data.setdefault("authorized", {})[capability_id] = bool(authorize)
        self._audit(
            action="set_enabled",
            capability_id=capability_id,
            enabled=bool(enabled),
            authorized=self._authorized_flag(capability_id),
        )
        return self.get(capability_id) if capability_id == "browser" or any(
            row["capability_id"] == capability_id for row in self.list()["capabilities"]
        ) else {
            "capability_id": capability_id,
            "enabled": bool(enabled),
            "authorized": self._authorized_flag(capability_id),
            "available": False,
        }

    def invoke(
        self,
        capability_id: str,
        *,
        permission_store: Any,
        session_id: str | None = None,
        turn_id: str | None = None,
        actor: str = "user",
        approval_id: str | None = None,
        project_id: str | None = None,
        workspace: str | None = None,
        hang: bool = False,
        force_fail: bool = False,
        background: bool = False,
    ) -> dict[str, Any]:
        """Start a cancellable capability job. hang/force_fail are test hooks."""
        chain: list[dict[str, Any]] = []
        task_id = self._start_tool(capability_id, session_id)
        if task_id:
            chain.append({"step": "tool", "task_id": task_id, "status": "started"})
        else:
            chain.append({"step": "tool", "status": "started"})
        try:
            self._authorize_write(
                permission_store,
                action="capability.invoke",
                actor=actor,
                session_id=session_id,
                approval_id=approval_id,
                project_id=project_id,
                workspace=workspace,
            )
        except CapabilityError as exc:
            chain.append({"step": "approval", "status": "reject", "bypass": False})
            self._finish_tool(task_id, "failed")
            job = self._new_job(
                capability_id,
                session_id,
                turn_id,
                "failed",
                exc.code,
                self._result_payload(capability_id, chain, None),
            )
            self._audit(action="invoke", capability_id=capability_id, status="failed", job_id=job["job_id"], error_code=exc.code)
            return job
        chain.append({"step": "approval", "status": "allow", "bypass": False})
        review_step = self._review_step(capability_id, session_id, workspace)
        chain.append(review_step)
        if review_step.get("status") not in {"passed", "approved"}:
            self._finish_tool(task_id, "failed")
            job = self._new_job(
                capability_id,
                session_id,
                turn_id,
                "failed",
                "REVIEW_BLOCKED",
                self._result_payload(capability_id, chain, None),
            )
            self._audit(action="invoke", capability_id=capability_id, status="failed", job_id=job["job_id"], error_code="REVIEW_BLOCKED")
            return job
        projection: dict[str, Any] | None = None
        if capability_id != "browser":
            try:
                projection = self.get(capability_id)
            except CapabilityError:
                self._finish_tool(task_id, "failed")
                job = self._new_job(
                    capability_id,
                    session_id,
                    turn_id,
                    "failed",
                    "CAPABILITY_NOT_FOUND",
                    self._result_payload(capability_id, chain, None),
                )
                self._audit(action="invoke", capability_id=capability_id, status="failed", job_id=job["job_id"])
                return job
            if not projection["installed"] or not projection["authorized"] or not projection["enabled"]:
                self._finish_tool(task_id, "failed")
                job = self._new_job(
                    capability_id,
                    session_id,
                    turn_id,
                    "failed",
                    "CAPABILITY_UNAVAILABLE",
                    self._result_payload(capability_id, chain, projection),
                )
                self._audit(action="invoke", capability_id=capability_id, status="failed", job_id=job["job_id"])
                return job
            if projection["kind"] == "mcp" and projection["connection"] != "connected":
                self._finish_tool(task_id, "failed")
                job = self._new_job(
                    capability_id,
                    session_id,
                    turn_id,
                    "failed",
                    "CAPABILITY_DISCONNECTED",
                    self._result_payload(capability_id, chain, projection),
                )
                self._audit(action="invoke", capability_id=capability_id, status="failed", job_id=job["job_id"])
                return job
        job = self._new_job(
            capability_id,
            session_id,
            turn_id,
            "started",
            None,
            self._result_payload(capability_id, chain, projection),
        )
        job["task_id"] = task_id
        self._jobs[job["job_id"]]["task_id"] = task_id
        flag = threading.Event()
        self._cancel_flags[job["job_id"]] = flag
        self._audit(action="invoke", capability_id=capability_id, status="started", job_id=job["job_id"])

        def runner() -> None:
            self._run_job(
                job["job_id"],
                capability_id,
                projection,
                chain,
                task_id,
                flag,
                force_fail=force_fail,
                hang=hang,
            )

        if background or hang:
            threading.Thread(target=runner, daemon=True).start()
            return dict(self._jobs[job["job_id"]])
        runner()
        return dict(self._jobs[job["job_id"]])

    def _run_job(
        self,
        job_id: str,
        capability_id: str,
        projection: dict[str, Any] | None,
        chain: list[dict[str, Any]],
        task_id: str | None,
        flag: threading.Event,
        *,
        force_fail: bool,
        hang: bool,
    ) -> None:
        job = self._jobs[job_id]
        deadline = time.monotonic() + max(0.05, float(self._invoke_timeout_s))
        try:
            if hang:
                while time.monotonic() < deadline:
                    if flag.is_set():
                        raise CapabilityError("CAPABILITY_CANCELLED", "cancelled")
                    time.sleep(0.01)
                raise CapabilityError("CAPABILITY_TIMEOUT", "capability timed out")
            if capability_id == "browser":
                raise CapabilityError("BROWSER_NOT_IMPLEMENTED", "browser is not a bypass window")
            if force_fail:
                raise CapabilityError("CAPABILITY_INVOKE_FAILED", "forced capability failure")
            if flag.is_set():
                raise CapabilityError("CAPABILITY_CANCELLED", "cancelled")
            payload = self._execute_projection(projection, flag)
            payload["chain"] = chain
            if time.monotonic() > deadline:
                raise CapabilityError("CAPABILITY_TIMEOUT", "capability timed out")
            self._finalize_job(job, "completed", None, payload, task_id, "succeeded")
            self._audit(
                action="invoke",
                capability_id=capability_id,
                status="completed",
                job_id=job_id,
                locator=(projection or {}).get("locator"),
            )
        except CapabilityError as exc:
            if flag.is_set() and exc.code != "CAPABILITY_TIMEOUT":
                self._finalize_job(
                    job,
                    "cancelled",
                    "CAPABILITY_CANCELLED",
                    self._result_payload(capability_id, chain, projection),
                    task_id,
                    "cancelled",
                )
            else:
                self._finalize_job(
                    job,
                    "failed",
                    exc.code,
                    self._result_payload(capability_id, chain, projection),
                    task_id,
                    "failed",
                )
            self._audit(action="invoke", capability_id=capability_id, status=job["status"], job_id=job_id, error_code=job["error_code"])
        except Exception as exc:
            self._finalize_job(
                job,
                "failed",
                "CAPABILITY_INVOKE_FAILED",
                self._result_payload(capability_id, chain, projection, message=redact_text(exc)),
                task_id,
                "failed",
            )
            self._audit(action="invoke", capability_id=capability_id, status="failed", job_id=job_id)
        with self._lock:
            job["updated_at"] = _now()
            job["thread_stuck"] = False

    def _execute_projection(self, projection: dict[str, Any] | None, flag: threading.Event) -> dict[str, Any]:
        if not projection:
            raise CapabilityError("CAPABILITY_NOT_FOUND", "missing projection")
        if flag.is_set():
            raise CapabilityError("CAPABILITY_CANCELLED", "cancelled")
        if projection["kind"] == "cli":
            return self._result_payload(
                projection["capability_id"],
                [],
                projection,
                tool_metadata=projection.get("tool_metadata"),
            )
        if projection["kind"] == "skill":
            skill_md = Path(str(projection.get("origin") or "")) / "SKILL.md"
            if not skill_md.is_file():
                raise CapabilityError("CAPABILITY_INVOKE_FAILED", "skill SKILL.md missing")
            text = skill_md.read_text(encoding="utf-8", errors="replace")[:4000]
            return self._result_payload(
                projection["capability_id"],
                [],
                projection,
                text=text,
            )
        if projection["kind"] == "mcp":
            spec = (self._mcp_lister() or {}).get(projection["name"])
            if isinstance(spec, dict) and spec.get("fail"):
                raise CapabilityError("CAPABILITY_INVOKE_FAILED", "mcp provider failed")
            if self._mcp_invoker is None:
                raise CapabilityError("CAPABILITY_INVOKE_FAILED", "mcp adapter unavailable")
            box: dict[str, Any] = {}

            def _call() -> None:
                try:
                    box["value"] = self._mcp_invoker(projection, spec, flag)
                except Exception as exc:  # noqa: BLE001 - surface to job
                    box["error"] = exc

            worker = threading.Thread(target=_call, daemon=True)
            worker.start()
            deadline = time.monotonic() + max(0.05, float(self._invoke_timeout_s))
            while worker.is_alive() and time.monotonic() < deadline:
                if flag.is_set():
                    raise CapabilityError("CAPABILITY_CANCELLED", "cancelled")
                worker.join(0.02)
            if worker.is_alive():
                raise CapabilityError("CAPABILITY_TIMEOUT", "mcp adapter timed out")
            if "error" in box:
                raise box["error"]
            if flag.is_set():
                raise CapabilityError("CAPABILITY_CANCELLED", "cancelled")
            result = box.get("value")
            text = result if isinstance(result, str) else redact_text(result)
            return self._result_payload(projection["capability_id"], [], projection, text=text)
        raise CapabilityError("CAPABILITY_UNAVAILABLE", "unsupported capability kind")

    def cancel(self, job_id: str, *, session_id: str | None = None) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            raise CapabilityError("CAPABILITY_JOB_NOT_FOUND", "unknown job_id")
        if session_id and job.get("session_id") and job["session_id"] != session_id:
            raise CapabilityError("CAPABILITY_JOB_NOT_FOUND", "job is not bound to this session")
        flag = self._cancel_flags.get(job_id)
        if flag is not None:
            flag.set()
        with self._lock:
            if job["status"] in {"completed", "failed", "cancelled"}:
                self._audit(action="cancel", capability_id=job["capability_id"], job_id=job_id, status=job["status"])
                return dict(job)
            job["status"] = "cancelled"
            job["error_code"] = "CAPABILITY_CANCELLED"
            job["updated_at"] = _now()
        self._finish_tool(job.get("task_id"), "cancelled")
        self._audit(action="cancel", capability_id=job["capability_id"], job_id=job_id, status="cancelled")
        return dict(job)

    def _finalize_job(
        self,
        job: dict[str, Any],
        status: str,
        error_code: str | None,
        payload: dict[str, Any] | None,
        task_id: str | None,
        tool_status: str,
    ) -> None:
        with self._lock:
            if job.get("status") in {"cancelled", "failed", "completed"}:
                return
            job["status"] = status
            job["error_code"] = error_code
            if payload is not None:
                job["payload"] = payload
        self._finish_tool(task_id, tool_status)

    def _start_tool(self, capability_id: str, session_id: str | None) -> str | None:
        if self._execution is None or not session_id:
            return None
        record = self._execution.start(
            session_id=session_id,
            name=capability_id,
            kind="tool",
            origin="capability",
            arguments={"capability_id": capability_id},
        )
        return record.task_id

    def _finish_tool(self, task_id: str | None, status: str) -> None:
        if self._execution is None or not task_id:
            return
        try:
            self._execution.finish(task_id, status)
        except Exception:
            return

    def _result_payload(
        self,
        capability_id: str,
        chain: list[dict[str, Any]],
        projection: dict[str, Any] | None,
        **extra: Any,
    ) -> dict[str, Any]:
        locator = (projection or {}).get("locator") or f"capability:{capability_id}"
        origin = (projection or {}).get("origin") or capability_id
        kind = (projection or {}).get("kind") or capability_id.split(":", 1)[0]
        return {
            "chain": chain,
            "source": {"kind": kind, "locator": locator, "origin": origin},
            "copyable": True,
            "collapsible": True,
            **extra,
        }

    def _review_step(
        self,
        capability_id: str,
        session_id: str | None,
        workspace: str | None,
    ) -> dict[str, Any]:
        step = {
            "step": "review",
            "status": "required",
            "bypass": False,
            "capability_id": capability_id,
        }
        if self._reviews is None:
            step["status"] = "unavailable"
            step["error_code"] = "REVIEW_UNAVAILABLE"
            return step
        step["review_service"] = "bound"
        step["session_id"] = session_id
        root = Path(workspace) if workspace else Path(".")
        try:
            summary, _events = self._reviews.start(
                request_id="cap-" + uuid.uuid4().hex[:10],
                session_id=session_id or "capability",
                workspace=root,
                scope="working_tree",
            )
            step["review_id"] = summary.get("review_id")
            step["status"] = str(summary.get("status") or "started")
        except ReviewError as exc:
            step["status"] = "rejected" if "DENIED" in exc.code or "INVALID" in exc.code else "unavailable"
            step["error_code"] = exc.code
        except Exception as exc:
            step["status"] = "unavailable"
            step["error_code"] = redact_text(exc)
        return step

    def audit(self, capability_id: str | None = None) -> list[dict[str, Any]]:
        rows = list(self._data.get("audit") or [])
        if capability_id:
            rows = [row for row in rows if row.get("capability_id") == capability_id]
        return rows

    def _new_job(
        self,
        capability_id: str,
        session_id: str | None,
        turn_id: str | None,
        status: str,
        error_code: str | None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job = {
            "job_id": uuid.uuid4().hex[:12],
            "capability_id": capability_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "status": status,
            "error_code": error_code,
            "payload": payload,
            "cancellable": True,
            "created_at": _now(),
            "updated_at": _now(),
            "thread_stuck": False,
        }
        self._jobs[job["job_id"]] = job
        return dict(job)
