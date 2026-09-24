"""Bind open-computer-use MCP tools onto ToolOrchestrator under ocu names."""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model

from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel, register_tool_risk
from RxyCode.RxyCode1_1_0.mcp.client import (
    MCPClient,
    _build_args_schema,
    _strip_adapter_defaults,
)

from .browser import make_browser_tools
from .launcher import mcp_server_config, resolve_ocu_mcp
from .settings import browser_enabled, is_approved, is_enabled
from .spec import (
    ACTION_TOOLS,
    CU_TOOL_ORDER,
    OCU_SERVER_NAME,
    OCU_TOOLS,
    TOOL_DESCRIPTIONS,
    TOOL_RISK,
)

from RxyCode.RxyCode1_1_0.config.settings import get_data_dir

logger = logging.getLogger(__name__)

_cu_local = threading.Lock()

_OTHER_WINDOW = (
    "[error: 另一个窗口正在执行 Computer Use。这次调用结束后即可再试。]"
    "空闲的窗口不会占住它。"
)


@contextmanager
def _cu_call_lock() -> Iterator[bool]:
    """Lock the desktop only while one Computer Use tool is running.

    废弃代码（2026-09-22）：窗口一绑定就 _hold_cu_desktop()，句柄一直留到进程退出。
    另一扇窗口即使没在调用，也会一直收到「正在被另一个窗口使用」。
    """
    if not _cu_local.acquire(blocking=False):
        yield False
        return
    handle = None
    held = False
    try:
        path = get_data_dir() / "desktop" / "computer-use.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() < 1:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        held = True
        yield True
    except OSError:
        yield False
    finally:
        if handle is not None:
            if held:
                try:
                    if os.name == "nt":
                        import msvcrt

                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()
        _cu_local.release()

_MISSING_OCU = (
    "[error: open-computer-use MCP is not installed. Install with "
    "`npm i -g open-computer-use` then restart. Computer Use stays off the "
    "tool schema until the binary exists, or pass computer_use.command.]"
)

_UNAPPROVED = (
    "[error: computer-use first-run approval required. Desktop control can "
    "click and type in any visible window. Set computer_use.approved=true "
    "or RXYCODE_COMPUTER_USE_APPROVED=1, then start a new session.]"
)


def _deny_factory(message: str):
    def _denied(**_kwargs: Any) -> str:
        return message

    return _denied


def _wrap_call(client: MCPClient, remote_name: str, schema: dict[str, Any], *, approved: bool):
    def sync_call(**kwargs: Any) -> str:
        if remote_name in ACTION_TOOLS and not approved:
            return _UNAPPROVED
        with _cu_call_lock() as held:
            if not held:
                return _OTHER_WINDOW
            payload = _strip_adapter_defaults(kwargs, schema)
            raw = client.call_tool(remote_name, payload)
            return _prefer_accessibility(raw)

    return sync_call


def _prefer_accessibility(raw: str) -> str:
    """Keep a11y JSON; drop bulky screenshot fields when present."""
    text = (raw or "").strip()
    if not text:
        return raw
    try:
        parsed, _end = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        return raw
    if not isinstance(parsed, dict):
        return raw
    for key in (
        "screenshot",
        "screenshot_png",
        "screenshotPng",
        "image_base64",
        "png",
        "overlay",
    ):
        parsed.pop(key, None)
    if "source" not in parsed and (
        "tree" in parsed or "nodes" in parsed or "elements" in parsed
    ):
        parsed["source"] = "accessibility"
    return json.dumps(parsed, ensure_ascii=False)


def _placeholder_schema(name: str) -> type[BaseModel]:
    if name == "list_apps":
        return create_model(
            "CUListAppsArgs",
            __config__=ConfigDict(extra="forbid"),
            query=(str | None, Field(default=None, description="Optional app name filter")),
        )
    if name == "get_app_state":
        return create_model(
            "CUGetAppStateArgs",
            __config__=ConfigDict(extra="forbid"),
            app=(str, Field(..., description="App name from list_apps")),
            include_screenshot=(
                bool,
                Field(default=False, description="Keep false; a11y tree is enough"),
            ),
        )
    if name in {"click", "perform_secondary_action", "set_value"}:
        return create_model(
            f"CU{name.title().replace('_', '')}Args",
            __config__=ConfigDict(extra="forbid"),
            app=(str, Field(...)),
            element_index=(str | int | None, Field(default=None)),
            x=(int | None, Field(default=None)),
            y=(int | None, Field(default=None)),
            action=(str | None, Field(default=None)),
            value=(str | None, Field(default=None)),
        )
    if name == "type_text":
        return create_model(
            "CUTypeTextArgs",
            __config__=ConfigDict(extra="forbid"),
            app=(str, Field(...)),
            text=(str, Field(...)),
        )
    if name == "press_key":
        return create_model(
            "CUPressKeyArgs",
            __config__=ConfigDict(extra="forbid"),
            app=(str, Field(...)),
            key=(str, Field(...)),
        )
    if name == "scroll":
        return create_model(
            "CUScrollArgs",
            __config__=ConfigDict(extra="forbid"),
            app=(str, Field(...)),
            element_index=(str | int | None, Field(default=None)),
            pages=(float | None, Field(default=None)),
            x=(int | None, Field(default=None)),
            y=(int | None, Field(default=None)),
        )
    if name == "drag":
        return create_model(
            "CUDragArgs",
            __config__=ConfigDict(extra="forbid"),
            app=(str, Field(...)),
            from_x=(int, Field(...)),
            from_y=(int, Field(...)),
            to_x=(int, Field(...)),
            to_y=(int, Field(...)),
        )
    return create_model(
        f"CU{name}Args",
        __config__=ConfigDict(extra="forbid"),
        app=(str | None, Field(default=None)),
    )


