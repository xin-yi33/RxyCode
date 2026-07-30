#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase 2: SSE streaming + LLM tests (simple query, build, plan, multi-turn)."""

import subprocess, sys, os, time, json, socket
import urllib.request as ur
import http.client

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOST = "127.0.0.1"
PORT = 8772
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
    sys.stdout.flush()

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
        r = ur.urlopen(req, timeout=120)
        return r.status, json.loads(r.read().decode())
    except Exception as e:
        return 0, {"error": str(e)}

def sse_stream(path, data, timeout=120):
    """POST and read SSE stream, return list of events."""
    events = []
    try:
        body = json.dumps(data).encode()
        conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
        conn.request("POST", path, body=body, headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream"
        })
        resp = conn.getresponse()
        buffer = ""
        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                events.append({"type": "timeout", "message": f"SSE timed out after {timeout}s"})
                break
            chunk = resp.read(1)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                for line in block.split("\n"):
                    if line.startswith("data: "):
                        try:
                            ev = json.loads(line[6:])
                            events.append(ev)
                            if ev.get("type") == "done":
                                conn.close()
                                return events
                        except json.JSONDecodeError:
                            pass
        conn.close()
    except Exception as e:
        events.append({"type": "error", "message": str(e)})
    return events

# ── Start server ──
print("Starting API server...")
env = os.environ.copy()
env["PYTHONPATH"] = PARENT_ROOT
proc = subprocess.Popen(
    [sys.executable, "-m", "RxyCode.RxyCode1_1_0.main", "--api", "--api-port", str(PORT)],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=PROJECT_ROOT,
)
print(f"  PID={proc.pid}")

ready = False
for i in range(30):
    time.sleep(1)
    if proc.poll() is not None:
        out = proc.stdout.read(2048).decode(errors="replace")
        print(f"  Server exited! code={proc.returncode}")
        print(f"  Output: {out[:500]}")
        break
    try:
        r = ur.urlopen(f"{BASE}/status", timeout=2)
        body = json.loads(r.read().decode())
        if body.get("model") != "unknown":
            print(f"  Server ready! model={body.get('model')}")
            ready = True
            break
    except:
        pass

if not ready:
    print("Server not ready after 30s, aborting.")
    proc.terminate()
    sys.exit(1)

# ── Test 1: Simple SSE query (fast path) ──
print("\n=== Test 1: SSE Simple Query (fast path) ===")
print("  Sending: 'Hello, introduce yourself in one sentence'")
sys.stdout.flush()
events = sse_stream("/chat/stream", {"message": "Hello, introduce yourself in one sentence", "mode": "build"}, timeout=60)
types = [e.get("type") for e in events]
has_final = "final" in types
has_done = "done" in types
has_token = "token" in types
has_error = "error" in types

G("SSE: has 'final' event", has_final, f"types={types}")
G("SSE: has 'done' event", has_done, f"types={types}")
G("SSE: has 'token' streaming events", has_token, f"types={types}")
G("SSE: no error", not has_error,
  f"error={next((e.get('message','') for e in events if e.get('type')=='error'), 'N/A')}")

if has_final:
    final_text = next((e.get("text", "") for e in events if e.get("type") == "final"), "")
    print(f"  Reply preview: {final_text[:150]}")
    G("SSE: reply has meaningful content", len(final_text) > 20, f"len={len(final_text)}")

# ── Test 2: Build mode with tool call ──
print("\n=== Test 2: Build Mode - Full Pipeline ===")
print("  Sending: 'Read README.md and summarize its content'")
sys.stdout.flush()
events = sse_stream("/chat/stream", {
    "message": "Read the README.md file in the current directory and summarize its content",
    "mode": "build"
}, timeout=120)
types = [e.get("type") for e in events]
has_final = "final" in types
has_tool = "tool_call" in types
has_done = "done" in types

G("Build: has 'final' event", has_final, f"types={types}")
G("Build: has 'tool_call' event", has_tool, f"types={types}")
G("Build: has 'done' event", has_done, f"types={types}")

