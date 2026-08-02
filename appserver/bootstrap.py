"""Agent bootstrap for appserver (mirrors api_server._init_agent without HTTP)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


def bootstrap_agent(
    *, stub: bool = False, workspace_root: Path | str | None = None
) -> Any:
    """Initialize AgentV2 (or stub) for stdio appserver."""
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
        os.chdir(root)
        log.info("bootstrap_agent: workspace_root=%s", root)
    else:
        project_root = Path(__file__).resolve().parents[1]
        os.chdir(project_root)

    try:
        from ..config.settings import load_config
        from ..utils.i18n import i18n
    except ImportError:
        from config.settings import load_config
        from utils.i18n import i18n

    log.info("bootstrap_agent: loading config")
    cfg = load_config()
    i18n.set_lang(cfg.get("language", "zh"))

    try:
        from ..core.agent_v2 import AgentV2 as Agent
    except ImportError:
        from core.agent_v2 import AgentV2 as Agent

    log.info("bootstrap_agent: constructing AgentV2 (may take 1-3 minutes)")
    agent = Agent()
    log.info("bootstrap_agent: AgentV2 ready")
    return agent