def _stub_tools(*, approved: bool, missing_binary: bool) -> list[StructuredTool]:
    message = _MISSING_OCU if missing_binary else (
        "[error: computer-use MCP is not connected]"
    )
    tools: list[StructuredTool] = []
    for name in OCU_TOOLS:
        risk = TOOL_RISK[name]
        if name in ACTION_TOOLS and not approved:
            func = _deny_factory(_UNAPPROVED)
        else:
            func = _deny_factory(message)
        register_tool_risk(name, risk)
        tools.append(
            StructuredTool(
                name=name,
                description=TOOL_DESCRIPTIONS[name],
                func=func,
                args_schema=_placeholder_schema(name),
                metadata={"source": "computer_use", "cu_kind": "ocu"},
            )
        )
    return tools


def bind_disabled_mapping(agent: Any) -> tuple[str, ...]:
    """Keep Computer Use names visible while the capability is off.

    Calling one asks the user to enable it (full_auto enables without a dialog).
    """
    orchestrator = getattr(agent, "_tool_orchestrator", None)
    if orchestrator is None:
        return ()
    if (
        getattr(agent, "_cu_fingerprint", None) == "disabled"
        and getattr(agent, "_cu_tool_names", ())
    ):
        return tuple(agent._cu_tool_names)

    unbind_computer_use(agent)
    bound: list[str] = []
    for name in CU_TOOL_ORDER:
        existing = orchestrator.get(name) if hasattr(orchestrator, "get") else None
        meta = getattr(existing, "metadata", None) or {}
        if existing is not None and meta.get("source") != "computer_use":
            continue
        register_tool_risk(name, TOOL_RISK.get(name, RiskLevel.WRITE))
        schema = create_model(
            f"CUOff{name}Args",
            __config__=ConfigDict(extra="allow"),
            url=(str | None, Field(default=None)),
        )
        tool = StructuredTool(
            name=name,
            description=TOOL_DESCRIPTIONS.get(name, name)
            + " Computer Use 未打开时调用会请求用户打开；full_auto 则直接打开并执行。",
            func=_deny_factory(
                "[error: Computer Use 未打开。请告诉用户需要打开 Computer Use。]"
            ),
            args_schema=schema,
            metadata={"source": "computer_use", "cu_kind": "disabled"},
        )
        orchestrator.register(name, tool, risk=TOOL_RISK.get(name, RiskLevel.WRITE))
        bound.append(name)
    agent._cu_client = None
    agent._cu_tool_names = tuple(bound)
    agent._cu_fingerprint = "disabled"
    return tuple(bound)


def _tools_from_client(client: MCPClient, *, approved: bool) -> list[StructuredTool]:
    discovered = {item.remote_name: item for item in client.get_tools()}
    tools: list[StructuredTool] = []
    for name in OCU_TOOLS:
        item = discovered.get(name)
        if item is None:
            continue
        schema = item.parameters if isinstance(item.parameters, dict) else {}
        register_tool_risk(name, TOOL_RISK.get(name, RiskLevel.WRITE))
        tools.append(
            StructuredTool(
                name=name,
                description=TOOL_DESCRIPTIONS.get(name) or item.description,
                func=_wrap_call(client, name, schema, approved=approved),
                args_schema=_build_args_schema(schema, model_name=f"CU{name}Args"),
                metadata={"source": "computer_use", "cu_kind": "ocu"},
            )
        )
    return tools


def unbind_computer_use(agent: Any) -> None:
    orchestrator = getattr(agent, "_tool_orchestrator", None)
    names = list(getattr(agent, "_cu_tool_names", ()) or ())
    if orchestrator is not None:
        for name in names:
            try:
                orchestrator.unregister(name)
            except Exception:
                pass
    client = getattr(agent, "_cu_client", None)
    if client is not None:
        try:
            client.disconnect()
        except Exception:
            pass
    agent._cu_client = None
    agent._cu_tool_names = ()
    agent._cu_fingerprint = None


