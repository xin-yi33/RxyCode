"""SOP 状态机。

阶段转移完全由 TeamSpec.stages 里声明的 next_on_success / next_on_failure
决定，不由 LLM 决定。这是刻意的：调研显示基于 LLM 的动态路由「80% 时候很
漂亮，另外 20% 做出莫名其妙的决策，而且因为推理隐含在响应里而极难调试」
（见 PHASE-F §2.2）。

LLM 只在一个地方介入：某阶段失败且 next_on_failure 有多个候选时，由团长
决策打回给谁。这个决策点是显式标注的，会进 trace。
本模块是纯逻辑：不导入 LLM、不导入 Session、不做 IO。
"""

from __future__ import annotations

from dataclasses import dataclass

from RxyCode.RxyCode1_1_0.protocol.agents import SopStage, TeamSpec


@dataclass(frozen=True)
class StageRecord:
    """One advance() observation for trace / replay."""

    stage: str
    ok: bool
    retry: int
    next_stage: str | None


class SopMachine:
    def __init__(self, team: TeamSpec) -> None:
        self._team = team
        self._stages = {s.name: s for s in team.stages}
        self._current: str | None = team.entry_stage
        self._retries: dict[str, int] = {}
        self._history: list[StageRecord] = []

    def current_stage(self) -> SopStage | None:
        if self._current is None:
            return None
        return self._stages[self._current]

    def advance(self, *, ok: bool) -> SopStage | None:
        """按结果推进。返回下一阶段，None 表示流程结束。

        失败时先看 max_retries：还有次数就原地重试，用完了才走
        next_on_failure。
        """
        stage = self.current_stage()
        if stage is None:
            return None
        if ok:
            nxt = stage.next_on_success
            self._history.append(
                StageRecord(stage=stage.name, ok=True, retry=self._retries.get(stage.name, 0), next_stage=nxt)
            )
            self._current = nxt
            return self.current_stage()

        used = self._retries.get(stage.name, 0)
        if used < stage.max_retries:
            used += 1
            self._retries[stage.name] = used
            self._history.append(
                StageRecord(stage=stage.name, ok=False, retry=used, next_stage=stage.name)
            )
            return stage

        nxt = stage.next_on_failure
        if nxt and nxt != stage.name:
            self._retries[nxt] = 0
        self._history.append(
            StageRecord(stage=stage.name, ok=False, retry=used, next_stage=nxt)
        )
        self._current = nxt
        return self.current_stage()

    def history(self) -> list[StageRecord]:
        """完整的阶段轨迹，用于 trace 和事后复盘。"""
        return list(self._history)
