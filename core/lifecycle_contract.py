"""Pinned minimum lifecycle event set.

The tuple is the contract. Callers still use HookRegistry.emit(phase,
subject, payload). This module does not add a blockable PreToolUse.
"""

# 契约事件名 = (phase, subject)；与现有 HookRegistry.emit(phase, subject, payload) 对齐
HOOK_EVENT_CONTRACT = (
    ("before", "tool"),          # PreToolUse
    ("after", "tool"),           # PostToolUse
    ("before", "compact"),       # PreCompact
    ("after", "compact"),        # PostCompact
    ("after", "stop"),           # Stop
    ("after", "session_start"),  # SessionStart
    ("after", "session_end"),    # SessionEnd
    ("before", "timeout_decision"),  # PreTimeoutDecision（决策环 LLM 调用之前触发）
)