def _fingerprint(config: dict[str, Any] | None, *, stub: bool) -> str:
    resolved = resolve_ocu_mcp(config)
    return json.dumps(
        {
            "enabled": is_enabled(config),
            "approved": is_approved(config),
            "browser": browser_enabled(config),
            "command": resolved,
            "stub": stub,
        },
        sort_keys=True,
    )


def bind_computer_use(
    agent: Any,
    *,
    client: MCPClient | None = None,
    stub: bool = False,
    config: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    """Register CU/browser tools in prefix-stable order. Returns bound names."""
    orchestrator = getattr(agent, "_tool_orchestrator", None)
    if orchestrator is None:
        return ()
    cfg = config if config is not None else getattr(agent, "_cfg", {}) or {}
    if not is_enabled(cfg) and client is None and not stub:
        # 废弃代码（2026-09-22）：未打开时不注册，模型看不到 Computer Use 工具。
        # unbind_computer_use(agent)
        # return ()
        return bind_disabled_mapping(agent)

    approved = is_approved(cfg)
    want_browser = browser_enabled(cfg)
    mark = _fingerprint(cfg, stub=stub or client is not None)
    if (
        not stub
        and client is None
        and getattr(agent, "_cu_fingerprint", None) == mark
        and getattr(agent, "_cu_tool_names", ())
    ):
        return tuple(agent._cu_tool_names)

    unbind_computer_use(agent)

    live_client = client
    tools: list[StructuredTool] = []
    if stub:
        tools = _stub_tools(approved=approved, missing_binary=False)
    elif live_client is not None:
        tools = _tools_from_client(live_client, approved=approved)
    else:
        server = mcp_server_config(cfg)
        if server is None:
            logger.warning("computer-use enabled but ocu binary was not found")
            tools = _stub_tools(approved=approved, missing_binary=True)
        else:
            # 废弃代码（2026-09-22）：绑定阶段拿不到终身锁就把整组工具换成拒绝函数。
            # 窗口只是开着、并没有正在调用，也会永久报「另一个窗口正在使用」。
            # elif not _hold_cu_desktop():
            #     tools = [deny _OTHER_WINDOW for name in OCU_TOOLS]
            live_client = MCPClient(
                OCU_SERVER_NAME,
                str(server["command"]),
                list(server.get("args") or []),
                timeout=float(server.get("timeout") or 30),
            )
            if not live_client.connect():
                logger.warning(
                    "computer-use MCP connect failed: %s",
                    live_client.last_error_type,
                )
                live_client.disconnect()
                live_client = None
                tools = _stub_tools(approved=approved, missing_binary=False)
            else:
                tools = _tools_from_client(live_client, approved=approved)

    by_name = {tool.name: tool for tool in tools}
    if want_browser:
        def _call(remote: str, args: dict[str, Any]) -> str:
            if live_client is None:
                return "[error: computer-use MCP is not connected]"
            if remote in ACTION_TOOLS and not approved:
                return _UNAPPROVED
            with _cu_call_lock() as held:
                if not held:
                    return _OTHER_WINDOW
                return _prefer_accessibility(live_client.call_tool(remote, args))

        for tool in make_browser_tools(call=_call, approved=approved):
            by_name[tool.name] = tool

    bound: list[str] = []
    for name in CU_TOOL_ORDER:
        # 废弃代码（2026-09-22）：CU 打开后无条件 register(browser_snapshot)，
        # 盖掉虚拟浏览器的同名工具，snapshot 变成 list_apps/MCP。
        if name in {"browser_navigate", "browser_snapshot", "browser_click"}:
            existing = orchestrator.get(name) if hasattr(orchestrator, "get") else None
            meta = getattr(existing, "metadata", None) or {}
            if existing is not None and meta.get("source") == "virtual_browser":
                continue
        tool = by_name.get(name)
        if tool is None:
            continue
        risk = TOOL_RISK.get(name, RiskLevel.WRITE)
        orchestrator.register(name, tool, risk=risk)
        bound.append(name)

    agent._cu_client = live_client
    agent._cu_tool_names = tuple(bound)
    agent._cu_fingerprint = mark
    return tuple(bound)


def sync_agent_computer_use(agent: Any, *, force: bool = False) -> tuple[str, ...]:
    """Idempotent bind used by AgentV2 and the appserver worker."""
    cfg = getattr(agent, "_cfg", {}) or {}
    if force:
        agent._cu_fingerprint = None
    # 废弃代码（2026-09-22）：未打开时卸掉工具并返回空。
    # if not is_enabled(cfg):
    #     unbind_computer_use(agent)
    #     return ()
    return bind_computer_use(agent, config=cfg)
