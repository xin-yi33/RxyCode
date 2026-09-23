"""Protocol TUI adapter: maps AgentV2 TUI calls to protocol notifications."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

try:
    from ..protocol.notifications import (
        MessageDelta,
        PlanUpdate,
        ProgressUpdate,
        RecoveryAnalyzing,
        RecoveryAttempt,
        RecoveryExhausted,
        RecoveryResolved,
        RecoveryStarted,
        ReasoningSnapshot,
        ToolBegin,
        ToolEnd,
    )
    from ..recovery.tracker import RecoveryKind, RecoveryTracker
except ImportError:
    from protocol.notifications import (
        MessageDelta,
        PlanUpdate,
        ProgressUpdate,
        RecoveryAnalyzing,
        RecoveryAttempt,
        RecoveryExhausted,
        RecoveryResolved,
        RecoveryStarted,
        ReasoningSnapshot,
        ToolBegin,
        ToolEnd,
    )
    from recovery.tracker import RecoveryKind, RecoveryTracker

EmitCallback = Callable[[BaseModel], None]

# 2026-09-23（P0 answer-last）：委托深度读取，打标 intermediate 用。
# 非 appserver 环境（单测/CLI 直跑）导入失败时深度恒 0（主代理语义）。
try:
    from .runtime import current_delegate_depth as _current_delegate_depth
except Exception:
    try:
        from RxyCode.RxyCode1_1_0.appserver.runtime import (
            current_delegate_depth as _current_delegate_depth,
        )
    except Exception:
        def _current_delegate_depth() -> int:
            return 0

def _user_safe_text(value: Any, *, limit: int = 4000) -> str:
    """Bound tool/recovery summaries and remove common secret-shaped values."""
    text = str(value)
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)(api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    if len(text) > limit:
        return text[:limit] + " … [truncated]"
    return text


class ProtocolTui:
    """Minimal TUI surface for appserver: emit protocol models, no direct I/O.

    C3: when a StreamCoalescer is bound (``set_coalescer``), streaming kinds
    (token/reasoning/progress) are pushed into it so the worker writes stdout
    once per batch instead of once per token (RXYCODE_STREAM_COALESCE=1).
    Without a coalescer the legacy per-call emit path is kept unchanged
    (switch 0 = old behaviour).
    """

    def __init__(self, session_id: str, emit: EmitCallback, run_id: str = "") -> None:
        self.session_id = session_id
        self.run_id = str(run_id)
        self._emit = emit
        self._expand_thinking = False
        self._thinking_acc = ""
        self._reasoning_chunks = 0
        self._reasoning_last_liveness_at = 0.0
        self._mode = "build"
        self._model_name = ""
        self._coalescer: Any = None
        self._push_tasks: set[asyncio.Task[Any]] = set()
        self._push_failures: list[BaseException] = []
        self._streamed_answer_chars = 0
        self._recovery = RecoveryTracker(self._emit_recovery_record)

    def set_run_id(self, run_id: str) -> None:
        self.run_id = str(run_id)

    @property
    def recovery_tracker(self) -> RecoveryTracker:
        return self._recovery

    def _emit_recovery_record(self, record: dict[str, Any]) -> None:
        """Convert tracker records to typed protocol notifications."""
        common = {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "recovery_id": str(record["recovery_id"]),
            "event_id": str(record["event_id"]),
            "seq": int(record["seq"]),
            "timestamp": str(record["timestamp"]),
        }
        kind = record.get("kind")
        if kind == "started":
            self._emit(
                RecoveryStarted(
                    **common,
                    source_call_id=str(record["source_call_id"]),
                    recovery_kind=str(record["recovery_kind"]),
                    error_kind=str(record["error_kind"]),
                    max_attempts=int(record["max_attempts"]),
                )
            )
        elif kind == "analyzing":
            self._emit(RecoveryAnalyzing(**common))
        elif kind == "attempt":
            self._emit(
                RecoveryAttempt(
                    **common,
                    attempt=int(record["attempt"]),
                    strategy=str(record["strategy"]),
                    replacement_call_id=(
                        str(record["replacement_call_id"])
                        if record.get("replacement_call_id") is not None
                        else None
                    ),
                    display_summary=str(record["display_summary"]),
                )
            )
        elif kind == "resolved":
            self._emit(
                RecoveryResolved(
                    **common,
                    attempts=int(record["attempts"]),
                    display_summary=str(record["display_summary"]),
                )
            )
        elif kind == "exhausted":
            self._emit(
                RecoveryExhausted(
                    **common,
                    attempts=int(record["attempts"]),
                    final_error=str(record["final_error"]),
                )
            )

    def write_transport_retry(
        self,
        *,
        call_id: str,
        tool_name: str,
        attempt: int,
        max_attempts: int,
        error_kind: str,
    ) -> None:
        """Expose a READ transport retry without exposing raw exception text."""
        active = self._recovery.active
        if active is None:
            active = self._recovery.detect(
                source_call_id=call_id,
                recovery_kind=RecoveryKind.TRANSPORT_RETRY,
                error_kind=error_kind,
                max_attempts=max_attempts,
                run_id=self.run_id,
            )
        self._recovery.attempt(
            active.recovery_id,
            attempt=attempt,
            strategy="same_tool",
            display_summary=f"{tool_name} 遇到暂态错误，正在重试",
        )

    def resolve_active_recovery(self, display_summary: str = "已自动恢复") -> None:
        active = self._recovery.active
        if active is not None:
            self._recovery.resolve(
                active.recovery_id,
                display_summary=display_summary,
            )

    def exhaust_active_recovery(self, final_error: str) -> None:
        active = self._recovery.active
        if active is not None:
            self._recovery.exhaust(
                active.recovery_id,
                final_error=_user_safe_text(final_error),
            )

    def set_coalescer(self, coalescer: Any) -> None:
        """Bind a StreamCoalescer (C3); pass None to restore direct emit."""
        self._coalescer = coalescer

    @property
    def push_failures(self) -> list[BaseException]:
        return list(self._push_failures)

    async def drain_push_tasks(self) -> None:
        """Wait for ALL scheduled coalescer pushes before a final flush, so
        buffered tokens never race the trailing flush (C3 ordering).

        Loops until the task set is empty: a sync TUI callback that fires
        while draining (e.g. during a concurrent flush) creates another push
        task which is also awaited, so the drain is strict.  Exception
        collection is owned by the per-task done callback (``_on_push_done``),
        so failures are recorded exactly once; after the drain we yield once
        so callbacks run before the caller reads ``push_failures``.
        """
        while self._push_tasks:
            await asyncio.gather(*list(self._push_tasks), return_exceptions=True)
            await asyncio.sleep(0)  # let done callbacks / new pushes settle
        await asyncio.sleep(0)  # let final done callbacks collect failures

    async def push(self, kind: str, text: str) -> None:
        """Async push for streaming kinds: coalesce when bound, else emit."""
        coalescer = self._coalescer
        if coalescer is not None:
            await coalescer.push(kind, str(text))
            return
        self._emit_direct(kind, str(text))

    def _emit_direct(self, kind: str, text: str) -> None:
        """Single kind→notification mapping used by both the async push()
        fallback and the sync _push_async() legacy path (switch 0)."""
        intermediate = _current_delegate_depth() > 0
        if kind == "token":
            self._emit(
                MessageDelta(
                    session_id=self.session_id,
                    text=str(text),
                    intermediate=intermediate,
                )
            )
        elif kind == "reasoning":
            self._emit(
                ReasoningSnapshot(
                    session_id=self.session_id,
                    text=str(text),
                    snapshot=False,
                    intermediate=intermediate,
                )
            )
        elif kind == "progress":
            self._emit(
                ProgressUpdate(
                    session_id=self.session_id,
                    text=str(text),
                    intermediate=intermediate,
                )
            )

    def set_thinking_expanded(self, expanded: bool) -> None:
        was = self._expand_thinking
        self._expand_thinking = bool(expanded)
        # Mid-run expand: push accumulated thinking so the client can show it.
        # The snapshot is a plain notification: order it after any buffered
        # stream content (barrier) so it cannot overtake earlier tokens.
        if self._expand_thinking and not was and self._thinking_acc:
            self._flush_pending_stream()
            self._emit(
                ReasoningSnapshot(
                    session_id=self.session_id,
                    text=self._thinking_acc,
                    snapshot=True,
                )
            )

    def get_thinking_expanded(self) -> bool:
        return self._expand_thinking

    def set_mode(self, mode: str) -> None:
        self._mode = str(mode)

    def set_model(self, model_name: str) -> None:
        self._model_name = str(model_name)

    def write_progress(self, text: str) -> None:
        # Progress is a replacement status line. StreamCoalescer does not
        # concatenate progress segments, so "思考中（第 N 轮）…" cannot glue
        # onto "等待模型返回…". Flushing here would raise a barrier before
        # the following status line is queued.
        self._push_async("progress", text)

    def write_turn_liveness(self, text: str = "思考中...") -> None:
        """PHASE-FIX LC20: visible thinking within 1s/3s without waiting on TTFT.

        Collapsed CoT stays hidden (``write_reasoning``). This emits a short
        liveness snapshot so greetings and complex turns show thinking before
        the gateway's first model token.
        """
        chunk = str(text or "思考中...")
        self._flush_pending_stream()
        self._emit(
            ReasoningSnapshot(
                session_id=self.session_id,
                text=chunk,
                snapshot=False,
                intermediate=_current_delegate_depth() > 0,
            )
        )

    def write(self, text: str, color: str = "") -> None:
        self.write_progress(text)

    def write_info(self, text: str) -> None:
        self.write_progress(text)

    def write_success(self, text: str) -> None:
        self.write_progress(text)

    def write_warning(self, text: str) -> None:
        self.write_progress(text)

    def write_error(self, text: str) -> None:
        self.write_progress(f"[error] {text}")

    def write_reasoning(self, text: str) -> None:
        chunk = str(text)
        started = not self._thinking_acc
        self._thinking_acc += chunk
        self._reasoning_chunks += 1
        # Do not send the chain through StreamCoalescer. Runtime logs showed
        # hundreds of write_reasoning calls while the TUI only received the
        # "思考中..." liveness snapshot. Liveness already uses _emit and
        # arrives; keep the real chain on that same path.
        try:
            try:
                from ..core.ttft_clock import mark_reasoning
            except Exception:
                from RxyCode.RxyCode1_1_0.core.ttft_clock import mark_reasoning

            mark_reasoning(chunk, kind="tui")
        except Exception:
            pass
        self._flush_pending_stream()
        # INVARIANT: always emit the reasoning chunk. Collapse is the TUI's
        # job, and the default is expanded. Do not wrap this emit in
        # `if self._expand_thinking`.
        # 废弃代码（2026-09-22）：未展开时不发 ReasoningSnapshot，界面只剩
        # 「思考中...」，思考一结束首位 Thought 被收掉。
        # ⚠️ 勿轻易修改本方法（2026-09-23 重申）：首位 Thought 丢失风险。
        # 思考内容必须从这里发出。界面没有 Thought 时，先看模型有没有
        # reasoning，再看前端有没有把这条 ReasoningSnapshot 画出来。
        self._emit(
            ReasoningSnapshot(
                session_id=self.session_id,
                text=chunk,
                snapshot=False,
                intermediate=_current_delegate_depth() > 0,
            )
        )
        if started and chunk.strip() and not self._expand_thinking:
            self.write_progress("思考中...")

    def _emit_reasoning_liveness(self, chunk: str, started: bool) -> None:
        """Emit sparse liveness without exposing collapsed reasoning text."""
        if self._expand_thinking or not chunk.strip():
            return
        now = time.monotonic()
        if started:
            self._reasoning_last_liveness_at = now
            return
        if (
            self._reasoning_chunks % 64 == 0
            or now - self._reasoning_last_liveness_at >= 2.0
        ):
            self.write_progress(
                "Thinking... (model reasoning active; "
                f"{self._reasoning_chunks} chunks)"
            )
            self._reasoning_last_liveness_at = now

    def stream_token(self, token: str) -> None:
        self._streamed_answer_chars = int(
            getattr(self, "_streamed_answer_chars", 0) or 0
        ) + len(token or "")
        self._push_async("token", token)

    def _push_async(self, kind: str, text: str) -> None:
        """Submit a streaming notification from sync TUI callbacks (agent_v2
        calls the TUI synchronously).

        Coalesced path: the buffer append happens SYNCHRONOUSLY (push_sync)
        so the coalescer's pending batch is ordered exactly against plain
        emits (e.g. write_tool_call) that enqueue immediately after; only a
        threshold-triggered flush is scheduled as a tracked task.  The
        direct-emit path (switch 0) keeps the legacy behaviour.
        """
        coalescer = self._coalescer
        if coalescer is not None:
            if coalescer.push_sync(kind, str(text)):
                task = asyncio.get_running_loop().create_task(coalescer.flush())
                self._push_tasks.add(task)
                task.add_done_callback(self._on_push_done)
            return
        self._emit_direct(kind, str(text))

    def _on_push_done(self, task: asyncio.Task[Any]) -> None:
        self._push_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self._push_failures.append(exc)

    def write_plan(self, steps: Any) -> None:
        if isinstance(steps, str):
            lines = [line for line in steps.splitlines()]
        elif isinstance(steps, (list, tuple)):
            lines = [str(item) for item in steps]
        else:
            lines = [str(steps)]
        if not lines:
            lines = ["（空计划）"]
        self._flush_pending_stream()
        self._emit(PlanUpdate(session_id=self.session_id, steps=lines[:2000]))

    def write_step(self, num: int, total: int, desc: str) -> None:
        self.write_progress(f"step {num}/{total}: {desc}")

    def _flush_pending_stream(self) -> None:
        """Ordering barrier: submit any buffered stream content to the FIFO
        writer BEFORE a plain emit, so a tool notification that follows a
        token can never overtake it (sync sink only; no-op otherwise)."""
        coalescer = self._coalescer
        if coalescer is not None:
            coalescer.flush_submit_sync()

    def write_tool_call(self, name: str, args: Any, call_id: str | None = None) -> str:
        self._flush_pending_stream()
        resolved_id = str(call_id or uuid.uuid4().hex)
        arguments = args if isinstance(args, dict) else {"raw": str(args)}
        active = self._recovery.active
        if active is not None and active.recovery_kind != RecoveryKind.TRANSPORT_RETRY:
            strategy = "alternative_tool" if str(name) != "" else "retry_task"
            self._recovery.attempt(
                active.recovery_id,
                strategy=strategy,
                replacement_call_id=resolved_id,
                display_summary=f"正在调整后续工具调用：{name}",
            )
        self._emit(
            ToolBegin(
                session_id=self.session_id,
                call_id=resolved_id,
                tool_name=str(name),
                arguments=arguments,
            )
        )
        try:
            from ..core.progress_labels import tool_wait_progress
        except ImportError:
            from core.progress_labels import tool_wait_progress
        label = tool_wait_progress(str(name))
        if label:
            self.write_progress(label)
        return resolved_id

    def write_tool_result(
        self,
        result: Any,
        status: str = "success",
        call_id: str | None = None,
    ) -> None:
        self._flush_pending_stream()
        self._emit(
            ToolEnd(
                session_id=self.session_id,
                call_id=str(call_id or uuid.uuid4().hex),
                ok=status == "success",
            summary=_user_safe_text(result),
                status=status,
            )
        )
        normalized = str(status).lower()
        active = self._recovery.active
        if normalized in {"success", "ok"}:
            if active is not None:
                self.resolve_active_recovery()
        elif normalized not in {"cancelled", "canceled"} and active is None:
            record = self._recovery.detect(
                source_call_id=str(call_id or ""),
                recovery_kind=RecoveryKind.MODEL_RECOVERY,
                error_kind=normalized or "tool_error",
                max_attempts=3,
                run_id=self.run_id,
            )
            self._recovery.analyze(record.recovery_id)
        elif (
            normalized not in {"cancelled", "canceled"}
            and active is not None
            and active.recovery_kind == RecoveryKind.TRANSPORT_RETRY
        ):
            # The transport budget was exhausted.  The failed ToolMessage is
            # still handed to the model, so begin a distinct model-recovery
            # phase instead of conflating the two budgets.
            self._recovery.exhaust(
                active.recovery_id,
                final_error=_user_safe_text(result),
            )
            record = self._recovery.detect(
                source_call_id=str(call_id or ""),
                recovery_kind=RecoveryKind.MODEL_RECOVERY,
                error_kind=normalized or "tool_error",
                max_attempts=3,
                run_id=self.run_id,
            )
            self._recovery.analyze(record.recovery_id)

    def set_session_list_fn(self, fn: Any) -> None:
        return None

    def set_new_session_fn(self, fn: Any) -> None:
        return None
