"""Production MCP stdio client using newline-delimited JSON-RPC.

The repository's local ``mcp`` package shadows the official Python SDK, so
this module implements the small client surface RxyCode needs while following
the SDK lifecycle: transport -> initialize -> initialized -> operations ->
disconnect.  The 2025-11-25 stdio transport uses one UTF-8 JSON-RPC message per
line; the legacy LSP-style ``Content-Length`` framing is intentionally rejected.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from jsonschema import ValidationError
from jsonschema.validators import validator_for
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model


logger = logging.getLogger(__name__)

CURRENT_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {
        CURRENT_PROTOCOL_VERSION,
        "2025-06-18",
        "2025-03-26",
        "2024-11-05",
    }
)
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_MESSAGE_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_OUTPUT_CHARS = 30_000
MAX_TOOLS = 1024
MAX_LIST_PAGES = 100
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|passwd|secret|token)"
    r"\s*([:=])\s*([^\s,;]+)"
)
DEFAULT_INHERITED_ENV_VARS = (
    (
        "APPDATA",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "USERNAME",
        "USERPROFILE",
    )
    if sys.platform == "win32"
    else ("HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER")
)


class MCPError(RuntimeError):
    """Base class for protocol, lifecycle, and transport failures."""


class MCPTimeoutError(MCPError):
    """Raised when a JSON-RPC request exceeds its configured deadline."""


class MCPCancelledError(MCPError):
    """Internal signal used to unwind a cancelled async tool adapter."""


@dataclass(frozen=True)
class MCPTool:
    """A validated tool provided by one MCP server."""

    name: str
    remote_name: str
    description: str
    parameters: dict[str, Any]
    output_schema: dict[str, Any] | None
    annotations: dict[str, Any]
    server_name: str


@dataclass
class _PendingResponse:
    event: threading.Event = field(default_factory=threading.Event)
    response: dict[str, Any] | None = None
    error: MCPError | None = None


@dataclass(frozen=True)
class MCPLoadResult:
    """Connected clients and their LangChain tools, plus content-free errors."""

    clients: dict[str, "MCPClient"]
    tools: dict[str, StructuredTool]
    errors: dict[str, str]
    configured_count: int


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value)
    text = "".join(
        char for char in text if char in "\n\r\t" or ord(char) >= 32
    )
    text = _SECRET_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}***",
        text,
    )
    text = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer ***", text
    )
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[MCP output truncated: {len(text) - limit} chars omitted]"


def _qualified_tool_name(server_name: str, remote_name: str) -> str:
    """Return a stable provider-compatible name with collision-resistant trim."""
    raw = f"mcp_{server_name}_{remote_name}"
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_") or "mcp_tool"
    if len(cleaned) <= 64:
        return cleaned
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned[:53]}_{digest}"


def _default_subprocess_environment() -> dict[str, str]:
    """Match the official SDK's conservative inherited-environment allowlist."""
    environment: dict[str, str] = {}
    for key in DEFAULT_INHERITED_ENV_VARS:
        value = os.environ.get(key)
        if value is None or value.startswith("()"):
            continue
        environment[key] = value
    return environment


def _validate_local_refs(value: Any) -> None:
    """Reject network/file JSON references during untrusted schema validation."""
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and not ref.startswith("#"):
            raise MCPError("MCP tool schema contains a non-local $ref")
        for child in value.values():
            _validate_local_refs(child)
    elif isinstance(value, list):
        for child in value:
            _validate_local_refs(child)


def _schema_validator(schema: dict[str, Any]):
    _validate_local_refs(schema)
    try:
        validator_cls = validator_for(schema)
        validator_cls.check_schema(schema)
        return validator_cls(schema)
    except Exception as exc:
        raise MCPError("MCP tool has an invalid inputSchema") from exc


