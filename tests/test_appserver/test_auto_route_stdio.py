"""E2E: type user prompts over appserver stdio JSON-RPC (OpenTUI transport)."""

from __future__ import annotations

import json
import time

import pytest

from tests.test_appserver.test_stdio_integration import AppserverClient, _appserver_env, _appserver_proc_with_env


@pytest.fixture
def appserver_proc():
    proc = _appserver_proc_with_env(_appserver_env())
    import threading as _t

    def _drain():
        assert proc.stderr is not None
        for line in proc.stderr:
            text = line.rstrip()
            if text:
                print(f"[appserver-autoroute-stderr] {text}", flush=True)

    _t.Thread(target=_drain, daemon=True).start()
    try:
        yield proc
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=5)


def _boot(client: AppserverClient) -> str:
    client.request(
        "initialize",
        {
            "client_name": "pytest-auto-route",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
    )
    session = client.request("session/new", {"workspace_root": "."})
    return session["session_id"]


def test_stdio_user_types_greeting_solo_and_why_mode(appserver_proc):
    client = AppserverClient(appserver_proc)
    session_id = _boot(client)

    t0 = time.perf_counter()
    hello = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "你好"},
        timeout=15.0,
    )
    simple_s = time.perf_counter() - t0
    assert hello["status"] == "succeeded"
    assert hello["text"] == "stub:你好"
    assert simple_s <= 1.5, f"simple stdio TTFT {simple_s:.3f}s exceeds 1s±0.5s"

    why = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "/why-mode"},
        timeout=15.0,
    )
    assert why["status"] == "succeeded"
    assert "routing" in why["text"] or "mode=" in why["text"] or "no routing" in why["text"]

    solo = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "/solo 修一下 foo.py 里的空指针"},
        timeout=15.0,
    )
    assert solo["status"] == "succeeded"
    assert "foo.py" in solo["text"]

    explore_help = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "/explore"},
        timeout=15.0,
    )
    assert explore_help["status"] == "succeeded"
    assert "explore" in explore_help["text"].lower()

    persist = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "用explore"},
        timeout=15.0,
    )
    assert persist["status"] == "succeeded"
    assert "explore" in persist["text"].lower()

    team_flag = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "开专家团"},
        timeout=15.0,
    )
    assert team_flag["status"] == "succeeded"
    assert "专家团" in team_flag["text"]

    t1 = time.perf_counter()
    greeting_after_flag = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "你好"},
        timeout=15.0,
    )
    after_s = time.perf_counter() - t1
    assert greeting_after_flag["text"] == "stub:你好"
    assert after_s <= 3.2, f"routed greeting TTFT {after_s:.3f}s exceeds 3s±0.2s"

    why2 = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "/why-mode"},
        timeout=15.0,
    )
    assert "mode=solo" in why2["text"]
    assert "greeting" in why2["text"]


@pytest.fixture
def routed_appserver(tmp_path):
    """Stub appserver with agents.enabled so auto-route actually dispatches."""
    env = _appserver_env()
    data = tmp_path / "auto-route-data"
    data.mkdir()
    env["RXYCODE_DATA_DIR"] = str(data)
    (data / "config.yaml").write_text(
        "agents:\n  enabled: true\n  team: software_dev\n  route_mode: auto\n",
        encoding="utf-8",
    )
    proc = _appserver_proc_with_env(env)
    import threading as _t

    def _drain():
        assert proc.stderr is not None
        for line in proc.stderr:
            text = line.rstrip()
            if text:
                print(f"[appserver-autoroute-enabled-stderr] {text}", flush=True)

    _t.Thread(target=_drain, daemon=True).start()
    try:
        yield proc
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=5)


def test_stdio_user_types_greeting_explore_then_team(routed_appserver):
    """Simulated user over OpenTUI's JSON-RPC: greeting → 查文件 → 完整登录."""
    client = AppserverClient(routed_appserver)
    session_id = _boot(client)

    t0 = time.perf_counter()
    hello = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "你好"},
        timeout=15.0,
    )
    simple_s = time.perf_counter() - t0
    assert hello["status"] == "succeeded"
    assert hello["text"] == "stub:你好"
    assert simple_s <= 1.5, f"simple harness {simple_s:.3f}s exceeds 1s±0.5s"

    why = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "/why-mode"},
        timeout=15.0,
    )
    assert "mode=solo" in why["text"]
    assert "greeting" in why["text"]

    t1 = time.perf_counter()
    explore = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "查找认证模块在哪个文件"},
        timeout=15.0,
    )
    explore_s = time.perf_counter() - t1
    assert explore["status"] == "succeeded"
    assert explore["text"] == "explore:查找认证模块在哪个文件"
    assert explore_s <= 3.2, f"explore harness {explore_s:.3f}s exceeds 3s±0.2s"
    why_ex = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "/why-mode"},
        timeout=15.0,
    )
    assert "mode=explore" in why_ex["text"]

    t2 = time.perf_counter()
    team = client.request(
        "session/prompt",
        {
            "session_id": session_id,
            "text": "实现一个完整的登录功能，前后端都要",
        },
        timeout=15.0,
    )
    team_s = time.perf_counter() - t2
    assert team["status"] == "succeeded"
    assert team["text"] == "team:实现一个完整的登录功能，前后端都要"
    assert team_s <= 3.2, f"team harness {team_s:.3f}s exceeds 3s±0.2s"
    why_team = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "/why-mode"},
        timeout=15.0,
    )
    assert "mode=team" in why_team["text"]
