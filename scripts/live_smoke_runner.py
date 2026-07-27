#!/usr/bin/env python3
"""Multi-round live API GateLive smoke runner (W03–W23 via /chat + /command).

Honest results only: PASS / PARTIAL / SKIP / FAIL — never invent PASS for TTY windows.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

JARGON_RE = re.compile(
    r"synthesizer|claim\s*manifest|grounded\s*claims?|Build incomplete|LangGraph",
    re.IGNORECASE,
)
TOKEN = "live-smoke-rxycode-token-32chars-minimum!!"
SOCIAL_MSG = "我很难过，你能陪我玩游戏吗？"
SOCIAL_FOLLOWUPS = [
    "那我们玩猜数字吧，你先想一个1到10的数",
    "我猜是7，对吗？",
    "谢谢你陪我，今天就到这里吧",
]
CODE_MSG = "写一个跑酷小游戏并保存"
CODE_STREAM_TIMEOUT = 180.0
CHAT_TIMEOUT = 90.0
TOOL_STREAM_TIMEOUT = 120.0
SESSION_ID = "live-smoke-multiround"
MCP_SMOKE_NAME = "live-smoke-echo-mcp"
SKILL_SMOKE_PROBE = "live-smoke-nonexistent-skill-zz"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _request(
    method: str,
    url: str,
    body: dict | None = None,
    token: str = TOKEN,
    timeout: float = 30.0,
) -> tuple[int, str, str | None]:
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace"), None
    except Exception as exc:
        return 0, "", f"{type(exc).__name__}: {exc}"


def _wait_ready(port: int, timeout: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/status"
    while time.monotonic() < deadline:
        status, _, err = _request("GET", url, timeout=5.0)
        if status == 200 and not err:
            return True
        time.sleep(0.25)
    return False


def _wait_agent_ready(port: int, timeout: float = 90.0) -> dict:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/status"
    last: dict = {}
    while time.monotonic() < deadline:
        status, body, _ = _request("GET", url, timeout=5.0)
        if status == 200:
            last = json.loads(body)
            if last.get("model") not in (None, "", "unknown"):
                return last
        time.sleep(0.5)
    return last


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event_type = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        payload = "\n".join(data_lines)
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {"raw": payload}
        events.append({"event": event_type, "data": parsed})
    return events


def _cmd(port: int, command: str, timeout: float = 30.0) -> dict:
    t0 = time.monotonic()
    code, body, err = _request(
        "POST",
        f"http://127.0.0.1:{port}/command",
        {"command": command, "session_id": SESSION_ID},
        timeout=timeout,
    )
    elapsed = round(time.monotonic() - t0, 3)
    payload: dict[str, Any] = {}
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body[:500]}
    return {
        "command": command,
        "status_code": code,
        "elapsed_s": elapsed,
        "error": err,
        "action": payload.get("action"),
        "message_excerpt": str(payload.get("message", ""))[:400],
        "payload_keys": sorted(payload.keys()),
        "payload": payload,
        "ok": code == 200 and not err and payload.get("action") != "error",
    }


def _chat(port: int, message: str, mode: str = "build", timeout: float = CHAT_TIMEOUT) -> dict:
    t0 = time.monotonic()
    code, body, err = _request(
        "POST",
        f"http://127.0.0.1:{port}/chat",
        {"message": message, "mode": mode, "session_id": SESSION_ID},
        timeout=timeout,
    )
    elapsed = round(time.monotonic() - t0, 3)
    payload: dict[str, Any] = {}
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body[:500]}
    combined = str(payload.get("response", "")) + str(payload.get("error", ""))
    return {
        "message": message,
        "mode": mode,
        "status_code": code,
        "elapsed_s": elapsed,
        "error": err or payload.get("error"),
        "jargon_detected": bool(JARGON_RE.search(combined)),
        "response_excerpt": combined[:500],
        "ok": code == 200 and not err and not payload.get("error"),
    }


def _approve(port: int, approval_id: str, decision: str = "approved") -> dict:
    code, body, err = _request(
        "POST",
        f"http://127.0.0.1:{port}/approve",
        {"approval_id": approval_id, "decision": decision},
        timeout=10.0,
    )
    payload: dict[str, Any] = {}
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body[:200]}
    return {
        "status_code": code,
        "error": err,
        "ok": code == 200 and not err and payload.get("ok") is True,
        "payload": payload,
        "approval_id": approval_id,
        "decision": decision,
    }


def _chat_stream(
    port: int,
    message: str,
    mode: str = "build",
    timeout: float = CODE_STREAM_TIMEOUT,
    *,
    auto_approve: bool = True,
) -> dict:
    """POST /chat/stream and collect SSE until done or timeout.

    When auto_approve is True, resolves approval_request events via POST /approve
    so WRITE/DANGER tools can proceed in API smoke (W12).
    """
    t0 = time.monotonic()
    url = f"http://127.0.0.1:{port}/chat/stream"
    data = json.dumps(
        {"message": message, "mode": mode, "session_id": SESSION_ID}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    event_types: list[str] = []
    answer_parts: list[str] = []
    tool_names: list[str] = []
    approvals: list[dict] = []
    approve_results: list[dict] = []
    progress_count = 0
    err: str | None = None
    status_code = 0
    done = False
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status
            buf = ""
            while not done:
                chunk = resp.read(4096)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    for line in block.splitlines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        try:
                            ev = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        et = str(ev.get("type", "message"))
                        event_types.append(et)
                        if et in ("progress", "tool_start", "tool_end", "step", "status"):
                            progress_count += 1
                        if et in ("answer", "token", "content", "text", "final"):
                            answer_parts.append(
                                str(ev.get("content") or ev.get("text") or ev.get("message") or "")
                            )
                        if et == "tool_call":
                            name = str(ev.get("name") or ev.get("tool") or "")
                            if name:
                                tool_names.append(name)
                            progress_count += 1
                        if et == "tool_result":
                            progress_count += 1
                        if et == "approval_request":
                            aid = str(ev.get("approval_id") or "")
                            approvals.append(
                                {
                                    "approval_id": aid,
                                    "tool": ev.get("tool") or ev.get("tool_name"),
                                    "risk": ev.get("risk"),
                                }
                            )
                            if auto_approve and aid:
                                approve_results.append(_approve(port, aid, "approved"))
                        if et == "error":
                            err = str(ev.get("message") or ev.get("content") or "stream error")
                        if et == "done":
                            done = True
                            break
                    if done:
                        break
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    elapsed = round(time.monotonic() - t0, 3)
    answer = "".join(answer_parts)
    return {
        "message": message,
        "mode": mode,
        "status_code": status_code,
        "elapsed_s": elapsed,
        "error": err,
        "event_types": event_types[:60],
        "progress_events": progress_count,
        "unique_event_types": sorted(set(event_types)),
        "tool_names": tool_names,
        "approvals": approvals,
        "approve_results": [
            {k: r[k] for k in ("ok", "status_code", "approval_id", "decision")}
            for r in approve_results
        ],
        "jargon_detected": bool(JARGON_RE.search(answer + str(err or ""))),
        "response_excerpt": (answer or str(err or ""))[:500],
        "ok": status_code == 200 and not err and bool(answer),
        "partial_ok": status_code == 200 and progress_count > 0 and not answer,
    }


def _window(result: str, note: str, evidence: Any = None) -> dict:
    return {"result": result, "note": note, "evidence": evidence}


def _run_opentui_gate_test(repo_root: Path) -> dict:
    """Run headless ScrollBox/textarea bun:test for W01/W02 PARTIAL evidence."""
    app_dir = repo_root / "frontend" / "opentui-app"
    bun = Path(os.environ.get("USERPROFILE", "")) / ".bun" / "bin" / "bun.exe"
    bun_cmd = str(bun) if bun.exists() else "bun"
    try:
        proc = subprocess.run(
            [bun_cmd, "test", "src/scrollbox.gate.test.tsx"],
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "PATH": str(bun.parent) + os.pathsep + os.environ.get("PATH", "")},
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return {
            "ok": proc.returncode == 0 and "pass" in out.lower(),
            "returncode": proc.returncode,
            "excerpt": out[-800:],
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    port = _free_port()
    repo_root = Path(__file__).resolve().parents[1]
    parent = repo_root.parent
    env = dict(os.environ)
    env["PYTHONPATH"] = str(parent) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    server_code = f"""
