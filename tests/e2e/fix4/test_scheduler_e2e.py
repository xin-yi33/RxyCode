"""layer=e2e E-F4-E2E-06 scheduler 真实消费链（stdio 子进程）。

测试 actor 声明（诚实标注）：`_WindowConsumer` 扮演 OpenTUI 窗口——后台线程按 cursor
poll session/events，收到 origin=="schedule" 的 event/user_message 即自动发起同文
session/prompt 并记录 Final。这就是窗口的真实消费契约；测试正文只允许用 actor 消费，
手动 session/prompt 补发 = §4 红灯。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from tests.e2e.fix4.helpers import (
    AppserverClient,
    appserver_env,
    poll_session_events,
    shutdown_appserver,
    spawn_appserver,
)

pytestmark = pytest.mark.e2e


def _spawn_scheduling_server(tmp_path) -> tuple:
    env = appserver_env({"RXYCODE_APPSERVER_SCHEDULE_TICK_SECONDS": "0.5"})
    proc = spawn_appserver(env, cwd=tmp_path)
    return proc, AppserverClient(proc)


def _iso_after(seconds: float) -> str:
    stamp = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=seconds)
    return stamp.isoformat(timespec="milliseconds")


def _scheduled(events: list[dict]) -> list[dict]:
    return [
        e for e in events
        if e.get("method") == "event/user_message"
        and str(((e.get("params") or {}).get("origin")) or "") == "schedule"
    ]


def _wait_until(predicate, timeout: float = 12.0, label: str = "") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(f"wait_until timeout: {label}")


class _WindowConsumer:
    """测试 actor：扮演 OpenTUI 窗口的真实消费契约。

    后台线程：按 cursor poll session/events → 收到 origin=="schedule" 的
    event/user_message → 自动发起同文 session/prompt → 记录 Final。
    consumed[i] 与 finals 的组合即"执行次数 × 真实产出"双锚。
    """

    def __init__(self, client: AppserverClient, session_id: str, *, cursor: int = 0):
        self.client = client
        self.session_id = session_id
        self.cursor = cursor
        self.consumed: list[str] = []
        self.finals: list[str] = []
        self.inflight = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="window-consumer")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.client.request(
                    "session/events",
                    {"session_id": self.session_id, "cursor": self.cursor},
                    timeout=5.0,
                )
            except Exception:  # client 关闭中 → 下一轮退出
                if self._stop.is_set():
                    return
                time.sleep(0.1)
                continue
            self.cursor = int(result.get("next_cursor") or self.cursor)
            for event in result.get("events") or []:
                params = event.get("params") or {}
                if event.get("method") != "event/user_message":
                    continue
                if str(params.get("origin") or "") != "schedule":
                    continue
                text = str(params.get("text") or "")
                self.consumed.append(text)
                self.inflight = True
                try:
                    final = self.client.request(
                        "session/prompt",
                        {"session_id": self.session_id, "text": text},
                        timeout=30.0,
                    )
                    self.finals.append(str(final.get("text") or ""))
                finally:
                    self.inflight = False

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)

    def consumed_count(self, text: str) -> int:
        return sum(1 for item in self.consumed if item == text)


def test_e2e_f4_06_full_chain_fire_consume_final_dedupe(tmp_path):
    """layer=e2e E-F4-E2E-06（**模拟窗口消费协议集成测试**，三轮复审 #4 正名）
    setup：真 appserver 子进程（stub）+ _WindowConsumer + at 规则 1.5s。
    扰动：到点 fire（actor 自动消费）→ 再投两个慢 turn（slow: 真实占位忙碌）→ 销毁并重建
    client + cursor 恢复（**消费方重建**，不是运输层重连；只重建消费方、保留同一 client 与唯一 reader；actor.close() 确认线程退出后
    同进程仅一 reader）。
    断言：三文本各消费恰 1 次且 Final 一一对应（"stub:<text>"）；无重投（事件计数后续不增长）；
    重建后零新投递；schedule/list 的 last_result.execution=="turn"。
    诚实边界：`_WindowConsumer` 是**模拟窗口消费方**——它验证后端对「按事件契约消费的
    窗口」的支持；生产 OpenTUI 的消费入口（frontend/opentui-app 的
    sessionEventsToMessages.ts / notifyToStreamEvent.ts）**当前没有 scheduled 消息的
    自动执行分支**，此处不声称 TUI 已能自动执行（该 surface 项另行登记）。
    """
    proc, client = _spawn_scheduling_server(tmp_path)
    try:
        session_id = client.initialize_and_session(str(tmp_path))
        actor = _WindowConsumer(client, session_id)          # actor poll → _claim_window_session（:1839）
        job = client.request(
            "schedule/create",
            {
                "rule": {"kind": "at", "time": _iso_after(1.5)},
                "action": {"kind": "session", "session_id": session_id, "message": "loop ping"},
            },
            timeout=5.0,
        )
        job_id = job["id"]

        _wait_until(
            lambda: actor.consumed_count("loop ping") == 1 and "stub:loop ping" in actor.finals,
            timeout=15.0,
            label="定时触发 → actor 消费一次 → 真实 Final",
        )
        assert actor.consumed_count("loop ping") == 1            # 到点恰一次执行
        assert actor.finals.count("stub:loop ping") == 1

        # 真实忙碌扰动：窗口正在执行 slow turn（真实占位），第二个 job 到点也来
        _busy1 = client.request(
            "schedule/create",
            {
                "rule": {"kind": "at", "time": _iso_after(0.8)},
                "action": {"kind": "session", "session_id": session_id, "message": "slow:busy01"},
            },
            timeout=5.0,
        )
        _busy2 = client.request(
            "schedule/create",
            {
                "rule": {"kind": "at", "time": _iso_after(1.0)},
                "action": {"kind": "session", "session_id": session_id, "message": "slow:busy02"},
            },
            timeout=5.0,
        )
        _wait_until(
            lambda: actor.consumed_count("slow:busy01") == 1
            and actor.consumed_count("slow:busy02") == 1
            and "stub:busy02" in actor.finals,
            timeout=20.0,
            label="忙碌占位下两 job 各执行一次（actor 串行、无二次执行）",
        )
        assert actor.finals.count("stub:busy01") == 1
        assert actor.finals.count("stub:busy02") == 1
        assert actor.inflight is False                           # 全部消化完

        jobs = client.request("schedule/list", {}, timeout=5.0)["jobs"]
        matched = [j for j in jobs if j["id"] == job_id]
        assert len(matched) == 1
        assert (matched[0].get("last_result") or {}).get("execution") == "turn"

        # 消费方重建（四轮复审 #1 修正）：只重建 _WindowConsumer，保留同一 client
        # 与唯一 reader——不通过关闭 stdout、不重建 client（那只会拿到已关闭的管道）。
        # 消费线程必须先确认退出。
        saved_cursor = actor.cursor
        actor.close()
        assert not actor._thread.is_alive()
        actor2 = _WindowConsumer(client, session_id, cursor=saved_cursor)
        consumed_before = dict()
        for text in ("loop ping", "slow:busy01", "slow:busy02"):
            consumed_before[text] = actor2.consumed_count(text)
        time.sleep(2.0)                                          # 观察窗（≥4 tick），纯观测非忙碌模拟
        for text, count in consumed_before.items():
            assert actor2.consumed_count(text) == count, text    # 重建零重复投递
        replayed = client.request(
            "session/events", {"session_id": session_id, "cursor": saved_cursor}, timeout=5.0
        )
        assert _scheduled(replayed["events"]) == []              # cursor 去重键生效
        actor2.close()
        assert not actor2._thread.is_alive()
    finally:
        shutdown_appserver(proc)   # 先停等 appserver 退出（stdout 收到 EOF）
        client.shutdown()          # 再 join reader、关句柄（顺序钉死：五轮复审 #1）


def test_e2e_f4_06_stop_never_fires_then_enable_fires_once(tmp_path):
    """layer=e2e E-F4-E2E-06（stop 面，actor 驱动）
    stop（toggle disabled）后越过到点 ≥6 个 tick：actor 零消费；
    再 enable → 恰一次触发 + 真实 Final（对照组：证明 "stop 后不再触发" 不是 "job 从不工作"）。
    """
    proc, client = _spawn_scheduling_server(tmp_path)
    try:
        session_id = client.initialize_and_session(str(tmp_path))
        actor = _WindowConsumer(client, session_id)
        job = client.request(
            "schedule/create",
            {
                "rule": {"kind": "at", "time": _iso_after(1.5)},
                "action": {"kind": "session", "session_id": session_id, "message": "stop ping"},
            },
            timeout=5.0,
        )
        client.request("schedule/toggle", {"job_id": job["id"], "enabled": False}, timeout=5.0)
        time.sleep(3.5)
        assert actor.consumed == []                              # stop 后不再触发（actor 视角零投递）

        client.request("schedule/toggle", {"job_id": job["id"], "enabled": True}, timeout=5.0)
        _wait_until(
            lambda: actor.consumed_count("stop ping") == 1 and "stub:stop ping" in actor.finals,
            timeout=10.0,
            label="enable 后恰一次触发",
        )
        assert actor.finals.count("stub:stop ping") == 1
        actor.close()
    finally:
        shutdown_appserver(proc)   # 先停等 appserver 退出（stdout 收到 EOF）
        client.shutdown()          # 再 join reader、关句柄（顺序钉死：五轮复审 #1）
