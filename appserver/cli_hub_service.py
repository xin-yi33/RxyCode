"""PhaseG-B14 CLI-Hub. Software ids are cli:<name> parameters, not registry tools."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import venv
import zipfile
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .settings import redact_text


def venv_scripts(venv: Path) -> Path:
    root = Path(venv)
    if os.name == "nt":
        return Path(str(root) + os.sep + "Scripts")
    return Path(str(root) + os.sep + "bin")


def venv_python(venv: Path) -> Path:
    scripts = venv_scripts(venv)
    if os.name == "nt":
        return Path(str(scripts) + os.sep + "python.exe")
    return Path(str(scripts) + os.sep + "python")


def venv_site_packages(venv: Path) -> Path:
    root = Path(venv)
    if os.name == "nt":
        return Path(str(root) + os.sep + "Lib" + os.sep + "site-packages")
    lib = Path(str(root) + os.sep + "lib")
    if lib.is_dir():
        for child in sorted(lib.iterdir()):
            if child.name.startswith("python"):
                return Path(str(child) + os.sep + "site-packages")
    ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return Path(str(root) + os.sep + "lib" + os.sep + ver + os.sep + "site-packages")

CACHE_TTL_S = 3600
SOURCES = ("builtin", "cli-hub", "self-generated")
GENERATE_LADDER = ("generate", "refine", "handwritten-wrapper")
AGENT_TOOLS = ("cli_list", "cli_run")
INSTALL_GUIDE = "install python3-venv / python3-pip, then retry cli/install"


class CliHubError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def software_id(name: str) -> str:
    raw = (name or "").strip()
    if raw.startswith("cli:"):
        raw = raw[4:]
    if not raw or "/" in raw or "\\" in raw or raw in AGENT_TOOLS:
        raise CliHubError("CLI_NAME_INVALID", "invalid CLI software name")
    return f"cli:{raw}"


def _next_ladder_step(stage: str) -> str | None:
    if stage not in GENERATE_LADDER:
        return None
    index = GENERATE_LADDER.index(stage)
    if index + 1 >= len(GENERATE_LADDER):
        return None
    return GENERATE_LADDER[index + 1]


class CliHubService:
    def __init__(self, root: Path | None = None, registry: dict[str, Any] | None = None) -> None:
        self.root = root or Path.home() / ".cli-hub"
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.root / "registry_cache.json"
        self.installed_path = self.root / "installed.json"
        self.failures_path = self.root / "generate_failures.json"
        self._fixture_registry = registry
        self.registry_url = os.environ.get("RXYCODE_CLI_HUB_URL", "")
        self._procs: dict[str, subprocess.Popen[str]] = {}

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")

    def _lookup_spec(self, sid: str, registry: dict[str, Any] | None = None) -> dict[str, Any] | None:
        software = registry if registry is not None else (self.fetch_registry().get("software") or {})
        spec = software.get(sid[4:]) or software.get(sid)
        return spec if isinstance(spec, dict) else None

    def fetch_registry(self) -> dict[str, Any]:
        cached = self._read_json(self.cache_path)
        if self._fixture_registry is not None:
            data = {"fetched_at": time.time(), "software": self._fixture_registry, "from_cache": False}
            self._write_json(self.cache_path, data)
            return data
        fetched_at = float(cached.get("fetched_at") or 0)
        fresh = bool(cached) and time.time() - fetched_at < CACHE_TTL_S
        if fresh:
            cached["from_cache"] = True
            return cached
        if self.registry_url:
            try:
                with urlopen(self.registry_url, timeout=3) as resp:
                    remote = json.loads(resp.read().decode("utf-8"))
                software = remote.get("software") if isinstance(remote, dict) else {}
                data = {"fetched_at": time.time(), "software": software or {}, "from_cache": False}
                self._write_json(self.cache_path, data)
                return data
            except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
                if cached:
                    cached["from_cache"] = True
                    cached["stale"] = True
                    return cached
                raise CliHubError("CLI_REGISTRY_UNAVAILABLE", "registry fetch failed and no cache")
        if cached:
            cached["from_cache"] = True
            cached["stale"] = True
            return cached
        empty = {"fetched_at": time.time(), "software": {}, "from_cache": False}
        self._write_json(self.cache_path, empty)
        return empty

    def decide(self, name: str, *, has_source: bool = False, has_sdk: bool = False) -> dict[str, Any]:
        """C-C: registry-first hybrid decision (§5.3)."""
        sid = software_id(name)
        if self._lookup_spec(sid) is not None:
            return {
                "id": sid,
                "priority": 1,
                "action": "cli-hub-install",
                "source": "cli-hub",
                "reason": "registry-first: consume existing CLI-Hub software",
            }
        if has_source:
            return {
                "id": sid,
                "priority": 2,
                "action": "generate",
                "source": "self-generated",
                "reason": "not in registry; source available for HARNESS generate",
            }
        if has_sdk:
            return {
                "id": sid,
                "priority": 3,
                "action": "mcp-bridge",
                "source": "self-generated",
                "reason": "not in registry; official SDK/API available",
            }
        return {
            "id": sid,
            "priority": 4,
            "action": "reject",
            "code": "CLI_NOT_ADOPTED",
            "source": None,
            "reason": "closed source without SDK; computer-use does not fill the gap",
        }

    def record_generate_failure(
        self,
        name: str,
        stage: str,
        reason: str,
        next_step: str | None = None,
    ) -> dict[str, Any]:
        """C-E: persist generate → refine → handwritten-wrapper failures."""
        if stage not in GENERATE_LADDER:
            raise CliHubError("CLI_LADDER_INVALID", f"stage must be one of {GENERATE_LADDER}")
        sid = software_id(name)
        record = {
            "id": sid,
            "stage": stage,
            "reason": reason,
            "next_step": next_step if next_step is not None else _next_ladder_step(stage),
            "recorded_at": time.time(),
        }
        store = self._read_json(self.failures_path)
        rows = list(store.get("failures") or [])
        rows.append(record)
        store["failures"] = rows
        self._write_json(self.failures_path, store)
        return record

    def list_generate_failures(self, name: str | None = None) -> dict[str, Any]:
        rows = list(self._read_json(self.failures_path).get("failures") or [])
        if name:
            sid = software_id(name)
            rows = [row for row in rows if row.get("id") == sid]
        return {"failures": rows, "ladder": list(GENERATE_LADDER)}

    def list_software(self) -> dict[str, Any]:
        registry = self.fetch_registry()
        installed = self._read_json(self.installed_path)
        rows = []
        for name, spec in (registry.get("software") or {}).items():
            sid = software_id(name)
            rec = installed.get(sid) or {}
            source = (spec or {}).get("source", "cli-hub")
            if source not in SOURCES:
                source = "cli-hub"
            rows.append(
                {
                    "id": sid,
                    "name": sid[4:],
                    "source": source,
                    "installed": bool(rec.get("installed")),
                    "running": bool(rec.get("running")),
                    "venv": rec.get("venv"),
                    "schema": (spec or {}).get("schema") or {"name": sid},
                }
            )
        return {"software": rows, "from_cache": bool(registry.get("from_cache")), "agent_tools": list(AGENT_TOOLS)}

    def _ensure_venv(self, venv_dir: Path, sid: str) -> Path:
        py = venv_python(venv_dir)
        try:
            if not py.exists():
                venv.create(venv_dir, with_pip=True, symlinks=(os.name != "nt"))
        except Exception as exc:
            raise CliHubError(
                "CLI_VENV_FAILED",
                f"venv create failed for {sid}; {INSTALL_GUIDE} ({redact_text(exc)})",
            ) from exc
        py = venv_python(venv_dir)
        if not py.exists():
            raise CliHubError("CLI_VENV_FAILED", f"venv python missing at {py}; {INSTALL_GUIDE}")
        if not self._venv_has_pip(py):
            boot = self._run_venv(
                [str(py), "-m", "ensurepip", "--upgrade"],
                timeout_s=120,
            )
            if boot.returncode != 0 or not self._venv_has_pip(py):
                raise CliHubError(
                    "CLI_VENV_FAILED",
                    f"isolated pip missing for {sid}; {INSTALL_GUIDE}; {redact_text(boot.stderr or boot.stdout or '')}",
                )
        return py

    def _venv_has_pip(self, py: Path) -> bool:
        probe = self._run_venv([str(py), "-m", "pip", "--version"], timeout_s=30)
        return probe.returncode == 0

    def _run_venv(
        self,
        argv: list[str],
        *,
        timeout_s: float,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = self._run_env()
        if extra_env:
            env.update(extra_env)
        try:
            return subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise CliHubError("CLI_TIMEOUT", f"{argv[:3]} timed out; {INSTALL_GUIDE}") from exc

    def _local_requirement(self, path: Path, venv_dir: Path, sid: str) -> Path:
        if path.suffix == ".whl" and path.is_file():
            return path
        if not path.exists():
            raise CliHubError(
                "CLI_INSTALL_UNSPECIFIED",
                f"{sid} has no local fixture package; set install.path to a pyproject/wheel; {INSTALL_GUIDE}",
            )
        return self._write_purelib_wheel(path, venv_dir / "wheels", sid)

    def _write_purelib_wheel(self, src_root: Path, dest_dir: Path, sid: str) -> Path:
        pkg_name = sid[4:].replace("-", "_")
        src_dir = src_root / "src"
        candidates = [src_root / "src" / pkg_name, src_root / pkg_name]
        if src_dir.is_dir():
            candidates.extend(sorted(child for child in src_dir.iterdir() if child.is_dir() and (child / "__init__.py").exists()))
        pkg = next((item for item in candidates if item.is_dir()), None)
        if pkg is None:
            raise CliHubError(
                "CLI_INSTALL_UNSPECIFIED",
                f"{sid} local package dir missing ({pkg_name}); {INSTALL_GUIDE}",
            )
        pkg_name = pkg.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        version = "0.1.0"
        dist = f"{pkg_name}-{version}"
        wheel = dest_dir / f"{dist}-py3-none-any.whl"
        dist_info = f"{dist}.dist-info"
        records: list[str] = []
        with zipfile.ZipFile(wheel, "w") as archive:
            for file in pkg.rglob("*"):
                if file.is_file():
                    arc = f"{pkg_name}/{file.relative_to(pkg).as_posix()}"
                    archive.write(file, arc)
                    records.append(f"{arc},,")
            meta = f"Metadata-Version: 2.1\nName: {pkg_name.replace('_', '-')}\nVersion: {version}\n"
            archive.writestr(f"{dist_info}/METADATA", meta)
            records.append(f"{dist_info}/METADATA,,")
            wheel_meta = "Wheel-Version: 1.0\nGenerator: rxy-cli-hub\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
            archive.writestr(f"{dist_info}/WHEEL", wheel_meta)
            records.append(f"{dist_info}/WHEEL,,")
            archive.writestr(f"{dist_info}/RECORD", "\n".join(records) + "\n")
        return wheel.resolve()

    def _pip_install(self, venv_dir: Path, spec: dict[str, Any], sid: str) -> dict[str, Any]:
        install = spec.get("install") if isinstance(spec.get("install"), dict) else {}
        kind = str(install.get("kind") or "local")
        py = venv_python(venv_dir)
        if kind == "local":
            raw_path = install.get("path")
            if not raw_path:
                raise CliHubError(
                    "CLI_INSTALL_UNSPECIFIED",
                    f"{sid} has no local fixture package; set install.path to a pyproject/wheel; {INSTALL_GUIDE}",
                )
            requirement = str(self._local_requirement(Path(str(raw_path)), venv_dir, sid).resolve())
            argv = [str(py), "-m", "pip", "install", "--no-deps", "--no-index", requirement]
        elif kind == "pip":
            requirement = str(install.get("spec") or "").strip()
            if not requirement:
                raise CliHubError("CLI_INSTALL_UNSPECIFIED", f"{sid} pip spec missing; {INSTALL_GUIDE}")
            argv = [str(py), "-m", "pip", "install", "--no-deps", requirement]
        else:
            raise CliHubError("CLI_INSTALL_UNSPECIFIED", f"{sid} unknown install kind {kind}; {INSTALL_GUIDE}")
        completed = self._run_venv(argv, timeout_s=180)
        if completed.returncode != 0:
            raise CliHubError(
                "CLI_INSTALL_FAILED",
                f"pip install failed for {sid}; {INSTALL_GUIDE}; {redact_text(completed.stderr or completed.stdout or 'pip error')}",
            )
        return {"pip_argv": argv, "python": str(py), "kind": kind, "requirement": requirement}

    def install(self, name: str, *, source: str = "cli-hub") -> dict[str, Any]:
        if source not in SOURCES:
            raise CliHubError("CLI_SOURCE_INVALID", "unknown source tag")
        sid = software_id(name)
        decision = self.decide(sid)
        if decision["priority"] == 1:
            source = "cli-hub"
        spec = self._lookup_spec(sid)
        if spec is None:
            which_hint = shutil.which(sid[4:])
            raise CliHubError(
                "CLI_NOT_FOUND",
                f"software missing: {sid}; not in CLI-Hub registry"
                + (f" (host which={which_hint})" if which_hint else "")
                + "; install via cli/install after the software is published, or generate (C-C priority 2)",
            )
        installed = self._read_json(self.installed_path)
        existing = installed.get(sid) or {}
        if existing.get("installed"):
            raise CliHubError("CLI_NAME_FROZEN", f"{sid} already installed; same-name overwrite forbidden")
        venv_dir = self.root / "venv" / sid[4:]
        py = self._ensure_venv(venv_dir, sid)
        pip_info = self._pip_install(venv_dir, spec, sid)
        module = str(spec.get("module") or sid[4:].replace("-", "_"))
        installed[sid] = {
            "installed": True,
            "venv": str(venv_dir),
            "source": source,
            "python": str(py),
            "module": module,
            "command": spec.get("command"),
            "pip": pip_info,
            "running": False,
        }
        self._write_json(self.installed_path, installed)
        return {
            "ok": True,
            "id": sid,
            "source": source,
            "venv": str(venv_dir),
            "isolated": True,
            "python": str(py),
            "module": module,
            "pip": pip_info,
            "decision": decision,
        }

    def uninstall(self, name: str) -> dict[str, Any]:
        sid = software_id(name)
        rec = self._read_json(self.installed_path).get(sid)
        if rec and rec.get("running"):
            self.stop(sid)
        installed = self._read_json(self.installed_path)
        rec = installed.pop(sid, None)
        if rec and rec.get("venv"):
            shutil.rmtree(rec["venv"], ignore_errors=True)
        self._write_json(self.installed_path, installed)
        return {"ok": True, "id": sid, "removed": rec is not None}

    def _installed(self, name: str) -> tuple[str, dict[str, Any]]:
        sid = software_id(name)
        rec = self._read_json(self.installed_path).get(sid)
        if not rec or not rec.get("installed"):
            raise CliHubError(
                "CLI_NOT_INSTALLED",
                f"{sid} is not installed; {INSTALL_GUIDE}",
            )
        python = str(rec.get("python") or "")
        if not python or not Path(python).exists():
            raise CliHubError("CLI_VENV_FAILED", f"isolated python missing for {sid}; {INSTALL_GUIDE}")
        if Path(python).resolve() == Path(sys.executable).resolve():
            raise CliHubError("CLI_ISOLATION_BROKEN", f"CLI ran in the host interpreter; {INSTALL_GUIDE}")
        return sid, rec

    def _argv(self, rec: dict[str, Any], extra: list[str] | None) -> list[str]:
        python = str(rec["python"])
        command = rec.get("command")
        if command:
            scripts = venv_scripts(Path(rec["venv"]))
            located = shutil.which(str(command), path=str(scripts))
            if located:
                return [located, *(extra or [])]
        module = str(rec.get("module") or "cli_hub_demo")
        return [python, "-m", module, *(extra or [])]

    def _run_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONNOUSERSITE"] = "1"
        env.pop("PYTHONPATH", None)
        return env

    def launch(self, name: str, args: list[str] | None = None, *, timeout_s: float = 15.0) -> dict[str, Any]:
        sid, rec = self._installed(name)
        argv = self._argv(rec, args)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
                env=self._run_env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise CliHubError("CLI_TIMEOUT", f"{sid} timed out after {timeout_s}s; {INSTALL_GUIDE}") from exc
        if completed.returncode != 0:
            raise CliHubError("CLI_LAUNCH_FAILED", redact_text(completed.stderr or "launch failed"))
        return {
            "ok": True,
            "id": sid,
            "argv": argv,
            "venv": rec.get("venv"),
            "source": rec.get("source"),
            "exit_code": completed.returncode,
            "stdout": (completed.stdout or "")[:2000],
        }

    def start(self, name: str, args: list[str] | None = None) -> dict[str, Any]:
        sid, rec = self._installed(name)
        existing = self._procs.get(sid)
        if existing is not None and existing.poll() is None:
            raise CliHubError("CLI_ALREADY_RUNNING", f"{sid} already running pid={existing.pid}")
        if rec.get("running") and rec.get("pid"):
            raise CliHubError("CLI_ALREADY_RUNNING", f"{sid} already running pid={rec.get('pid')}")
        extra = ["--serve", *(args or [])]
        argv = self._argv(rec, extra)
        kwargs: dict[str, Any] = {
            "env": self._run_env(),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(argv, **kwargs)
        time.sleep(0.15)
        if proc.poll() is not None:
            err = ""
            if proc.stderr:
                err = proc.stderr.read() or ""
            raise CliHubError("CLI_START_FAILED", redact_text(err or f"{sid} exited immediately"))
        self._procs[sid] = proc
        installed = self._read_json(self.installed_path)
        installed[sid]["running"] = True
        installed[sid]["pid"] = proc.pid
        self._write_json(self.installed_path, installed)
        return {"ok": True, "id": sid, "pid": proc.pid, "status": "running", "argv": argv}

    def stop(self, name: str) -> dict[str, Any]:
        sid = software_id(name)
        proc = self._procs.pop(sid, None)
        if proc is not None and proc.poll() is None:
            self._terminate(proc)
        installed = self._read_json(self.installed_path)
        rec = installed.get(sid) or {}
        pid = rec.get("pid")
        if proc is None and pid:
            self._kill_pid(int(pid))
        if rec:
            rec["running"] = False
            rec.pop("pid", None)
            installed[sid] = rec
            self._write_json(self.installed_path, installed)
        return {"ok": True, "id": sid, "status": "stopped", "was_running": bool(pid or proc)}

    def _terminate(self, proc: subprocess.Popen[str]) -> None:
        try:
            if os.name == "nt":
                proc.terminate()
            else:
                os.killpg(proc.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _kill_pid(self, pid: int) -> None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
            else:
                os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            return

    def cli_list(self, query: str | None = None) -> dict[str, Any]:
        """Agent tool: list software ids as parameter values, not registry tools."""
        payload = self.list_software()
        if query:
            needle = query.lower()
            payload["software"] = [
                row
                for row in payload["software"]
                if needle in str(row.get("id", "")).lower() or needle in str(row.get("name", "")).lower()
            ]
        return payload

    def cli_run(self, name: str, args: list[str] | None = None, timeout_s: float = 15.0) -> dict[str, Any]:
        """Agent tool: run one cli:<name> software id."""
        return self.launch(name, args, timeout_s=timeout_s)

    def schema(self, name: str) -> dict[str, Any]:
        sid = software_id(name)
        spec = self._lookup_spec(sid) or {}
        return {"id": sid, "schema": spec.get("schema") or {"name": sid}, "source": spec.get("source", "cli-hub")}

    def agent_tools(self) -> list[Any]:
        """Fixed two-tool agent surface. Software ids stay parameters (N13)."""
        from tools.cli_bridge import bind_agent_tools

        return bind_agent_tools(self)

    def tool_metadata(self) -> dict[str, Any]:
        """Source-tagged metadata for G13 capability panel. Not tools/registry."""
        rows = [
            {
                "id": f"tool:{tool}",
                "name": tool,
                "source": "builtin",
                "kind": "cli-agent-tool",
                "namespace": "cli",
                "installed": True,
            }
            for tool in AGENT_TOOLS
        ]
        for item in self.list_software()["software"]:
            rows.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "source": item["source"],
                    "kind": "cli",
                    "namespace": "cli",
                    "installed": bool(item.get("installed")),
                    "schema": item.get("schema"),
                }
            )
        return {"tools": rows, "agent_tools": list(AGENT_TOOLS), "sources": list(SOURCES)}
