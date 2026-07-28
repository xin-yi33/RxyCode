"""Focused GateLive helpers for W06–W09, W21–W26 (imported by live_smoke_runner)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

CACHE_QUESTION = (
    "LIVE_SMOKE_CACHE_GATE_2026-07-28: 只回答数字，2+2等于几？不要解释。"
)
W09_PREFIX = (
    "LIVE_SMOKE_PROVIDER_PREFIX_2026-07-28: 你是 RxyCode 助手。"
    "以下背景保持不变：RxyCode 是 Python+LangGraph 编码助手，支持 plan/build/compose、"
    "工具编排、双级缓存与安全门禁。"
)
W09_SUFFIXES = [
    " 用一句话说明 plan 模式。",
    " 用一句话说明 build 模式。",
    " 用一句话说明 compose 模式。",
    " 用一句话说明 safety gate。",
]


def chat_with_session(
    port: int,
    message: str,
    *,
    token: str,
    session_id: str,
    mode: str = "build",
    timeout: float = 90.0,
) -> dict:
    t0 = time.monotonic()
    code, body, err = _request(
        port,
        "POST",
        "/chat",
        {"message": message, "mode": mode, "session_id": session_id},
        token=token,
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
        "session_id": session_id,
        "status_code": code,
        "elapsed_s": elapsed,
        "error": err or payload.get("error"),
        "response_excerpt": combined[:500],
        "ok": code == 200 and not err and not payload.get("error"),
    }


def fetch_status(port: int, token: str) -> dict:
    code, body, _ = _request(port, "GET", "/status", token=token, timeout=10.0)
    if code != 200:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


def cancel_active(port: int, token: str) -> dict:
    code, body, err = _request(port, "POST", "/cancel", token=token, timeout=10.0)
    payload: dict[str, Any] = {}
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body[:200]}
    return {
        "status_code": code,
        "error": err,
        "ok": code == 200 and not err,
        "payload": payload,
        "cancelled": bool(payload.get("cancelled")),
    }


def chat_stream_cancel_probe(
    port: int,
    message: str,
    *,
    token: str,
    session_id: str,
    cancel_after_events: int = 2,
    stream_timeout: float = 45.0,
) -> dict:
    """Start /chat/stream, POST /cancel after progress, collect SSE evidence."""
    url = f"http://127.0.0.1:{port}/chat/stream"
    data = json.dumps(
        {"message": message, "mode": "build", "session_id": session_id}
    ).encode("utf-8")
    result: dict[str, Any] = {
        "message": message,
        "event_types": [],
        "cancel_response": None,
        "error": None,
        "cancelled_seen": False,
        "progress_before_cancel": 0,
    }
    done = threading.Event()

    def worker() -> None:
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=stream_timeout) as resp:
                buf = ""
                while not done.is_set():
                    chunk = resp.read(2048)
                    if not chunk:
                        break
                    buf += chunk.decode("utf-8", errors="replace")
                    while "\n\n" in buf:
                        block, buf = buf.split("\n\n", 1)
                        for line in block.splitlines():
                            if not line.startswith("data:"):
                                continue
                            try:
                                ev = json.loads(line[5:].strip())
                            except json.JSONDecodeError:
                                continue
                            et = str(ev.get("type", ""))
                            result["event_types"].append(et)
                            if et in ("progress", "tool_start", "tool_call", "token", "content"):
                                result["progress_before_cancel"] += 1
                            if et in ("done", "error", "final"):
                                done.set()
                                break
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True)
    t0 = time.monotonic()
    t.start()
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if result["progress_before_cancel"] >= cancel_after_events:
            break
        if done.is_set():
            break
        time.sleep(0.15)
    result["cancel_response"] = cancel_active(port, token)
    done.wait(timeout=stream_timeout)
    t.join(timeout=5.0)
    result["elapsed_s"] = round(time.monotonic() - t0, 3)
    result["cancelled_seen"] = bool(
        result["cancel_response"].get("cancelled")
        or "cancelled" in str(result["cancel_response"].get("payload", {})).lower()
        or "cancel" in " ".join(result["event_types"]).lower()
    )
    result["ok"] = result["cancelled_seen"] and result["progress_before_cancel"] > 0
    return result


def run_workflow_probe() -> dict:
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    run_id = "live-smoke-w21"
    script = "print('live-smoke-w21-ok')"
    try:
        run_out = workflow.manage_workflow("run", script=script, run_id=run_id)
        status_out = workflow.manage_workflow("status", run_id=run_id)
        wait_out = workflow.manage_workflow("wait", run_id=run_id)
        cancel_out = workflow.manage_workflow("cancel", run_id=run_id)
        status_after = json.loads(status_out) if status_out.strip().startswith("{") else {}
        return {
            "ok": "completed" in str(wait_out).lower() or status_after.get("status") == "completed",
            "run_excerpt": str(run_out)[:200],
            "status": status_out[:300],
            "wait": wait_out[:300],
            "cancel": cancel_out[:300],
            "turns": 4,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def run_diagnostics_probe(repo_root: Path) -> dict:
    from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics

    sample = repo_root / "scripts" / ".live_smoke_diag_sample.py"
    sample.write_text("def broken(\n    pass\n", encoding="utf-8")
    try:
        result = run_diagnostics(str(sample))
        ok = "error" in result.lower() or "syntax" in result.lower()
        return {"ok": ok, "excerpt": result[:400], "file": str(sample)}
    finally:
        sample.unlink(missing_ok=True)


def run_parallel_unit_test(repo_root: Path) -> dict:
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_core/test_parallel_executor.py",
                "-q",
                "--tb=no",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        passed = proc.returncode == 0 and "passed" in out.lower()
        return {
            "ok": passed,
            "returncode": proc.returncode,
            "excerpt": out[-600:],
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def run_logo_dump(repo_root: Path, desktop: Path | None = None) -> dict:
    frontend = repo_root / "frontend"
    script = frontend / "scripts" / "render_logo_dump.ts"
    targets = [
        repo_root / "scripts" / "live_smoke_w25_logo_dump.txt",
    ]
    if desktop is not None:
        targets.append(desktop / "RxyCode-win32-logo-dump-2026-07-28.txt")
    try:
        proc = subprocess.run(
            ["npx", "tsx", str(script), *[str(t) for t in targets]],
            cwd=str(frontend),
            capture_output=True,
            text=True,
            timeout=60,
            shell=True,
        )
        written = [str(t) for t in targets if t.exists()]
        return {
            "ok": proc.returncode == 0 and bool(written),
            "returncode": proc.returncode,
            "written": written,
            "excerpt": (proc.stdout or "")[-400:] + (proc.stderr or "")[-200:],
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def run_mac_width_tests(repo_root: Path) -> dict:
    frontend = repo_root / "frontend"
    try:
        proc = subprocess.run(
            ["npx", "vitest", "run", "tests/logo.mac-width.test.ts"],
            cwd=str(frontend),
            capture_output=True,
            text=True,
            timeout=120,
            shell=True,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return {
            "ok": proc.returncode == 0 and "pass" in out.lower(),
            "returncode": proc.returncode,
            "excerpt": out[-800:],
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def w08_cache_retest(
    port: int,
    *,
    token: str,
    chat_fn: Callable[..., dict],
    status_before: dict,
) -> dict:
    s1 = "live-smoke-cache-a"
    s2 = "live-smoke-cache-b"
    first = chat_fn(port, CACHE_QUESTION, session_id=s1, mode="build")
    second = chat_fn(port, CACHE_QUESTION, session_id=s2, mode="build")
    status_after = fetch_status(port, token)
    app_before = (status_before.get("application_cache") or {}).get("precise", {})
    app_after = (status_after.get("application_cache") or {}).get("precise", {})
    hits_delta = int(app_after.get("hits", 0) or 0) - int(app_before.get("hits", 0) or 0)
    provider = status_after.get("provider_cache") or {}
    return {
        "first_ok": first.get("ok"),
        "second_ok": second.get("ok"),
        "hits_delta": hits_delta,
        "precise_after": app_after,
        "provider_cache": provider,
        "cache_rate": status_after.get("cache_rate"),
        # App precise hits OR Provider StatusBar rate both prove dual-track works.
        "ok": bool(
            first.get("ok")
            and second.get("ok")
            and (
                hits_delta >= 1
                or float(str(status_after.get("cache_rate") or "0").replace("%", "") or 0)
                >= 85.0
                or int(provider.get("hit_tokens") or 0) > 0
            )
        ),
    }


def w09_provider_warmup(
    port: int,
    *,
    token: str,
    chat_fn: Callable[..., dict],
    session_id: str = "live-smoke-w09",
) -> dict:
    turns: list[dict] = []
    for suffix in W09_SUFFIXES:
        turn = chat_fn(
            port,
            W09_PREFIX + suffix,
            session_id=session_id,
            mode="build",
            timeout=90.0,
        )
        turns.append(turn)
    status = fetch_status(port, token)
    evaluated = evaluate_w09(status, turns)
    return {"turns": turns, "turn_count": len(turns), "status": status, **evaluated}


def evaluate_w09(status_json: dict, warmup_turns: list[dict]) -> dict:
    provider = status_json.get("provider_cache") or {}
    hit_tokens = int(provider.get("hit_tokens") or 0)
    prompt_tokens = int(provider.get("prompt_tokens") or 0)
    rate_raw = str(status_json.get("cache_rate") or "0")
    try:
        rate_val = float(str(rate_raw).replace("%", "").strip() or 0)
    except ValueError:
        rate_val = 0.0
    ratio = (hit_tokens / prompt_tokens) if prompt_tokens > 0 else 0.0
    ok = rate_val >= 85.0 or ratio >= 0.85
    return {
        "ok": ok,
        "cache_rate": rate_raw,
        "hit_tokens": hit_tokens,
        "prompt_tokens": prompt_tokens,
        "ratio": round(ratio, 4),
        "turns_ok": sum(1 for t in warmup_turns if t.get("ok")),
    }


def _request(
    port: int,
    method: str,
    path: str,
    body: dict | None = None,
    *,
    token: str,
    timeout: float = 30.0,
) -> tuple[int, str, str | None]:
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace"), None
    except Exception as exc:
        return 0, "", f"{type(exc).__name__}: {exc}"