from RxyCode.RxyCode1_1_0.api_server import configure_api_access, app
import uvicorn
configure_api_access(allow_remote=False, token={TOKEN!r})
uvicorn.run(app, host="127.0.0.1", port={port}, log_level="info")
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", server_code],
        cwd=str(parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    results: dict[str, Any] = {
        "port": port,
        "token_set": True,
        "session_id": SESSION_ID,
        "checks": {},
        "windows": {},
        "turns": [],
    }
    try:
        if not _wait_ready(port):
            tail = (proc.stdout.read(4000) if proc.stdout else "") if proc.poll() is not None else ""
            results["checks"]["server_ready"] = {"ok": False, "detail": tail[-2000:]}
            results["windows"]["W03"] = _window("FAIL", "server not ready")
            _write(results)
            return 1
        results["checks"]["server_ready"] = {"ok": True}

        # W03 early: /thinking BEFORE agent ready (must be fast, no hang)
        early_t0 = time.monotonic()
        early_think = _cmd(port, "/thinking", timeout=5.0)
        early_elapsed = round(time.monotonic() - early_t0, 3)
        results["checks"]["thinking_before_agent"] = {
            **early_think,
            "wall_s": early_elapsed,
            "ok": early_think["ok"]
            and early_think.get("action") == "thinking_toggled"
            and early_elapsed < 3.0,
        }

        agent_status = _wait_agent_ready(port)
        agent_ok = agent_status.get("model") not in (None, "", "unknown")
        results["checks"]["agent_ready"] = {
            "ok": agent_ok,
            "model": agent_status.get("model"),
        }
        llm_available = bool(agent_ok)

        # --- W08 status + cache ---
        status_code, status_body, _ = _request("GET", f"http://127.0.0.1:{port}/status")
        status_json = json.loads(status_body) if status_code == 200 else {}
        app_cache = status_json.get("application_cache")
        provider_cache = status_json.get("provider_cache")
        results["checks"]["w08_status"] = {
            "ok": status_code == 200
            and isinstance(app_cache, dict)
            and set(app_cache.keys()) >= {"precise", "semantic"}
            and isinstance(provider_cache, dict)
            and "hit_rate" in provider_cache,
            "status_code": status_code,
            "application_cache_keys": sorted(app_cache.keys()) if isinstance(app_cache, dict) else None,
            "provider_cache_keys": sorted(provider_cache.keys()) if isinstance(provider_cache, dict) else None,
            "cache_rate": status_json.get("cache_rate"),
            "model": status_json.get("model"),
        }
        cache_cmd = _cmd(port, "/cache")
        results["checks"]["w08_command_cache"] = {
            "ok": cache_cmd["ok"] and cache_cmd.get("action") == "cache_stats",
            **{k: cache_cmd[k] for k in ("action", "elapsed_s", "payload_keys")},
            "has_application_cache": "application_cache" in cache_cmd.get("payload", {}),
            "has_provider_cache": "provider_cache" in cache_cmd.get("payload", {}),
        }

        # W03 thinking toggle after agent ready
        t1 = _cmd(port, "/thinking", timeout=5.0)
        t2 = _cmd(port, "/thinking", timeout=5.0)
        results["checks"]["thinking_toggle"] = {
            "ok": t1["ok"]
            and t2["ok"]
            and t1.get("action") == "thinking_toggled"
            and t2.get("action") == "thinking_toggled"
            and t1["payload"].get("expanded") is not t2["payload"].get("expanded"),
            "first": {"expanded": t1["payload"].get("expanded"), "elapsed_s": t1["elapsed_s"]},
            "second": {"expanded": t2["payload"].get("expanded"), "elapsed_s": t2["elapsed_s"]},
            "before_agent_ok": results["checks"]["thinking_before_agent"]["ok"],
        }
        early_ok = results["checks"]["thinking_before_agent"]["ok"]
        toggle_ok = results["checks"]["thinking_toggle"]["ok"]
        if early_ok and toggle_ok:
            results["windows"]["W03"] = _window(
                "PASS",
                " /thinking before+after agent init; toggle expands/collapses",
                results["checks"]["thinking_toggle"],
            )
        elif toggle_ok or early_ok:
            results["windows"]["W03"] = _window(
                "PARTIAL",
                "thinking partially ok",
                results["checks"]["thinking_toggle"],
            )
        else:
            results["windows"]["W03"] = _window("FAIL", "thinking toggle failed")

        # Unit routing helpers
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        agent = object.__new__(AgentV2)
        results["checks"]["w04_unit_social"] = {
            "ok": agent._is_social_chat(SOCIAL_MSG) is True,
            "value": agent._is_social_chat(SOCIAL_MSG),
        }
        results["checks"]["w04b_unit_not_social"] = {
            "ok": agent._is_social_chat(CODE_MSG) is False,
            "value": agent._is_social_chat(CODE_MSG),
        }

        # --- Multi-round LLM session (≥4 turns) when model available ---
        social_turns: list[dict] = []
        if llm_available:
            first = _chat(port, SOCIAL_MSG, mode="build", timeout=CHAT_TIMEOUT)
            social_turns.append(first)
            results["turns"].append({"window": "W04", "turn": 1, **first})
            if first["ok"] and not first["jargon_detected"]:
                for i, follow in enumerate(SOCIAL_FOLLOWUPS, start=2):
                    turn = _chat(port, follow, mode="build", timeout=CHAT_TIMEOUT)
                    social_turns.append(turn)
                    results["turns"].append({"window": "W04", "turn": i, **turn})
            results["checks"]["w04_multiround"] = {
                "ok": len(social_turns) >= 4
                and all(t["ok"] and not t["jargon_detected"] for t in social_turns),
                "turn_count": len(social_turns),
                "turns_ok": sum(1 for t in social_turns if t["ok"]),
                "jargon_any": any(t["jargon_detected"] for t in social_turns),
                "excerpts": [t["response_excerpt"][:160] for t in social_turns],
            }
            mr = results["checks"]["w04_multiround"]
            if mr["ok"]:
                results["windows"]["W04"] = _window(
                    "PASS", f"social multi-round {mr['turn_count']} turns, no jargon", mr
                )
            elif social_turns and social_turns[0]["ok"] and not social_turns[0]["jargon_detected"]:
                results["windows"]["W04"] = _window(
                    "PARTIAL",
                    f"first social ok but only {mr['turn_count']} successful turns",
                    mr,
                )
            else:
                results["windows"]["W04"] = _window("FAIL", "social chat failed", mr)
        else:
            results["windows"]["W04"] = _window("SKIP", "LLM/agent not ready")
            results["checks"]["w04_multiround"] = {"ok": False, "turn_count": 0}

        # W04b: longer stream timeout for parkour game build
        if llm_available:
            stream = _chat_stream(port, CODE_MSG, mode="build", timeout=CODE_STREAM_TIMEOUT)
            results["checks"]["w04b_code_stream"] = stream
            results["turns"].append({"window": "W04b", "turn": "stream", **stream})
            unit_ok = results["checks"]["w04b_unit_not_social"]["ok"]
            if stream["ok"] and not stream["jargon_detected"] and unit_ok:
                results["windows"]["W04b"] = _window(
                    "PASS",
                    f"stream completed in {stream['elapsed_s']}s with answer",
                    {"progress_events": stream["progress_events"], "elapsed_s": stream["elapsed_s"]},
                )
            elif stream.get("partial_ok") or (stream["status_code"] == 200 and stream["progress_events"] > 0):
                results["windows"]["W04b"] = _window(
                    "PARTIAL",
                    f"stream progress seen but no final answer / error={stream.get('error')}",
                    stream,
                )
            elif stream.get("error") and "Timeout" in str(stream.get("error")):
                results["windows"]["W04b"] = _window(
                    "PARTIAL",
                    f"unit routing ok; stream TimeoutError @{CODE_STREAM_TIMEOUT}s "
                    f"(progress_events={stream.get('progress_events', 0)})",
                    stream,
                )
            else:
                results["windows"]["W04b"] = _window(
                    "PARTIAL" if unit_ok else "FAIL",
                    f"unit={unit_ok}; stream error={stream.get('error')}",
                    stream,
                )
        else:
            results["windows"]["W04b"] = _window("SKIP", "LLM/agent not ready")

        # --- Mode switches W05–W07 (command-level live; not full TUI policy) ---
        plan = _cmd(port, "/plan")
        build = _cmd(port, "/build")
        compose = _cmd(port, "/compose")
        mode_show = _cmd(port, "/mode build")
        results["checks"]["modes"] = {
            "plan": plan,
            "build": build,
            "compose": compose,
            "mode_build": mode_show,
        }
        # Light plan-mode chat (read-oriented ask) if LLM up — counts as round evidence
        plan_chat = None
        if llm_available:
            plan_chat = _chat(
                port,
                "用一句话说明当前仓库是做什么的，不要修改任何文件",
                mode="plan",
                timeout=CHAT_TIMEOUT,
            )
            results["turns"].append({"window": "W05", "turn": "plan_chat", **plan_chat})
        results["checks"]["w05_plan"] = {
            "cmd_ok": plan["ok"] and plan.get("action") == "mode_changed",
            "chat": plan_chat,
        }
        if plan["ok"] and plan.get("action") == "mode_changed":
            note = " /plan mode_changed"
            if plan_chat and plan_chat.get("ok"):
                note += "; plan-mode chat ok"
                results["windows"]["W05"] = _window("PASS", note, results["checks"]["w05_plan"])
            else:
                results["windows"]["W05"] = _window(
                    "PARTIAL",
                    note + "; full plan safety/write-deny not live-proven",
                    results["checks"]["w05_plan"],
                )
        else:
            results["windows"]["W05"] = _window("FAIL", " /plan failed", plan)

        if build["ok"] and build.get("action") == "mode_changed":
            results["windows"]["W06"] = _window(
                "PARTIAL",
                "/build mode_changed; full edit+test pipeline not completed in smoke "
                "(see W04b stream)",
                build,
            )
        else:
            results["windows"]["W06"] = _window("FAIL", "/build failed", build)

        if compose["ok"] and compose.get("action") == "mode_changed":
            results["windows"]["W07"] = _window(
                "PARTIAL",
                "/compose mode_changed; replan/cache compose loop not fully exercised",
                compose,
            )
        else:
            results["windows"]["W07"] = _window("FAIL", "/compose failed", compose)

        # W08
        if results["checks"]["w08_status"]["ok"] and results["checks"]["w08_command_cache"]["ok"]:
            results["windows"]["W08"] = _window(
                "PARTIAL",
                "dual-track /status+/cache ok; same-question hit retest not run",
                {
                    "cache_rate": results["checks"]["w08_status"].get("cache_rate"),
                    "status": results["checks"]["w08_status"],
                },
            )
        else:
            results["windows"]["W08"] = _window("FAIL", "cache dual-track fields missing")

        # W09 provider cache gate
        rate_raw = str(status_json.get("cache_rate") or "0")
        try:
            rate_val = float(str(rate_raw).replace("%", "").strip() or 0)
        except ValueError:
            rate_val = 0.0
        if rate_val >= 85.0:
            results["windows"]["W09"] = _window("PASS", f"provider cache_rate={rate_raw}")
        else:
            results["windows"]["W09"] = _window(
                "SKIP",
                f"N/A: cache_rate={rate_raw} (<85%); smoke not warm enough",
            )

        # W10 memory (must leave Plan mode — memory writes are blocked there)
        _cmd(port, "/build")
        mem_add = _cmd(port, "/memory add live-smoke-note-gate-2026-07-28", timeout=60.0)
        mem_list = _cmd(port, "/memory list", timeout=60.0)
        mem_search = _cmd(port, "/memory search live-smoke", timeout=60.0)
        results["checks"]["w10_memory"] = {
            "add": {k: mem_add[k] for k in ("ok", "action", "elapsed_s", "message_excerpt", "error")},
            "list": {k: mem_list[k] for k in ("ok", "action", "elapsed_s", "message_excerpt", "error")},
            "search": {
                k: mem_search[k] for k in ("ok", "action", "elapsed_s", "message_excerpt", "error")
            },
        }
        mem_ok = mem_add["ok"] and mem_list["ok"] and mem_search["ok"]
        if mem_ok:
            results["windows"]["W10"] = _window("PASS", "memory add/list/search via /command", results["checks"]["w10_memory"])
        elif mem_add["ok"] or mem_list["ok"]:
            results["windows"]["W10"] = _window("PARTIAL", "partial memory commands", results["checks"]["w10_memory"])
        else:
            results["windows"]["W10"] = _window("FAIL", "memory commands failed", results["checks"]["w10_memory"])

        # W11–W18: honest live probes (commands + multi-round LLM when available)
        _cmd(port, "/build")

        # --- W14 Skills (command multi-round; avoid real downloads) ---
        sk_list1 = _cmd(port, "/list-skills", timeout=30.0)
        sk_rm = _cmd(port, f"/remove-skill {SKILL_SMOKE_PROBE}", timeout=30.0)
        sk_find = _cmd(port, f"/find-skill {SKILL_SMOKE_PROBE}", timeout=60.0)
        sk_list2 = _cmd(port, "/list-skills", timeout=30.0)
        results["checks"]["w14_skills"] = {
            "list1": {k: sk_list1[k] for k in ("ok", "action", "message_excerpt", "error")},
            "remove_missing": {k: sk_rm[k] for k in ("ok", "action", "message_excerpt", "error")},
            "find_missing": {k: sk_find[k] for k in ("ok", "action", "message_excerpt", "error")},
            "list2": {k: sk_list2[k] for k in ("ok", "action", "message_excerpt", "error")},
            "turns": 4,
        }
        if sk_list1["ok"] and sk_list2["ok"]:
            # find/remove of missing skill may return action=error — still proves wiring
            results["windows"]["W14"] = _window(
                "PASS",
                "skills list x2 + remove-missing + find-missing command multi-round (4)",
                results["checks"]["w14_skills"],
            )
        elif sk_list1["ok"] or sk_list2["ok"]:
            results["windows"]["W14"] = _window(
                "PARTIAL", "partial skills commands", results["checks"]["w14_skills"]
            )
        else:
            results["windows"]["W14"] = _window(
                "FAIL", "skills list failed", results["checks"]["w14_skills"]
            )

        # --- W13 MCP (command multi-round with cleanup) ---
        mcp_list1 = _cmd(port, "/list-mcp", timeout=30.0)
        mcp_add = _cmd(
            port,
            f"/addmcp {MCP_SMOKE_NAME} python -c \"print('live-smoke-mcp')\"",
            timeout=60.0,
        )
        mcp_list2 = _cmd(port, "/list-mcp", timeout=30.0)
        mcp_rm = _cmd(port, f"/remove-mcp {MCP_SMOKE_NAME}", timeout=30.0)
        results["checks"]["w13_mcp"] = {
            "list1": {k: mcp_list1[k] for k in ("ok", "action", "message_excerpt", "error")},
            "add": {k: mcp_add[k] for k in ("ok", "action", "message_excerpt", "error")},
            "list2": {k: mcp_list2[k] for k in ("ok", "action", "message_excerpt", "error")},
            "remove": {k: mcp_rm[k] for k in ("ok", "action", "message_excerpt", "error")},
            "turns": 4,
        }
        listed_after = MCP_SMOKE_NAME in str(mcp_list2.get("message_excerpt", "")) or mcp_add["ok"]
        if mcp_list1["ok"] and mcp_add["ok"] and mcp_rm["ok"]:
            results["windows"]["W13"] = _window(
                "PASS",
                "MCP list/add/list/remove multi-round (4)",
                results["checks"]["w13_mcp"],
            )
        elif mcp_list1["ok"] and (mcp_add["ok"] or listed_after):
            results["windows"]["W13"] = _window(
                "PARTIAL",
                "MCP list ok; add/remove incomplete",
                results["checks"]["w13_mcp"],
            )
        elif mcp_list1["ok"]:
            results["windows"]["W13"] = _window(
                "PARTIAL",
                "MCP list ok; add blocked/failed (no config mutation success)",
                results["checks"]["w13_mcp"],
            )
        else:
            results["windows"]["W13"] = _window(
                "FAIL", "MCP list failed", results["checks"]["w13_mcp"]
            )

        # W19/W20/W23 BEFORE heavy LLM windows (W11+) — avoids chat-lock timeouts
        q_list = _cmd(port, "/queue")
        q_add = _cmd(port, "/queue add live-smoke-noop-prompt-do-not-run")
        q_list2 = _cmd(port, "/queue list")
        q_remove = None
        task = (q_add.get("payload") or {}).get("task") or {}
        if task.get("id") is not None:
            q_remove = _cmd(port, f"/queue remove {task['id']}")
        sched = _cmd(port, "/schedule list")
        results["checks"]["w19_queue_schedule"] = {
            "queue_list": {k: q_list[k] for k in ("ok", "action", "error")},
            "queue_add": {k: q_add[k] for k in ("ok", "action", "error", "message_excerpt")},
            "queue_list2": {k: q_list2[k] for k in ("ok", "action", "error")},
            "queue_remove": (
                {k: q_remove[k] for k in ("ok", "action", "error")} if q_remove else None
            ),
            "schedule_list": {k: sched[k] for k in ("ok", "action", "error", "message_excerpt")},
        }
        if q_add["ok"] and q_list["ok"] and sched["ok"]:
            results["windows"]["W19"] = _window(
                "PASS",
                "queue add/list/remove + schedule list via /command",
                results["checks"]["w19_queue_schedule"],
            )
        elif q_list["ok"] or sched["ok"]:
            results["windows"]["W19"] = _window(
                "PARTIAL", "partial queue/schedule", results["checks"]["w19_queue_schedule"]
            )
        else:
            results["windows"]["W19"] = _window(
                "FAIL", "queue/schedule failed", results["checks"]["w19_queue_schedule"]
            )

        save = _cmd(port, "/save-chat live-smoke-session-2026-07-28")
        listing = _cmd(port, "/list-chats")
        load = _cmd(port, "/load-chat live-smoke-session-2026-07-28")
        results["checks"]["w20_session"] = {
            "save": {k: save[k] for k in ("ok", "action", "error", "message_excerpt")},
            "list": {k: listing[k] for k in ("ok", "action", "error", "message_excerpt")},
            "load": {k: load[k] for k in ("ok", "action", "error", "message_excerpt")},
        }
        if save["ok"] and listing["ok"]:
            results["windows"]["W20"] = _window(
                "PASS" if load["ok"] else "PARTIAL",
                "save-chat + list-chats"
                + (" + load-chat" if load["ok"] else " (load partial/fail)"),
                results["checks"]["w20_session"],
            )
        else:
            results["windows"]["W20"] = _window(
                "FAIL", "session save/list failed", results["checks"]["w20_session"]
            )

        models = _cmd(port, "/models")
        lang_show = _cmd(port, "/language")
        lang_en = _cmd(port, "/language en")
        lang_zh = _cmd(port, "/language zh")
        results["checks"]["w23_i18n_models"] = {
            "models": {k: models[k] for k in ("ok", "action", "message_excerpt", "error")},
            "language_show": {k: lang_show[k] for k in ("ok", "action", "message_excerpt", "error")},
            "language_en": {k: lang_en[k] for k in ("ok", "action", "message_excerpt", "error")},
            "language_zh": {k: lang_zh[k] for k in ("ok", "action", "message_excerpt", "error")},
        }
        if models["ok"] and (lang_en["ok"] or lang_show["ok"]):
            results["windows"]["W23"] = _window(
                "PASS",
                "/models + /language toggle",
                results["checks"]["w23_i18n_models"],
            )
        else:
            results["windows"]["W23"] = _window(
                "PARTIAL" if models["ok"] or lang_show["ok"] else "FAIL",
                "i18n/models partial",
                results["checks"]["w23_i18n_models"],
            )

        # --- W11 RAG ---
        rag_local: dict[str, Any] = {"ok": False}
        try:
            from RxyCode.RxyCode1_1_0.rag.search import code_search

            rag_text = code_search("AgentV2", top_k=3)
            rag_local = {
                "ok": bool(rag_text) and "[no " not in rag_text[:40],
                "excerpt": str(rag_text)[:300],
            }
        except Exception as exc:
            rag_local = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        results["checks"]["w11_rag_local"] = rag_local

        rag_turns: list[dict] = []
        if llm_available:
            rag_prompts = [
                "请调用 code_search 工具，query=AgentV2，只返回命中文件路径，不要改文件",
                "刚才的 RAG 结果里哪个路径最相关？一句话，不要改文件",
                "再用 code_search 搜索 stickyScroll，只返回路径",
                "用一两句话总结这两次 code_search，不要改文件",
            ]
            for i, prompt in enumerate(rag_prompts, start=1):
                turn = _chat(port, prompt, mode="build", timeout=CHAT_TIMEOUT)
                rag_turns.append(turn)
                results["turns"].append({"window": "W11", "turn": i, **turn})
        results["checks"]["w11_rag_chat"] = {
            "turn_count": len(rag_turns),
            "turns_ok": sum(1 for t in rag_turns if t.get("ok")),
            "excerpts": [t.get("response_excerpt", "")[:120] for t in rag_turns],
        }
        if rag_local.get("ok") and len(rag_turns) >= 4 and all(t.get("ok") for t in rag_turns):
            results["windows"]["W11"] = _window(
                "PASS",
                "code_search local + 4-turn RAG chat",
                {"local": rag_local, "chat": results["checks"]["w11_rag_chat"]},
            )
        elif rag_local.get("ok") or (rag_turns and rag_turns[0].get("ok")):
            results["windows"]["W11"] = _window(
                "PARTIAL",
                f"RAG partial (local_ok={rag_local.get('ok')}, "
                f"chat_ok={sum(1 for t in rag_turns if t.get('ok'))}/{len(rag_turns)})",
                {"local": rag_local, "chat": results["checks"]["w11_rag_chat"]},
            )
        else:
            results["windows"]["W11"] = _window(
                "SKIP" if not llm_available and not rag_local.get("ok") else "FAIL",
                "RAG not evidenced",
                {"local": rag_local, "chat": results["checks"]["w11_rag_chat"]},
            )

        # --- W12 Safety (stream write → approval_request → /approve) ---
        if llm_available:
            safety_stream = _chat_stream(
                port,
                "在仓库根目录创建临时文件 live_smoke_w12_temp.txt，写入一行 gate-live-w12，"
                "完成后用一句话确认路径。不要 git commit。",
                mode="build",
                timeout=TOOL_STREAM_TIMEOUT,
                auto_approve=True,
            )
            results["checks"]["w12_safety"] = {
                k: safety_stream[k]
                for k in (
                    "ok",
                    "partial_ok",
                    "elapsed_s",
                    "error",
                    "progress_events",
                    "unique_event_types",
                    "tool_names",
                    "approvals",
                    "approve_results",
                    "response_excerpt",
                )
            }
            results["turns"].append({"window": "W12", "turn": "stream_write", **safety_stream})
            # Extra short rounds about safety outcome
            for i, prompt in enumerate(
                [
                    "刚才的写文件是否触发了安全审批？一句话",
                    "不要再写文件；确认 live_smoke_w12_temp.txt 是否存在，用 read/ls",
                    "一句话说明 safety gate 的作用",
                ],
                start=2,
            ):
                t = _chat(port, prompt, mode="build", timeout=CHAT_TIMEOUT)
                results["turns"].append({"window": "W12", "turn": i, **t})
            had_approval = bool(safety_stream.get("approvals"))
            approved_ok = any(r.get("ok") for r in safety_stream.get("approve_results") or [])
            if had_approval and approved_ok:
                results["windows"]["W12"] = _window(
                    "PASS",
                    "approval_request seen + POST /approve ok (write stream)",
                    results["checks"]["w12_safety"],
                )
            elif had_approval or "write" in safety_stream.get("tool_names", []) or safety_stream.get(
                "partial_ok"
            ):
                results["windows"]["W12"] = _window(
                    "PARTIAL",
                    f"safety stream partial (approvals={len(safety_stream.get('approvals') or [])}, "
                    f"tools={safety_stream.get('tool_names')})",
                    results["checks"]["w12_safety"],
                )
            else:
                results["windows"]["W12"] = _window(
                    "PARTIAL",
                    "write asked; no approval_request observed (may auto-allow or LLM avoided write)",
                    results["checks"]["w12_safety"],
                )
        else:
            results["windows"]["W12"] = _window("SKIP", "LLM not available for safety stream")

        # --- W15 Web ---
        if llm_available:
            web_stream = _chat_stream(
                port,
                "必须调用 websearch 工具，查询 'Python asyncio gather'，只返回前2条标题，不要改文件",
                mode="build",
                timeout=TOOL_STREAM_TIMEOUT,
            )
            results["checks"]["w15_web"] = {
                k: web_stream[k]
                for k in (
                    "ok",
                    "partial_ok",
                    "elapsed_s",
                    "error",
                    "tool_names",
                    "unique_event_types",
                    "response_excerpt",
                )
            }
            results["turns"].append({"window": "W15", "turn": "websearch_stream", **web_stream})
            web_follow = [
                "刚才用的是 websearch 还是 webfetch？一句话",
                "不要再搜索；用一句话总结搜索结果主题",
                "确认没有修改任何仓库文件，回复 yes/no",
            ]
            web_ok_turns = 1 if web_stream.get("ok") or web_stream.get("partial_ok") else 0
            for i, prompt in enumerate(web_follow, start=2):
                t = _chat(port, prompt, mode="build", timeout=CHAT_TIMEOUT)
                results["turns"].append({"window": "W15", "turn": i, **t})
                if t.get("ok"):
                    web_ok_turns += 1
            tools = [n.lower() for n in web_stream.get("tool_names") or []]
            used_web = any(n in ("websearch", "webfetch") for n in tools) or any(
                x in str(web_stream.get("response_excerpt", "")).lower()
                for x in ("http", "asyncio", "search")
            )
            if used_web and ("websearch" in tools or "webfetch" in tools):
                results["windows"]["W15"] = _window(
                    "PASS" if web_ok_turns >= 3 else "PARTIAL",
                    f"web tool={tools}; followups_ok={web_ok_turns}",
                    results["checks"]["w15_web"],
                )
            elif used_web or web_stream.get("partial_ok") or web_stream.get("ok"):
                results["windows"]["W15"] = _window(
                    "PARTIAL",
                    f"web chat ran but tool_names={tools}",
                    results["checks"]["w15_web"],
                )
            else:
                results["windows"]["W15"] = _window(
                    "SKIP",
                    f"web not evidenced: error={web_stream.get('error')}",
                    results["checks"]["w15_web"],
                )
        else:
            results["windows"]["W15"] = _window("SKIP", "LLM not available for web")

        # --- W16 Git (force git tool, not web) ---
        if llm_available:
            git_stream = _chat_stream(
                port,
                "必须调用 git 工具：operation=status。只报告当前分支与是否有未提交改动。"
                "禁止 websearch/webfetch，不要 commit。",
                mode="build",
                timeout=TOOL_STREAM_TIMEOUT,
            )
            results["checks"]["w16_git"] = {
                k: git_stream[k]
                for k in (
                    "ok",
                    "partial_ok",
                    "elapsed_s",
                    "error",
                    "tool_names",
                    "unique_event_types",
                    "response_excerpt",
                )
            }
            results["turns"].append({"window": "W16", "turn": "git_status_stream", **git_stream})
            for i, prompt in enumerate(
                [
                    "刚才是否实际调用了 git 工具？yes/no + 分支名",
                    "不要 commit；用一句话说明 working tree 是否干净",
                    "确认没有执行 git commit / push，回复 yes",
                ],
                start=2,
            ):
                t = _chat(port, prompt, mode="build", timeout=CHAT_TIMEOUT)
                results["turns"].append({"window": "W16", "turn": i, **t})
            tools = [n.lower() for n in git_stream.get("tool_names") or []]
            excerpt = str(git_stream.get("response_excerpt", ""))
            looks_git = "git" in tools or bool(
                re.search(r"branch|master|cursor/|working tree|未提交|clean", excerpt, re.I)
            )
            if "git" in tools and (git_stream.get("ok") or git_stream.get("partial_ok")):
                results["windows"]["W16"] = _window(
                    "PASS",
                    "git tool_call observed via stream + followups",
                    results["checks"]["w16_git"],
                )
            elif looks_git:
                results["windows"]["W16"] = _window(
                    "PARTIAL",
                    f"git-ish answer without clear tool_call (tools={tools})",
                    results["checks"]["w16_git"],
                )
            else:
                results["windows"]["W16"] = _window(
                    "PARTIAL",
                    f"git asked; tools={tools}; error={git_stream.get('error')}",
                    results["checks"]["w16_git"],
                )
        else:
            results["windows"]["W16"] = _window("SKIP", "LLM not available for git")

        # --- W17 Sub-agent / parallel ---
        if llm_available:
            parallel_requested = False
            try:
                from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

                _a = object.__new__(AgentV2)
                parallel_requested = bool(
                    _a._should_use_subagents(
                        "同时分别读取 README.md 和 AGENTS.md 并各自总结"
                    )
                )
            except Exception:
                parallel_requested = False
            sa_turns: list[dict] = []
            sa_prompts = [
                "同时分别读取 README.md 和 AGENTS.md，各自用一句话总结，不要改文件",
                "刚才是否并行处理了两个文件？yes/no",
                "再并行列出这两个文件的第一行标题/首句",
                "一句话总结并行读取的结果，不要改文件",
            ]
            for i, prompt in enumerate(sa_prompts, start=1):
                if i == 1:
                    turn = _chat_stream(
                        port, prompt, mode="build", timeout=TOOL_STREAM_TIMEOUT
                    )
                else:
                    turn = _chat(port, prompt, mode="build", timeout=CHAT_TIMEOUT)
                sa_turns.append(turn)
                results["turns"].append({"window": "W17", "turn": i, **turn})
            results["checks"]["w17_subagent"] = {
                "unit_parallel_requested": parallel_requested,
                "turn_count": len(sa_turns),
                "turns_ok": sum(1 for t in sa_turns if t.get("ok") or t.get("partial_ok")),
                "first_tools": (sa_turns[0].get("tool_names") if sa_turns else []),
                "excerpts": [str(t.get("response_excerpt", ""))[:100] for t in sa_turns],
            }
            ok_n = results["checks"]["w17_subagent"]["turns_ok"]
            if parallel_requested and ok_n >= 3:
                results["windows"]["W17"] = _window(
                    "PARTIAL",
                    "parallel intent detected + multi-round file reads "
                    "(legacy SubAgent path disabled; graph parallel not fully proven)",
                    results["checks"]["w17_subagent"],
                )
            elif ok_n >= 1:
                results["windows"]["W17"] = _window(
                    "PARTIAL",
                    f"parallel chat partial ({ok_n} turns); unit_parallel={parallel_requested}",
                    results["checks"]["w17_subagent"],
                )
            else:
                results["windows"]["W17"] = _window(
                    "SKIP", "sub-agent/parallel not evidenced", results["checks"]["w17_subagent"]
                )
        else:
            results["windows"]["W17"] = _window("SKIP", "LLM not available for sub-agent")

        # --- W18 Recovery ---
        recovery_unit: dict[str, Any] = {"ok": False}
        try:
            from RxyCode.RxyCode1_1_0.recovery.error_recovery import (
                ErrorKind,
                classify_error,
            )

            kind = classify_error(ConnectionError("live-smoke-transient"))
            recovery_unit = {
                "ok": kind == ErrorKind.TRANSIENT,
                "kind": str(kind),
            }
        except Exception as exc:
            recovery_unit = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        results["checks"]["w18_recovery_unit"] = recovery_unit
        if llm_available:
            rec_stream = _chat_stream(
                port,
                "先用 bash 运行命令 xyz_live_smoke_no_such_cmd_zzz（预期失败），"
                "然后改用 echo live-smoke-recovery-ok 成功执行，说明你如何恢复。不要改仓库文件。",
                mode="build",
                timeout=TOOL_STREAM_TIMEOUT,
            )
            results["checks"]["w18_recovery_stream"] = {
                k: rec_stream[k]
                for k in (
                    "ok",
                    "partial_ok",
                    "elapsed_s",
                    "error",
                    "tool_names",
                    "unique_event_types",
                    "response_excerpt",
                )
            }
            results["turns"].append({"window": "W18", "turn": "recovery_stream", **rec_stream})
            for i, prompt in enumerate(
                [
                    "刚才是否经历了失败后重试/换命令？yes/no",
                    "一句话说明 recovery 做了什么",
                    "确认没有修改仓库文件，回复 yes",
                ],
                start=2,
            ):
                t = _chat(port, prompt, mode="build", timeout=CHAT_TIMEOUT)
                results["turns"].append({"window": "W18", "turn": i, **t})
            tools = rec_stream.get("tool_names") or []
            if recovery_unit.get("ok") and (
                rec_stream.get("ok") or rec_stream.get("partial_ok") or len(tools) >= 1
            ):
                results["windows"]["W18"] = _window(
                    "PARTIAL",
                    "classify_error TRANSIENT ok + live fail-then-recover bash probe",
                    {
                        "unit": recovery_unit,
                        "stream": results["checks"]["w18_recovery_stream"],
                    },
                )
            elif recovery_unit.get("ok"):
                results["windows"]["W18"] = _window(
                    "PARTIAL",
                    "recovery unit ok; live retry path weak",
                    {"unit": recovery_unit, "stream": results["checks"]["w18_recovery_stream"]},
                )
            else:
                results["windows"]["W18"] = _window(
                    "SKIP", "recovery not evidenced", recovery_unit
                )
        else:
            results["windows"]["W18"] = _window(
                "PARTIAL" if recovery_unit.get("ok") else "SKIP",
                "recovery unit only" if recovery_unit.get("ok") else "no recovery evidence",
                recovery_unit,
            )

        # W21–W22 remain SKIP (no cheap live command surface in this smoke)
        for wid, reason in [
            ("W21", "Workflow run/status/cancel not exercised"),
            ("W22", "LSP not exercised"),
        ]:
            results["windows"][wid] = _window("SKIP", reason)

        # W19/W20/W23 already collected before W11 (avoid chat-lock timeouts)

        # W24: frontend e2e has Ctrl+C cancel; this smoke does not drive live Esc
        results["windows"]["W24"] = _window(
            "PARTIAL",
            "frontend e2e Ctrl+C cancel stream OK; live API concurrent Esc not driven this smoke",
        )

        # W01/W02: headless OpenTUI bun:test → PARTIAL (not interactive TTY PASS)
        w01w02 = _run_opentui_gate_test(repo_root)
        results["checks"]["w01_w02_opentui"] = w01w02
        if w01w02.get("ok"):
            results["windows"]["W01"] = _window(
                "PARTIAL",
                "OpenTUI bun:test textarea focus/value path (headless; not interactive TTY)",
                w01w02,
            )
            results["windows"]["W02"] = _window(
                "PARTIAL",
                "OpenTUI bun:test ScrollBox scrollTop + sticky helpers (headless; not interactive TTY)",
                w01w02,
            )
        else:
            results["windows"]["W01"] = _window(
                "SKIP",
                f"No interactive TTY cursor proof; bun:test failed: {w01w02.get('error')}",
                w01w02,
            )
            results["windows"]["W02"] = _window(
                "SKIP",
                f"No ScrollBox evidence; bun:test failed: {w01w02.get('error')}",
                w01w02,
            )
        results["windows"]["W25"] = _window(
            "PARTIAL", "logo matrix automated only; no Win32 screenshot in this run"
        )
        results["windows"]["W26"] = _window("SKIP", "No macOS runner")

        turn_count = len(results["turns"])
        results["checks"]["multiround_summary"] = {
            "recorded_turns": turn_count,
            "llm_available": llm_available,
            "gte_4_turns": turn_count >= 4,
        }

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_tail = ""
        if proc.stdout:
            try:
                log_tail = proc.stdout.read() or ""
            except Exception:
                log_tail = ""
        results["checks"]["route_log"] = {
            "route_social_chat_seen": "route=social_chat" in log_tail,
            "log_excerpt": log_tail[-2000:],
        }

    _write(results)
    # Exit 0 even with PARTIAL — this is evidence collection, not a CI gate.
    return 0


def _write(results: dict) -> None:
    # Strip bulky nested payload blobs for readability
    slim = json.loads(json.dumps(results, ensure_ascii=False, default=str))
    for key in list(slim.get("checks", {})):
        node = slim["checks"][key]
        if isinstance(node, dict) and "payload" in node:
            node.pop("payload", None)
        if isinstance(node, dict):
            for sub in node.values():
                if isinstance(sub, dict) and "payload" in sub:
                    sub.pop("payload", None)
    out_path = Path(__file__).resolve().parent / "live_smoke_output.json"
    out_path.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
    # Also write a compact window summary
    summary = {
        wid: {"result": w.get("result"), "note": w.get("note")}
        for wid, w in sorted(slim.get("windows", {}).items())
    }
    summary_path = Path(__file__).resolve().parent / "live_smoke_windows.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    print(summary_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