tool_calls = [e for e in events if e.get("type") == "tool_call"]
if tool_calls:
    tool_names = [tc.get("name", "") for tc in tool_calls]
    print(f"  Tool calls: {tool_names}")
    G("Build: tool call includes read/file", any("read" in n.lower() or "file" in n.lower() for n in tool_names), f"tools={tool_names}")

if has_final:
    final_text = next((e.get("text", "") for e in events if e.get("type") == "final"), "")
    print(f"  Reply preview: {final_text[:150]}")
    G("Build: reply has content", len(final_text) > 50, f"len={len(final_text)}")

# ── Test 3: Plan mode ──
print("\n=== Test 3: Plan Mode - Read-only Analysis ===")
print("  Sending: 'Analyze the project directory structure'")
sys.stdout.flush()
events = sse_stream("/chat/stream", {
    "message": "Analyze the current project directory structure and give an architecture overview",
    "mode": "plan"
}, timeout=90)
types = [e.get("type") for e in events]
has_final = "final" in types
has_done = "done" in types

G("Plan: has 'final' event", has_final, f"types={types}")
G("Plan: has 'done' event", has_done, f"types={types}")

if has_final:
    final_text = next((e.get("text", "") for e in events if e.get("type") == "final"), "")
    print(f"  Reply preview: {final_text[:150]}")
    G("Plan: reply has analysis content", len(final_text) > 50, f"len={len(final_text)}")

# ── Test 4: Multi-turn conversation ──
print("\n=== Test 4: Multi-turn Conversation ===")
print("  Turn 1: 'Remember: my favorite language is Python'")
sys.stdout.flush()
events1 = sse_stream("/chat/stream", {"message": "Please remember that my favorite programming language is Python", "mode": "build"}, timeout=60)
types1 = [e.get("type") for e in events1]
has_final1 = "final" in types1
G("Multi-turn T1: got reply", has_final1, f"types={types1}")

print("  Turn 2: 'What is my favorite language?'")
sys.stdout.flush()
events2 = sse_stream("/chat/stream", {"message": "What did I tell you my favorite programming language is?", "mode": "build"}, timeout=60)
types2 = [e.get("type") for e in events2]
has_final2 = "final" in types2
G("Multi-turn T2: got reply", has_final2, f"types={types2}")

if has_final2:
    final2 = next((e.get("text", "") for e in events2 if e.get("type") == "final"), "")
    mentions_python = "python" in final2.lower()
    print(f"  Reply: {final2[:150]}")
    G("Multi-turn T2: reply mentions Python", mentions_python, f"text={final2[:100]}")

print("  Turn 3: 'Confirm again - what do I like?'")
sys.stdout.flush()
events3 = sse_stream("/chat/stream", {"message": "Please confirm again - what is my favorite programming language?", "mode": "build"}, timeout=60)
types3 = [e.get("type") for e in events3]
has_final3 = "final" in types3
G("Multi-turn T3: got reply", has_final3, f"types={types3}")

# ── Test 5: Cache stats after conversation ──
print("\n=== Test 5: Cache Stats ===")
s, b = post("/command", {"command": "/cache"})
has_cache = s == 200 and "Cache" in b.get("message", "")
G("Cache stats readable", has_cache, f"status={s}")
if has_cache:
    print(f"  {b.get('message', '')[:300]}")

# ── Test 6: Save/Load chat ──
print("\n=== Test 6: Save/Load Chat ===")
s, b = post("/command", {"command": "/save-chat e2e-test-session"})
saved = s == 200 and ("saved" in b.get("message", "").lower() or "save" in b.get("message", "").lower())
G("/save-chat saved", saved, f"msg={b.get('message','')[:80]}")

s, b = post("/command", {"command": "/list-chats"})
G("/list-chats works", s == 200, f"status={s}")

s, b = post("/command", {"command": "/load-chat e2e-test-session"})
loaded = s == 200 and ("loaded" in b.get("message", "").lower() or "load" in b.get("message", "").lower())
G("/load-chat loaded", loaded, f"msg={b.get('message','')[:80]}")

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

# ── Stop server ──
proc.terminate()
try:
    proc.wait(timeout=5)
except:
    proc.kill()
print("\nServer stopped.")
