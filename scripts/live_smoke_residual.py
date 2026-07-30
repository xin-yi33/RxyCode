#!/usr/bin/env python3
"""Resume remaining closer windows after hang kill. Prints each turn; 45s timeouts."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from live_smoke_gates import (  # noqa: E402
    chat_stream_cancel_probe,
    chat_with_session,
    fetch_status,
    w08_cache_retest,
)

TOKEN = "live-smoke-rxycode-token-32chars-minimum!!"
LOG = ROOT / "scripts" / "live_smoke_residual.log"
OUT = ROOT / "scripts" / "live_smoke_closer_out.json"


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_api(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["RXYCODE_API_TOKEN"] = TOKEN
    code = (
        "from RxyCode.RxyCode1_1_0.api_server import run_api_server; "
        f"run_api_server(port={port}, token={TOKEN!r})"
    )
    return subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_ready(port: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fetch_status(port, TOKEN).get("model"):
            return True
        time.sleep(0.4)
    return False


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    windows: dict = {}
    # seed from prior closer log successes
    prior = {
        "W06": {"result": "PASS", "note": "build multi-round ok=3/4"},
        "W09": {"result": "PASS", "note": "rate=95.6% ratio=0.9564"},
        "W21": {"result": "PASS", "note": "workflow"},
        "W22": {"result": "PASS", "note": "diagnostics"},
        "W17": {"result": "PASS", "note": "parallel"},
        "W25": {"result": "PASS", "note": "logo dump"},
        "W26": {"result": "PASS", "note": "mac width"},
    }
    windows.update(prior)

    port = free_port()
    log(f"start api :{port}")
    proc = start_api(port)
    try:
        if not wait_ready(port, 60):
            log("API not ready")
            return 1

        def chat(p, msg, session_id="s", mode="build", timeout=45.0):
            log(f"chat begin {session_id} {msg[:40]!r}")
            r = chat_with_session(
                p, msg, token=TOKEN, session_id=session_id, mode=mode, timeout=timeout
            )
            log(f"chat end {session_id} ok={r.get('ok')} err={r.get('error')}")
            return r

        status0 = fetch_status(port, TOKEN)
        w08 = w08_cache_retest(port, token=TOKEN, chat_fn=chat, status_before=status0)
        windows["W08"] = {
            "result": "PASS" if w08.get("ok") else "PARTIAL",
            "note": f"hits_delta={w08.get('hits_delta')} cache_rate={w08.get('cache_rate')}",
        }
        log(f"W08 {windows['W08']}")

        turns7 = []
        for i, msg in enumerate(
            [
                "规划：做一个倒计时 CLI 的步骤",
                "根据刚才计划，列出要改的文件",
                "风险是什么",
                "一句话总结计划",
            ]
        ):
            turns7.append(chat(port, msg, session_id="w07", mode="compose", timeout=45))
            log(f"W07 turn {i+1} ok={turns7[-1].get('ok')}")
        ok7 = sum(1 for t in turns7 if t.get("ok")) >= 3
        windows["W07"] = {
            "result": "PASS" if ok7 else "PARTIAL",
            "note": f"compose multi-round ok={sum(1 for t in turns7 if t.get('ok'))}/4",
        }
        log(f"W07 {windows['W07']}")

        g = chat(
            port,
            "必须调用 git 工具，operation=status，不要用 websearch",
            session_id="w16",
            timeout=50,
        )
        windows["W16"] = {
            "result": "PASS" if g.get("ok") else "PARTIAL",
            "note": (g.get("response_excerpt") or g.get("error") or "")[:160],
        }
        log(f"W16 {windows['W16']}")

        bad = chat(
            port,
            "读取一个肯定不存在的文件路径 Z:/no/such/rxycode_live_smoke_missing.txt 然后用人话说明失败原因",
            session_id="w18",
            timeout=50,
        )
        jargon = any(
            x in (bad.get("response_excerpt") or "").lower()
            for x in ("synthesizer", "grounded claims", "build incomplete")
        )
        windows["W18"] = {
            "result": "PASS" if bad.get("ok") and not jargon else "PARTIAL",
            "note": (bad.get("response_excerpt") or bad.get("error") or "")[:160],
        }
        log(f"W18 {windows['W18']}")

        c = chat_stream_cancel_probe(
            port,
            "慢慢分析这个仓库结构，尽量多说步骤",
            token=TOKEN,
            session_id="w24",
            cancel_after_events=1,
            stream_timeout=35,
        )
        windows["W24"] = {
            "result": "PASS" if c.get("ok") else "PARTIAL",
            "note": f"progress={c.get('progress_before_cancel')} cancelled={c.get('cancelled_seen')}",
        }
        log(f"W24 {windows['W24']}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
        log("api stopped")

    # merge with windows.json
    win_path = ROOT / "scripts" / "live_smoke_windows.json"
    existing = {}
    if win_path.exists():
        existing = json.loads(win_path.read_text(encoding="utf-8"))
    existing.update(windows)
    win_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT.write_text(json.dumps({"windows": existing}, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"wrote {OUT}")
    partial = [k for k, v in existing.items() if v.get("result") == "PARTIAL"]
    log(f"PARTIAL left: {partial}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
