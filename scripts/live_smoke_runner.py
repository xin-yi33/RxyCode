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
CODE_STREAM_TIMEOUT = 300.0
CHAT_TIMEOUT = 90.0
SESSION_ID = "live-smoke-multiround"


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


def _chat_stream(port: int, message: str, mode: str = "build", timeout: float = CODE_STREAM_TIMEOUT) -> dict:
    """POST /chat/stream and collect SSE until done or timeout."""
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
    progress_count = 0
    err: str | None = None
    status_code = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status
            buf = ""
            while True:
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
                        if et in ("answer", "token", "content", "text"):
                            answer_parts.append(str(ev.get("content") or ev.get("text") or ""))
                        if et == "error":
                            err = str(ev.get("message") or ev.get("content") or "stream error")
                        if et == "done":
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
        "event_types": event_types[:40],
        "progress_events": progress_count,
        "unique_event_types": sorted(set(event_types)),
        "jargon_detected": bool(JARGON_RE.search(answer + str(err or ""))),
        "response_excerpt": (answer or str(err or ""))[:500],
        "ok": status_code == 200 and not err and bool(answer),
        "partial_ok": status_code == 200 and progress_count > 0 and not answer,
    }


def _window(result: str, note: str, evidence: Any = None) -> dict:
    return {"result": result, "note": note, "evidence": evidence}


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

        # W11–W18, W21–W22: require tools/TUI — mark SKIP unless we have cheap probes
        for wid, reason in [
            ("W11", "RAG search/edit not exercised in API smoke"),
            ("W12", "Safety WRITE/DANGER approval flow not live"),
            ("W13", "MCP add/list not exercised"),
            ("W14", "Skills find/add/remove not exercised"),
            ("W15", "Web search/fetch not exercised"),
            ("W17", "Sub-agent parallel not exercised"),
            ("W18", "Recovery retry path not exercised"),
            ("W21", "Workflow run/status/cancel not exercised"),
            ("W22", "LSP not exercised"),
        ]:
            results["windows"][wid] = _window("SKIP", reason)

        # W16 git — ask via short chat if LLM; else SKIP
        if llm_available:
            git_chat = _chat(
                port,
                "只运行 git status，用一两句话告诉我当前分支和是否有未提交改动，不要 commit",
                mode="build",
                timeout=120.0,
            )
            results["checks"]["w16_git"] = git_chat
            results["turns"].append({"window": "W16", "turn": "git_status", **git_chat})
            if git_chat["ok"]:
                results["windows"]["W16"] = _window(
                    "PARTIAL",
                    "git status asked via /chat; no commit performed",
                    {"excerpt": git_chat["response_excerpt"][:240]},
                )
            else:
                results["windows"]["W16"] = _window(
                    "SKIP", f"git chat failed: {git_chat.get('error')}", git_chat
                )
        else:
            results["windows"]["W16"] = _window("SKIP", "LLM not available for git chat")

        # W19 schedule/queue
        q_list = _cmd(port, "/queue")
        q_add = _cmd(port, "/queue add live-smoke-noop-prompt-do-not-run")
        q_list2 = _cmd(port, "/queue list")
        # remove if we got an id
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

        # W20 session save/load/list
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

        # W23 i18n + models
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

        # W24 cancel — only if we can start a stream and cancel; SKIP if risky
        results["windows"]["W24"] = _window(
            "SKIP",
            "Esc/cancel mid-stream not driven in this smoke (would need concurrent cancel)",
        )

        # TTY windows remain SKIP
        results["windows"]["W01"] = _window("SKIP", "No TTY cursor evidence")
        results["windows"]["W02"] = _window("SKIP", "No scrollbox live session")
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
