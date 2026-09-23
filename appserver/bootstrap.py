"""Agent bootstrap for appserver (mirrors api_server._init_agent without HTTP)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


def bootstrap_agent(
    *,
    stub: bool = False,
    workspace_root: Path | str | None = None,
    model_name: str | None = None,
    session_id: str | None = None,
) -> Any:
    """Initialize AgentV2 (or stub) for stdio appserver.

    ``session_id`` must be the owning session's real id.  AgentV2 defaults to
    the compatibility bucket ``"latest"``; every worker in the same data dir
    shares that bucket, so hydrating/saving under it both forgets per-session
    history on restart and leaks context across windows (2026-09-23 fix).
    """
    import logging

    log = logging.getLogger(__name__)
    delay_raw = os.environ.get("RXYCODE_APPSERVER_BOOTSTRAP_DELAY")
    if delay_raw:
        time.sleep(float(delay_raw))
    if stub:
        from .stub import StubAgent

        log.info("bootstrap_agent: using StubAgent")
        return StubAgent()

    if workspace_root is not None:
        root = Path(workspace_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        log.info("bootstrap_agent: workspace_root=%s", root)

    try:
        from ..config.settings import load_config
        from ..utils.i18n import i18n
    except ImportError:
        from config.settings import load_config
        from utils.i18n import i18n

    log.info("bootstrap_agent: loading config")
    cfg = load_config()
    i18n.set_lang(cfg.get("language", "zh"))

    # 2026-08-13: 预导入 langchain_openai（含 torch 传递链，实测 ~6.5s）——
    # AgentV2 已改懒导入（首次 _build_llm_from_config 才触发），这里在
    # bootstrap 阶段一次性预加载：运行时/切换模型的首次 LLM 构造不再卡 6.5s
    # （切换模型走 worker.switch_model 复用进程，秒级完成）。
    try:
        import langchain_openai  # noqa: F401 - 预导入消除运行时首次构造延迟
    except Exception as exc:  # pragma: no cover - 预导入失败不阻断 bootstrap
        log.warning("bootstrap_agent: langchain_openai preimport failed: %s", exc)

    try:
        from ..core.agent_v2 import AgentV2 as Agent
    except ImportError:
        from core.agent_v2 import AgentV2 as Agent

    log.info("bootstrap_agent: constructing AgentV2")
    # A Desktop session may choose a task-scoped model before its worker has
    # finished booting.  Pass that selection into the first AgentV2
    # construction so the cold worker never initializes the old global active
    # model only to rebuild it a moment later.
    # session_id: bind memory to THIS session before the hydrate below, so
    # load_session reads the per-session bucket instead of the shared
    # "latest" compatibility bucket (cross-window contamination fix).
    agent = Agent(model_name=model_name, session_id=session_id)
    try:
        memory = getattr(agent, "_memory", None)
        if memory is not None and hasattr(memory, "load_session"):
            memory.load_session(append_only=True)
            agent._session_loaded = True
    except Exception as exc:
        log.warning("bootstrap_agent: session hydrate failed: %s", exc)
    log.info("bootstrap_agent: AgentV2 ready")
    return agent
