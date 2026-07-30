#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase 1: Non-LLM tests (health, commands, memory, frontend)."""

import subprocess, sys, os, time, json, socket
import urllib.request as ur

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOST = "127.0.0.1"
PORT = 8770
BASE = f"http://{HOST}:{PORT}"
PROJECT_ROOT = r"d:\agent-demo\RxyCode\RxyCode1_1_0"
PARENT_ROOT = r"d:\agent-demo\RxyCode"
results = []

def G(name, passed, detail=""):
    s = "PASS" if passed else "FAIL"
    results.append({"name": name, "passed": passed})
    print(f"  [{s}] {name}")
    if not passed and detail:
        print(f"         {detail[:200]}")

def get(path):
    try:
        r = ur.urlopen(f"{BASE}{path}", timeout=10)
        return r.status, json.loads(r.read().decode())
    except Exception as e:
        return 0, {"error": str(e)}

def post(path, data):
    try:
        body = json.dumps(data).encode()
        req = ur.Request(f"{BASE}{path}", data=body, headers={"Content-Type": "application/json"})
        r = ur.urlopen(req, timeout=10)
        return r.status, json.loads(r.read().decode())
    except Exception as e:
        return 0, {"error": str(e)}

# Start server
print("Starting API server...")
env = os.environ.copy()
env["PYTHONPATH"] = PARENT_ROOT
proc = subprocess.Popen(
    [sys.executable, "-m", "RxyCode.RxyCode1_1_0.main", "--api", "--api-port", str(PORT)],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=PROJECT_ROOT,
)
print(f"  PID={proc.pid}")

# Wait for ready
ready = False
for i in range(30):
    time.sleep(1)
    if proc.poll() is not None:
        out = proc.stdout.read(2048).decode(errors="replace")
        print(f"  Server exited early! code={proc.returncode}")
        print(f"  Output: {out[:500]}")
        break
    try:
        r = ur.urlopen(f"{BASE}/status", timeout=2)
        if r.status == 200:
            body = json.loads(r.read().decode())
            if body.get("model") != "unknown":
                print(f"  Server ready! model={body.get('model')}")
                ready = True
                break
    except:
        pass

if not ready:
    print("Server not ready, trying anyway...")
    try:
        r = ur.urlopen(f"{BASE}/status", timeout=2)
        ready = r.status == 200
    except:
        pass

if ready:
    # ── 1. Health Check ──
    print("\n=== 1. Health Check ===")
    s, b = get("/status")
    has_fields = all(k in b for k in ["memory_mb", "model", "mode", "language"]) if s == 200 else False
    G("/status returns 200 + correct fields", s == 200 and has_fields, f"status={s}")
    if has_fields:
        print(f"      model={b.get('model')}, mode={b.get('mode')}, lang={b.get('language')}")

    s, b = get("/models")
    has_model = s == 200 and len(b.get("models", [])) > 0 if isinstance(b, dict) else False
    G("/models returns configured model", has_model, f"status={s}")
    if has_model:
        print(f"      models={[m['id'] for m in b.get('models',[])]}, active={b.get('active')}")

    # ── 2. Slash Commands ──
    print("\n=== 2. Slash Commands ===")
    s, b = post("/command", {"command": "/help"})
    G("/help returns help text", s == 200 and "help" in b.get("message", "").lower() or "help" in b.get("action", "").lower(), f"status={s}")

    s, b = post("/command", {"command": "/clear"})
    G("/clear clears context", s == 200 and "cleared" in b.get("action", ""), f"status={s}")

    s, b = post("/command", {"command": "/cache"})
    G("/cache cache stats", s == 200 and "Cache" in b.get("message", ""), f"status={s}")

    s, b = post("/command", {"command": "/memory list"})
    G("/memory list", s == 200, f"status={s}")

    s, b = post("/command", {"command": "/language en"})
    G("/language en switch", s == 200 and "English" in b.get("message", ""), f"status={s}")
    post("/command", {"command": "/language zh"})

    s, b = post("/command", {"command": "/tutorial"})
    G("/tutorial", s == 200 and "tutorial" in b.get("action", ""), f"status={s}")

    s, b = post("/command", {"command": "/list-chats"})
    G("/list-chats", s == 200, f"status={s}")

    s, b = post("/command", {"command": "/quickstart"})
    G("/quickstart", s == 200 and "quickstart" in b.get("action", ""), f"status={s}")

    s, b = post("/command", {"command": "/examples"})
    G("/examples", s == 200 and "examples" in b.get("action", ""), f"status={s}")

    # ── 3. Memory System ──
    print("\n=== 3. Memory System ===")
    s, b = post("/command", {"command": "/memory add e2e-test-mem-12345"})
    added = s == 200 and ("saved" in b.get("message", "").lower() or "save" in b.get("message", "").lower())
    G("/memory add", added, f"msg={b.get('message','')[:80]}")

    s, b = post("/command", {"command": "/memory list"})
    has_mem = "e2e-test-mem-12345" in b.get("message", "")
    G("/memory list contains new memory", has_mem, f"msg={b.get('message','')[:100]}")

    s, b = post("/command", {"command": "/memory search test"})
    G("/memory search", s == 200, f"status={s}")

    # ── 4. Approve Endpoint ──
    print("\n=== 4. Approve Endpoint ===")
    s, b = post("/approve", {"approval_id": "nonexistent-id", "decision": "approved"})
    G("/approve endpoint responds (404=OK)", s in [404, 200], f"status={s}")

    # ── 5. Frontend ──
    print("\n=== 5. Frontend Build ===")
    dist_js = os.path.join(PROJECT_ROOT, "frontend", "dist", "index.js")
    exists = os.path.exists(dist_js)
    G("frontend/dist/index.js exists", exists)
    if exists:
        size = os.path.getsize(dist_js)
        G("Build size > 10KB", size > 10240, f"size={size}")

    components_dir = os.path.join(PROJECT_ROOT, "frontend", "src", "components")
    if os.path.isdir(components_dir):
        components = [f for f in os.listdir(components_dir) if f.endswith(".tsx")]
        G(f"Frontend components ({len(components)} .tsx)", len(components) > 5, f"files={components[:10]}")

    hooks_dir = os.path.join(PROJECT_ROOT, "frontend", "src", "hooks")
    if os.path.isdir(hooks_dir):
        hooks = [f for f in os.listdir(hooks_dir) if f.endswith(".ts")]
        G(f"Frontend hooks ({len(hooks)} .ts)", len(hooks) > 0, f"files={hooks}")

    # ── Summary ──
    print("\n" + "=" * 50)
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    total = len(results)
    print(f"  Total: {total} | PASS: {passed} | FAIL: {failed}")
    print("=" * 50)
    for r in results:
        s = "[OK]" if r["passed"] else "[FAIL]"
        print(f"  {s} {r['name']}")

# Stop server
proc.terminate()
try:
    proc.wait(timeout=5)
except:
    proc.kill()
print("\nServer stopped.")