class MCPClient:
    """Thread-safe MCP stdio client with bounded I/O and strict lifecycle."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
        cwd: str | os.PathLike[str] | None = None,
    ):
        self.name = self._validate_server_name(name)
        self.command = self._validate_command(command)
        self.args = self._validate_args(args or [])
        self.env = self._validate_env(env or {})
        try:
            self.timeout = min(3600.0, max(0.05, float(timeout)))
        except (TypeError, ValueError) as exc:
            raise ValueError("MCP timeout must be a positive number") from exc
        self.max_message_bytes = min(
            64 * 1024 * 1024, max(1024, int(max_message_bytes))
        )
        self.max_output_chars = min(
            1_000_000, max(1000, int(max_output_chars))
        )
        self.cwd = self._validate_cwd(cwd)

        self._process: Optional[subprocess.Popen[bytes]] = None
        self._request_id = 0
        self._tools: list[MCPTool] = []
        self._validators: dict[str, Any] = {}
        self._output_validators: dict[str, Any] = {}
        self._write_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._pending: dict[int, _PendingResponse] = {}
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._connected = False
        self._closing = False
        self._tools_changed = False
        self._protocol_version: str | None = None
        self._server_capabilities: dict[str, Any] = {}
        self._last_error_type: str | None = None

    @staticmethod
    def _validate_server_name(name: str) -> str:
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ValueError("MCP server name must contain 1-128 characters")
        if any(char in name for char in ("\x00", "\n", "\r")):
            raise ValueError("MCP server name contains invalid characters")
        return name.strip()

    @staticmethod
    def _validate_command(command: str) -> str:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("MCP command is required")
        if "\x00" in command or len(command) > 32_768:
            raise ValueError("MCP command is invalid")
        return command

    @staticmethod
    def _validate_args(args: list[str]) -> list[str]:
        if not isinstance(args, list) or len(args) > 256:
            raise ValueError("MCP args must be a list with at most 256 entries")
        validated: list[str] = []
        for arg in args:
            if not isinstance(arg, str) or "\x00" in arg or len(arg) > 32_768:
                raise ValueError("MCP args must contain bounded strings")
            validated.append(arg)
        return validated

    @staticmethod
    def _validate_env(env: dict[str, str]) -> dict[str, str]:
        if not isinstance(env, dict) or len(env) > 256:
            raise ValueError("MCP env must be a mapping with at most 256 entries")
        validated: dict[str, str] = {}
        for key, value in env.items():
            if not isinstance(key, str) or not _ENV_NAME_RE.fullmatch(key):
                raise ValueError("MCP env contains an invalid variable name")
            if not isinstance(value, str) or "\x00" in value or len(value) > 131_072:
                raise ValueError("MCP env values must be bounded strings")
            validated[key] = value
        return validated

    @staticmethod
    def _validate_cwd(cwd: str | os.PathLike[str] | None) -> str | None:
        if cwd is None:
            return None
        resolved = Path(cwd).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError("MCP cwd must be an existing directory")
        return str(resolved)

    @property
    def connected(self) -> bool:
        process = self._process
        return bool(
            self._connected
            and process is not None
            and process.poll() is None
        )

    @property
    def tools_changed(self) -> bool:
        return self._tools_changed

    @property
    def protocol_version(self) -> str | None:
        return self._protocol_version

    @property
    def last_error_type(self) -> str | None:
        return self._last_error_type

    def connect(self) -> bool:
        """Start the server and complete MCP initialization and discovery."""
        if self.connected:
            return True
        self.disconnect()
        self._closing = False
        try:
            env = _default_subprocess_environment()
            env.update(self.env)
            popen_kwargs: dict[str, Any] = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "env": env,
                "cwd": self.cwd,
                "bufsize": 0,
                "shell": False,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            executable = shutil.which(self.command) or self.command
            self._process = subprocess.Popen(
                [executable, *self.args],
                **popen_kwargs,
            )
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name=f"mcp-{self.name}-stdout",
                daemon=True,
            )
            self._stderr_thread = threading.Thread(
                target=self._stderr_loop,
                name=f"mcp-{self.name}-stderr",
                daemon=True,
            )
            self._reader_thread.start()
            self._stderr_thread.start()

            response = self._send_request(
                "initialize",
                {
                    "protocolVersion": CURRENT_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "RxyCode", "version": "1.2.2"},
                },
            )
            result = self._result_or_raise(response, "initialize")
            negotiated = result.get("protocolVersion")
            if negotiated not in SUPPORTED_PROTOCOL_VERSIONS:
                raise MCPError("MCP server selected an unsupported protocol version")
            capabilities = result.get("capabilities", {})
            if not isinstance(capabilities, dict):
                raise MCPError("MCP initialize result has invalid capabilities")
            self._protocol_version = str(negotiated)
            self._server_capabilities = capabilities
            self._send_notification("notifications/initialized")
            tools_capability = capabilities.get("tools")
            if tools_capability is not None and not isinstance(
                tools_capability, dict
            ):
                raise MCPError("MCP tools capability is invalid")
            self._tools = (
                self._discover_tools() if tools_capability is not None else []
            )
            self._tools_changed = False
            self._connected = True
            self._last_error_type = None
            logger.info(
                "[MCP:%s] connected with %d tools", self.name, len(self._tools)
            )
            return True
        except Exception as exc:
            self._last_error_type = type(exc).__name__
            logger.warning("[MCP:%s] connection failed: %s", self.name, type(exc).__name__)
            self.disconnect()
            return False

    def disconnect(self) -> None:
        """Stop the subprocess, unblock waiters, and clear negotiated state."""
        self._closing = True
        self._connected = False
        self._fail_pending(MCPError("MCP connection closed"))
        process = self._process
        self._process = None
        if process is not None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except Exception:
                pass
            self._terminate_process_tree(process)
            for stream in (process.stdout, process.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass
        current = threading.current_thread()
        for thread in (self._reader_thread, self._stderr_thread):
            if thread is not None and thread is not current and thread.is_alive():
                thread.join(timeout=1.0)
        self._reader_thread = None
        self._stderr_thread = None
        self._tools.clear()
        self._validators.clear()
        self._output_validators.clear()
        self._protocol_version = None
        self._server_capabilities = {}
        self._tools_changed = False

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            import psutil

            root = psutil.Process(process.pid)
            children = root.children(recursive=True)
            for child in reversed(children):
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            try:
                root.terminate()
            except psutil.Error:
                pass
            _, alive = psutil.wait_procs([*children, root], timeout=2.0)
            for item in alive:
                try:
                    item.kill()
                except psutil.Error:
                    pass
            psutil.wait_procs(alive, timeout=1.0)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except Exception:
                    pass

    def get_tools(self) -> list[MCPTool]:
        return list(self._tools)

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Validate and invoke a discovered tool, returning bounded text."""
        if not self.connected:
            return f"[error: MCP server '{self.name}' is disconnected]"
        if tool_name not in self._validators:
            return f"[error: MCP tool '{tool_name}' is not registered]"
        if not isinstance(arguments, dict):
            return "[error: MCP tool arguments must be an object]"
        try:
            self._validators[tool_name].validate(arguments)
        except ValidationError as exc:
            path = "$." + ".".join(str(part) for part in exc.absolute_path)
            if not exc.absolute_path:
                path = "$"
            return (
                "[error: MCP arguments failed schema validation at "
                f"{path} ({exc.validator})]"
            )
        try:
            response = self._send_request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                cancel_event=cancel_event,
            )
            result = self._result_or_raise(response, "tools/call")
            output_validator = self._output_validators.get(tool_name)
            if output_validator is not None:
                if "structuredContent" not in result:
                    raise MCPError(
                        "MCP tool omitted required structuredContent"
                    )
                try:
                    output_validator.validate(result["structuredContent"])
                except ValidationError as exc:
                    raise MCPError(
                        "MCP tool result failed outputSchema validation"
                    ) from exc
            rendered = self._render_tool_result(result)
            if result.get("isError") is True:
                return f"[error: MCP tool reported failure: {rendered}]"
            return rendered
        except Exception as exc:
            self._last_error_type = type(exc).__name__
            return f"[error: MCP {type(exc).__name__}]"

    def list_resources(self) -> list[dict[str, Any]]:
        try:
            result = self._result_or_raise(
                self._send_request("resources/list", {}), "resources/list"
            )
            resources = result.get("resources", [])
            return resources if isinstance(resources, list) else []
        except Exception:
            return []

    def read_resource(self, uri: str) -> str:
        try:
            result = self._result_or_raise(
                self._send_request("resources/read", {"uri": uri}),
                "resources/read",
            )
            parts: list[str] = []
            for content in result.get("contents", []):
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    parts.append(content["text"])
            return _bounded_text("\n".join(parts), self.max_output_chars)
        except Exception as exc:
            return f"[error: MCP {type(exc).__name__}]"

    def _discover_tools(self) -> list[MCPTool]:
        tools: list[MCPTool] = []
        validators: dict[str, Any] = {}
        output_validators: dict[str, Any] = {}
        remote_names: set[str] = set()
        qualified_names: set[str] = set()
        cursor: str | None = None
        for _page in range(MAX_LIST_PAGES):
            params = {"cursor": cursor} if cursor else {}
            result = self._result_or_raise(
                self._send_request("tools/list", params), "tools/list"
            )
            page_tools = result.get("tools", [])
            if not isinstance(page_tools, list):
                raise MCPError("MCP tools/list returned a non-list tools field")
            for raw in page_tools:
                if not isinstance(raw, dict):
                    raise MCPError("MCP tools/list returned an invalid tool")
                remote_name = raw.get("name")
                if not isinstance(remote_name, str) or not _TOOL_NAME_RE.fullmatch(
                    remote_name
                ):
                    raise MCPError("MCP server returned an invalid tool name")
                if remote_name in remote_names:
                    raise MCPError("MCP server returned duplicate tool names")
                schema = raw.get("inputSchema")
                if not isinstance(schema, dict):
                    raise MCPError("MCP tool inputSchema must be an object")
                validator = _schema_validator(schema)
                output_schema = raw.get("outputSchema")
                if output_schema is not None and not isinstance(
                    output_schema, dict
                ):
                    raise MCPError("MCP tool outputSchema must be an object")
                output_validator = (
                    _schema_validator(output_schema)
                    if output_schema is not None
                    else None
                )
                qualified = _qualified_tool_name(self.name, remote_name)
                if qualified in qualified_names:
                    digest = hashlib.sha256(remote_name.encode("utf-8")).hexdigest()[:8]
                    qualified = f"{qualified[:55]}_{digest}"
                description = raw.get("description", "")
                if not isinstance(description, str):
                    description = ""
                description = _bounded_text(description, 4000)
                annotations = raw.get("annotations", {})
                if not isinstance(annotations, dict):
                    raise MCPError("MCP tool annotations must be an object")
                tools.append(
                    MCPTool(
                        name=qualified,
                        remote_name=remote_name,
                        description=description,
                        parameters=schema,
                        output_schema=output_schema,
                        annotations=annotations,
                        server_name=self.name,
                    )
                )
                validators[remote_name] = validator
                if output_validator is not None:
                    output_validators[remote_name] = output_validator
                remote_names.add(remote_name)
                qualified_names.add(qualified)
                if len(tools) > MAX_TOOLS:
                    raise MCPError("MCP server exposed too many tools")
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                self._validators = validators
                self._output_validators = output_validators
                return tools
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                raise MCPError("MCP tools/list returned an invalid cursor")
            cursor = next_cursor
        raise MCPError("MCP tools/list exceeded the pagination limit")

    def _send_request(
        self,
        method: str,
        params: Any,
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        process = self._process
        if process is None or process.poll() is not None:
            raise MCPError("MCP server is not running")
        with self._state_lock:
            self._request_id += 1
            request_id = self._request_id
            pending = _PendingResponse()
            self._pending[request_id] = pending
        try:
            self._write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
        except Exception:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise
        deadline = time.monotonic() + self.timeout
        while not pending.event.is_set():
            if cancel_event is not None and cancel_event.is_set():
                with self._state_lock:
                    self._pending.pop(request_id, None)
                self._send_notification(
                    "notifications/cancelled",
                    {"requestId": request_id, "reason": "client cancelled"},
                    suppress_errors=True,
                )
                raise MCPCancelledError("MCP request was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._state_lock:
                    self._pending.pop(request_id, None)
                self._send_notification(
                    "notifications/cancelled",
                    {"requestId": request_id, "reason": "client timeout"},
                    suppress_errors=True,
                )
                raise MCPTimeoutError(
                    f"MCP request timed out after {self.timeout:g}s"
                )
            pending.event.wait(min(0.05, remaining))
        if pending.error is not None:
            raise pending.error
        if pending.response is None:
            raise MCPError("MCP request completed without a response")
        return pending.response

    def _send_notification(
        self,
        method: str,
        params: Any | None = None,
        *,
        suppress_errors: bool = False,
    ) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        try:
            self._write_message(message)
        except Exception:
            if not suppress_errors:
                raise

    def _write_message(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise MCPError("MCP server stdin is unavailable")
        try:
            encoded = (
                json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise MCPError("MCP request is not JSON serializable") from exc
        if len(encoded) > self.max_message_bytes:
            raise MCPError("MCP request exceeds the message-size limit")
        with self._write_lock:
            try:
                process.stdin.write(encoded)
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._mark_disconnected(MCPError("MCP server pipe closed"))
                raise MCPError("MCP server pipe closed") from exc

    def _reader_loop(self) -> None:
        process = self._process
        stream = process.stdout if process is not None else None
        if stream is None:
            self._mark_disconnected(MCPError("MCP server stdout is unavailable"))
            return
        try:
            while not self._closing:
                line = stream.readline(self.max_message_bytes + 1)
                if not line:
                    break
                if len(line) > self.max_message_bytes or not line.endswith(b"\n"):
                    raise MCPError("MCP server message exceeds the size limit")
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise MCPError("MCP server emitted invalid JSON-RPC") from exc
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise MCPError("MCP server emitted an invalid JSON-RPC message")
                self._dispatch_message(message)
        except Exception as exc:
            self._last_error_type = type(exc).__name__
            self._mark_disconnected(
                exc if isinstance(exc, MCPError) else MCPError("MCP reader failed")
            )
        finally:
            if not self._closing:
                self._mark_disconnected(MCPError("MCP server disconnected"))

    def _dispatch_message(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = message.get("method")
        if request_id is not None and method is None:
            if not isinstance(request_id, int):
                raise MCPError("MCP response has an invalid id")
            with self._state_lock:
                pending = self._pending.pop(request_id, None)
            if pending is not None:
                pending.response = message
                pending.event.set()
            return
        if isinstance(method, str) and request_id is None:
            if method == "notifications/tools/list_changed":
                self._tools_changed = True
            return
        if isinstance(method, str) and request_id is not None:
            if method == "ping":
                response = {"jsonrpc": "2.0", "id": request_id, "result": {}}
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "Method not supported"},
                }
            self._write_message(response)
            return
        raise MCPError("MCP server emitted an unrecognized JSON-RPC message")

    def _stderr_loop(self) -> None:
        process = self._process
        stream = process.stderr if process is not None else None
        if stream is None:
            return
        logged = 0
        try:
            while not self._closing:
                line = stream.readline(4097)
                if not line:
                    break
                if logged >= 64 * 1024:
                    continue
                rendered = _bounded_text(
                    line.decode("utf-8", errors="replace").strip(), 4096
                )
                logged += len(line)
                if rendered:
                    # stderr is a logging channel in MCP, not an error signal.
                    logger.info("[MCP:%s] stderr: %s", self.name, rendered)
        except Exception:
            return

    def _mark_disconnected(self, error: MCPError) -> None:
        self._connected = False
        self._fail_pending(error)

    def _fail_pending(self, error: MCPError) -> None:
        with self._state_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            waiter.error = error
            waiter.event.set()

    @staticmethod
    def _result_or_raise(
        response: dict[str, Any], operation: str
    ) -> dict[str, Any]:
        error = response.get("error")
        if error is not None:
            code = error.get("code") if isinstance(error, dict) else None
            raise MCPError(f"MCP {operation} returned JSON-RPC error {code}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise MCPError(f"MCP {operation} returned an invalid result")
        return result

    def _render_tool_result(self, result: dict[str, Any]) -> str:
        if "isError" in result and not isinstance(result["isError"], bool):
            raise MCPError("MCP tool result has an invalid isError field")
        parts: list[str] = []
        content = result.get("content", [])
        if not isinstance(content, list):
            raise MCPError("MCP tool result content must be a list")
        for item in content:
            if not isinstance(item, dict):
                continue
            content_type = item.get("type")
            if content_type == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif content_type == "image":
                parts.append(f"[image: {item.get('mimeType', 'unknown')}]")
            elif content_type == "audio":
                parts.append(f"[audio: {item.get('mimeType', 'unknown')}]")
            elif content_type == "resource_link":
                parts.append(f"[resource: {item.get('uri', '')}]")
            elif content_type == "resource":
                resource = item.get("resource")
                if isinstance(resource, dict) and isinstance(resource.get("text"), str):
                    parts.append(resource["text"])
                elif isinstance(resource, dict):
                    parts.append(f"[resource: {resource.get('uri', '')}]")
        structured = result.get("structuredContent")
        if structured is not None:
            try:
                parts.append(json.dumps(structured, ensure_ascii=False, sort_keys=True))
            except (TypeError, ValueError):
                raise MCPError("MCP structuredContent is not JSON serializable")
        if not parts:
            parts.append("[MCP tool completed with no content]")
        return _bounded_text("\n".join(parts), self.max_output_chars)


def _python_type(schema: dict[str, Any], model_name: str) -> Any:
    enum = schema.get("enum")
    if (
        isinstance(enum, list)
        and enum
        and all(
            item is None or isinstance(item, (str, int, float, bool))
            for item in enum
        )
    ):
        from typing import Literal

        return Literal[tuple(enum)]  # type: ignore[valid-type]
    candidates = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(candidates, list) and candidates:
        options = tuple(
            _python_type(item, f"{model_name}Option{index}")
            for index, item in enumerate(candidates)
            if isinstance(item, dict)
        )
        return Union[options] if options else Any
    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        options = tuple(
            type(None) if item == "null" else _python_type({**schema, "type": item}, model_name)
            for item in raw_type
        )
        return Union[options]
    if raw_type == "string":
        return str
    if raw_type == "integer":
        return int
    if raw_type == "number":
        return float
    if raw_type == "boolean":
        return bool
    if raw_type == "array":
        items = schema.get("items")
        return list[_python_type(items, f"{model_name}Item")] if isinstance(items, dict) else list[Any]
    if raw_type == "object":
        properties = schema.get("properties")
        if isinstance(properties, dict) and properties:
            return _build_args_schema(schema, model_name=model_name)
        return dict[str, Any]
    return Any


def _build_args_schema(
    schema: dict[str, Any], *, model_name: str = "MCPArgs"
) -> type[BaseModel]:
    """Build the LLM-facing Pydantic shape; wire validation remains JSON Schema."""
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    required = set(schema.get("required", []))
    fields: dict[str, tuple[Any, Any]] = {}
    for property_name, property_schema in properties.items():
        if not isinstance(property_name, str) or not isinstance(property_schema, dict):
            continue
        annotation = _python_type(
            property_schema,
            f"{model_name}{re.sub(r'[^A-Za-z0-9]', '', property_name).title()}",
        )
        description = property_schema.get("description", "")
        if property_name in required:
            default: Any = Field(description=str(description)[:1000])
        else:
            annotation = Optional[annotation]
            default = Field(
                default=property_schema.get("default"),
                description=str(description)[:1000],
            )
        fields[property_name] = (annotation, default)
    extra = "forbid" if schema.get("additionalProperties") is False else "allow"
    return create_model(
        model_name[:100] or "MCPArgs",
        __config__=ConfigDict(extra=extra),
        **fields,
    )


def _strip_adapter_defaults(
    arguments: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any]:
    """Remove Pydantic-injected ``None`` for optional, non-null MCP fields.

    ``StructuredTool`` materializes absent optional model fields as ``None``.
    Sending those values would change an omitted JSON property into an invalid
    explicit null. Direct ``MCPClient.call_tool`` calls do not use this adapter
    and therefore still reject an explicitly supplied invalid null.
    """
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return dict(arguments)
    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        property_schema = properties.get(key)
        if value is None and isinstance(property_schema, dict):
            raw_type = property_schema.get("type")
            permits_null = raw_type == "null" or (
                isinstance(raw_type, list) and "null" in raw_type
            )
            has_null_branch = any(
                isinstance(item, dict) and item.get("type") == "null"
                for keyword in ("anyOf", "oneOf")
                for item in (
                    property_schema.get(keyword, [])
                    if isinstance(property_schema.get(keyword), list)
                    else []
                )
            )
            if (
                "default" not in property_schema
                and not permits_null
                and not has_null_branch
            ):
                continue
        cleaned[key] = value
    return cleaned


def _normalize_server_config(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("MCP server config must be an object")
    if raw.get("enabled", True) is False:
        return {"disabled": True}
    server_type = raw.get("type", "stdio")
    if server_type != "stdio":
        raise ValueError("Only MCP stdio servers are supported")
    env_raw = raw.get("env", {})
    if isinstance(env_raw, list):
        converted: dict[str, str] = {}
        for item in env_raw:
            if not isinstance(item, str) or "=" not in item:
                raise ValueError("MCP env list entries must be KEY=VALUE strings")
            key, value = item.split("=", 1)
            converted[key] = value
        env_raw = converted
    return {
        "command": raw.get("command", ""),
        "args": raw.get("args", []),
        "env": env_raw,
        "timeout": raw.get("timeout", DEFAULT_TIMEOUT_SECONDS),
        "max_message_bytes": raw.get(
            "max_message_bytes", DEFAULT_MAX_MESSAGE_BYTES
        ),
        "max_output_chars": raw.get("max_output_chars", DEFAULT_MAX_OUTPUT_CHARS),
        "cwd": raw.get("cwd"),
    }


def load_mcp_servers(config: dict[str, Any]) -> MCPLoadResult:
    """Connect configured stdio servers and expose lifecycle-owned tools."""
    if not isinstance(config, dict):
        return MCPLoadResult({}, {}, {"config": "ValueError"}, 0)
    clients: dict[str, MCPClient] = {}
    tools: dict[str, StructuredTool] = {}
    errors: dict[str, str] = {}
    for server_name, raw_config in config.items():
        client: MCPClient | None = None
        try:
            normalized = _normalize_server_config(raw_config)
            if normalized.get("disabled"):
                continue
            client = MCPClient(server_name, **normalized)
            if not client.connect():
                errors[str(server_name)] = client.last_error_type or "MCPError"
                continue
            server_tools: dict[str, StructuredTool] = {}
            for discovered in client.get_tools():
                if discovered.name in tools or discovered.name in server_tools:
                    raise MCPError("MCP qualified tool name collision")

                def sync_call(
                    _client: MCPClient = client,
                    _remote_name: str = discovered.remote_name,
                    _schema: dict[str, Any] = discovered.parameters,
                    **kwargs: Any,
                ) -> str:
                    return _client.call_tool(
                        _remote_name, _strip_adapter_defaults(kwargs, _schema)
                    )

                async def async_call(
                    _client: MCPClient = client,
                    _remote_name: str = discovered.remote_name,
                    _schema: dict[str, Any] = discovered.parameters,
                    **kwargs: Any,
                ) -> str:
                    cancel_event = threading.Event()
                    operation = asyncio.create_task(
                        asyncio.to_thread(
                            _client.call_tool,
                            _remote_name,
                            _strip_adapter_defaults(kwargs, _schema),
                            cancel_event=cancel_event,
                        )
                    )
                    try:
                        return await asyncio.shield(operation)
                    except asyncio.CancelledError:
                        cancel_event.set()
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(operation), timeout=1.0
                            )
                        except (asyncio.CancelledError, asyncio.TimeoutError):
                            pass
                        raise

                description = discovered.description or (
                    f"MCP tool '{discovered.remote_name}' from server '{server_name}'"
                )
                # MCP annotations are untrusted and can never lower the local
                # default WRITE policy. A positive destructive hint is useful
                # only as a conservative escalation to DANGER.
                mcp_risk = (
                    "danger"
                    if discovered.annotations.get("destructiveHint") is True
                    else "write"
                )
                server_tools[discovered.name] = StructuredTool(
                    name=discovered.name,
                    description=description,
                    func=sync_call,
                    coroutine=async_call,
                    metadata={
                        "source": "mcp",
                        "mcp_risk": mcp_risk,
                    },
                    args_schema=_build_args_schema(
                        discovered.parameters,
                        model_name=f"MCP{discovered.name}Args",
                    ),
                )
            clients[str(server_name)] = client
            tools.update(server_tools)
        except Exception as exc:
            errors[str(server_name)] = type(exc).__name__
            if client is not None:
                client.disconnect()
    return MCPLoadResult(clients, tools, errors, len(config))


def create_mcp_tools(config: dict[str, Any]) -> list[StructuredTool]:
    """Backward-compatible helper; each tool owns a reference to its client."""
    return list(load_mcp_servers(config).tools.values())
