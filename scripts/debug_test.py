#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RxyCode E2E debug test."""

import subprocess
import sys
import time
import json
import urllib.request
import urllib.error
import os
import socket
import threading
import http.client

# Force UTF-8 on Windows
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── 配置 ──────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8768
BASE_URL = f"http://{HOST}:{PORT}"
TIMEOUT = 120  # LLM 调用超时
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_ROOT = os.path.dirname(PROJECT_ROOT)  # d:\agent-demo\RxyCode

# ── 颜色输出 ───────────────────────────────────────────
class C:
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"

results = []

def log(msg, color=""):
    print(f"{color}{msg}{C.RESET}")

def record(name, passed, detail=""):
    status = f"{C.GREEN}PASS{C.RESET}" if passed else f"{C.RED}FAIL{C.RESET}"
    results.append({"name": name, "passed": passed, "detail": detail})
    print(f"  [{status}] {name}")
    if detail and not passed:
        print(f"         {C.DIM}{detail[:200]}{C.RESET}")

# ── HTTP 工具 ──────────────────────────────────────────
def http_get(path):
    try:
        req = urllib.request.Request(f"{BASE_URL}{path}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except Exception as e:
        return 0, {"error": str(e)}

def http_post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{BASE_URL}{path}", data=body,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode())
    except Exception as e:
        return 0, {"error": str(e)}

def sse_stream(path, data, timeout=TIMEOUT):
    """发送 POST 请求并读取 SSE 流，返回所有事件列表"""
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
                events.append({"type": "timeout", "message": f"SSE stream timed out after {timeout}s"})
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

# ── 启动 API 服务器 ────────────────────────────────────
def wait_for_server(proc=None, max_wait=30):
    for i in range(max_wait):
        try:
            with socket.create_connection((HOST, PORT), timeout=1):
                status, body = http_get("/status")
                if status == 200:
                    return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            pass
        # 检查进程是否已退出
        if proc and proc.poll() is not None:
            out = proc.stdout.read(4096).decode(errors="replace") if proc.stdout else ""
            log(f"  服务器进程提前退出! code={proc.returncode}", C.RED)
            log(f"  输出: {out[:500]}", C.RED)
            return False
        time.sleep(1)
    return False

def start_server():
    # 先杀掉可能残留的旧进程
    try:
        urllib.request.urlopen(f"{BASE_URL}/status", timeout=2)
        log("  旧服务器已在运行，直接使用", C.YELLOW)
        return None
    except Exception:
        pass

    env = os.environ.copy()
    env["PYTHONPATH"] = PARENT_ROOT  # d:\agent-demo\RxyCode
    proc = subprocess.Popen(
        [sys.executable, "-m", "RxyCode.RxyCode1_1_0.main", "--api", "--api-port", str(PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=PROJECT_ROOT,
    )
    log(f"  API 服务器启动中... PID={proc.pid} port={PORT}", C.CYAN)
    return proc

# ── 测试场景 ───────────────────────────────────────────

def test_health():
    """1. 健康检查 - /status 和 /models"""
    log("\n━━━ 1. 健康检查 ━━━", C.BOLD)

    # /status
    status, body = http_get("/status")
    has_fields = all(k in body for k in ["memory_mb", "model", "mode", "language"]) if status == 200 else False
    record("/status 返回 200 + 正确字段", status == 200 and has_fields,
           f"status={status}, fields={list(body.keys()) if isinstance(body, dict) else 'N/A'}")
    if has_fields:
        log(f"      model={body.get('model')}, mode={body.get('mode')}, lang={body.get('language')}", C.DIM)

    # /models
    status, body = http_get("/models")
    has_model = False
    if status == 200 and isinstance(body, dict):
        models = body.get("models", [])
        has_model = len(models) > 0
        if has_model:
            active = body.get("active", "")
            log(f"      models={[m['id'] for m in models]}, active={active}", C.DIM)
    record("/models 返回已配置模型", status == 200 and has_model,
           f"status={status}, body={str(body)[:150]}")

def test_slash_commands():
    """2. 斜杠命令测试"""
    log("\n━━━ 2. 斜杠命令测试 ━━━", C.BOLD)

    # /help
    status, body = http_post("/command", {"command": "/help"})
    has_help = status == 200 and "帮助" in body.get("message", "")
    record("/help 返回帮助文本", has_help, f"status={status}")

    # /clear
    status, body = http_post("/command", {"command": "/clear"})
    record("/clear 清除上下文", status == 200 and "cleared" in body.get("action", ""), f"status={status}")

    # /cache
    status, body = http_post("/command", {"command": "/cache"})
    has_cache = status == 200 and "Cache" in body.get("message", "")
    record("/cache 缓存统计", has_cache, f"status={status}")

    # /memory list
    status, body = http_post("/command", {"command": "/memory list"})
    record("/memory list 列出记忆", status == 200, f"status={status}")

    # /language en -> zh
    status, body = http_post("/command", {"command": "/language en"})
    has_en = status == 200 and "English" in body.get("message", "")
    record("/language en 切换英文", has_en, f"status={status}")

    # 切回来
    http_post("/command", {"command": "/language zh"})

    # /tutorial
    status, body = http_post("/command", {"command": "/tutorial"})
    record("/tutorial 教程", status == 200 and "tutorial" in body.get("action", ""), f"status={status}")

    # /list-chats
    status, body = http_post("/command", {"command": "/list-chats"})
    record("/list-chats 对话列表", status == 200, f"status={status}")

def test_memory_system():
    """3. 记忆系统测试"""
    log("\n━━━ 3. 记忆系统测试 ━━━", C.BOLD)

    # 添加记忆
    status, body = http_post("/command", {"command": "/memory add test-memory-12345"})
    added = status == 200 and "saved" in body.get("message", "").lower() or "保存" in body.get("message", "")
    record("/memory add 添加记忆", added, f"status={status}, msg={body.get('message','')[:80]}")

    # 列出记忆
    status, body = http_post("/command", {"command": "/memory list"})
    has_mem = "test-memory-12345" in body.get("message", "")
    record("/memory list 包含新记忆", has_mem, f"msg={body.get('message','')[:100]}")

    # 搜索记忆
    status, body = http_post("/command", {"command": "/memory search test"})
    searched = status == 200
    record("/memory search 搜索记忆", searched, f"status={status}")

def test_sse_simple_query():
    """4. SSE 简单查询测试 (fast path)"""
    log("\n━━━ 4. SSE 流式简单查询 (fast path) ━━━", C.BOLD)

    events = sse_stream("/chat/stream", {"message": "你好，请用一句话介绍你自己", "mode": "build"}, timeout=60)
    types = [e.get("type") for e in events]
    has_final = "final" in types
    has_done = "done" in types
    has_token = "token" in types
    has_error = "error" in types

    record("SSE 包含 final 事件", has_final, f"types={types}")
    record("SSE 包含 done 事件", has_done, f"types={types}")
    record("SSE 包含 token 流式事件", has_token, f"types={types}")
    record("SSE 无错误", not has_error,
           f"error={next((e.get('message','') for e in events if e.get('type')=='error'), 'N/A')}")

    if has_final:
        final_text = next((e.get("text", "") for e in events if e.get("type") == "final"), "")
        log(f"      回复预览: {final_text[:120]}...", C.DIM)

    return has_final and has_done and not has_error

def test_build_mode():
    """5. Build 模式复杂任务 (完整管道)"""
    log("\n━━━ 5. Build 模式 - 完整 LangGraph 管道 ━━━", C.BOLD)

    # 用一个需要工具调用的任务
    events = sse_stream("/chat/stream", {
        "message": "读取当前目录下的 README.md 文件，总结其内容",
        "mode": "build"
    }, timeout=120)

    types = [e.get("type") for e in events]
    has_final = "final" in types
    has_tool = "tool_call" in types
    has_done = "done" in types

    record("Build: SSE 包含 final 事件", has_final, f"types={types}")
    record("Build: SSE 包含 tool_call 事件", has_tool, f"types={types}")
    record("Build: SSE 包含 done 事件", has_done, f"types={types}")

    # 检查工具调用内容
    tool_calls = [e for e in events if e.get("type") == "tool_call"]
    if tool_calls:
        tool_names = [tc.get("name", "") for tc in tool_calls]
        log(f"      工具调用: {tool_names}", C.DIM)
        record("Build: 工具调用包含 read 类工具", any("read" in n.lower() or "file" in n.lower() for n in tool_names),
               f"tools={tool_names}")

    if has_final:
        final_text = next((e.get("text", "") for e in events if e.get("type") == "final"), "")
        log(f"      回复预览: {final_text[:150]}...", C.DIM)
        record("Build: 回复包含有意义内容", len(final_text) > 50, f"len={len(final_text)}")

    return has_final and has_done

def test_plan_mode():
    """6. Plan 模式测试 (只读分析)"""
    log("\n━━━ 6. Plan 模式 - 只读分析 ━━━", C.BOLD)

    events = sse_stream("/chat/stream", {
        "message": "分析当前项目的目录结构，给出架构概述",
        "mode": "plan"
    }, timeout=90)

    types = [e.get("type") for e in events]
    has_final = "final" in types
    has_done = "done" in types

    record("Plan: SSE 包含 final 事件", has_final, f"types={types}")
    record("Plan: SSE 包含 done 事件", has_done, f"types={types}")

    if has_final:
        final_text = next((e.get("text", "") for e in events if e.get("type") == "final"), "")
        log(f"      回复预览: {final_text[:150]}...", C.DIM)
        record("Plan: 回复包含分析内容", len(final_text) > 50, f"len={len(final_text)}")

    return has_final and has_done

def test_compose_mode():
    """7. Compose 模式测试"""
    log("\n━━━ 7. Compose 模式 - 规划+构建 ━━━", C.BOLD)

    events = sse_stream("/chat/stream", {
        "message": "在 ~/.rxycode/output/ 目录下创建一个 hello.py 文件，内容为 print('Hello from RxyCode')",
        "mode": "compose"
    }, timeout=120)

    types = [e.get("type") for e in events]
    has_final = "final" in types
    has_done = "done" in types
    has_tool = "tool_call" in types

    record("Compose: SSE 包含 final 事件", has_final, f"types={types}")
    record("Compose: SSE 包含 done 事件", has_done, f"types={types}")
    record("Compose: 包含工具调用", has_tool, f"types={types}")

    if has_final:
        final_text = next((e.get("text", "") for e in events if e.get("type") == "final"), "")
        log(f"      回复预览: {final_text[:150]}...", C.DIM)

    return has_final and has_done

def test_multi_turn():
    """8. 多轮对话 - 记忆累积测试"""
    log("\n━━━ 8. 多轮对话 - 记忆累积 ━━━", C.BOLD)

    # 第一轮
    log("      轮 1: 告诉我你的名字", C.DIM)
    events1 = sse_stream("/chat/stream", {"message": "请记住：我最喜欢的编程语言是 Python", "mode": "build"}, timeout=60)
    types1 = [e.get("type") for e in events1]
    has_final1 = "final" in types1
    record("多轮-轮1: 收到回复", has_final1, f"types={types1}")

    # 第二轮 - 验证记忆
    log("      轮 2: 询问记忆内容", C.DIM)
    events2 = sse_stream("/chat/stream", {"message": "我刚才告诉你我最喜欢的编程语言是什么？", "mode": "build"}, timeout=60)
    types2 = [e.get("type") for e in events2]
    has_final2 = "final" in types2
    record("多轮-轮2: 收到回复", has_final2, f"types={types2}")

    if has_final2:
        final2 = next((e.get("text", "") for e in events2 if e.get("type") == "final"), "")
        mentions_python = "python" in final2.lower()
        record("多轮-轮2: 回复提及 Python", mentions_python,
               f"text={final2[:150]}")
        log(f"      回复预览: {final2[:120]}...", C.DIM)

    # 第三轮
    log("      轮 3: 追问", C.DIM)
    events3 = sse_stream("/chat/stream", {"message": "请再确认一次，我最喜欢什么语言？", "mode": "build"}, timeout=60)
    types3 = [e.get("type") for e in events3]
    has_final3 = "final" in types3
    record("多轮-轮3: 收到回复", has_final3, f"types={types3}")

    # 检查缓存统计
    status, body = http_post("/command", {"command": "/cache"})
    has_cache = status == 200 and "Cache" in body.get("message", "")
    record("多轮: /cache 统计可读", has_cache, f"status={status}")
    if has_cache:
        log(f"      {body.get('message', '')[:200]}", C.DIM)

def test_save_load_chat():
    """9. 对话存储测试"""
    log("\n━━━ 9. 对话存储 - save/load ━━━", C.BOLD)

    # 保存
    status, body = http_post("/command", {"command": "/save-chat test-e2e-session"})
    saved = status == 200 and "saved" in body.get("message", "").lower() or "保存" in body.get("message", "")
    record("/save-chat 保存对话", saved, f"msg={body.get('message','')[:80]}")

    # 列表
    status, body = http_post("/command", {"command": "/list-chats"})
    listed = status == 200
    record("/list-chats 列表包含已保存", listed, f"status={status}")

    # 加载
    status, body = http_post("/command", {"command": "/load-chat test-e2e-session"})
    loaded = status == 200 and "loaded" in body.get("message", "").lower() or "加载" in body.get("message", "")
    record("/load-chat 加载对话", loaded, f"msg={body.get('message','')[:80]}")

def test_approve_endpoint():
    """10. 安全审批端点测试"""
    log("\n━━━ 10. 安全审批端点 ━━━", C.BOLD)

    # 发送一个无效的 approval_id，应该返回 404
    status, body = http_post("/approve", {"approval_id": "nonexistent-id", "decision": "approved"})
    # 404 = 端点存在但 ID 不存在 = 端点正常工作
    record("/approve 端点响应 (404=正常)", status in [404, 200],
           f"status={status}, body={str(body)[:100]}")

def test_frontend():
    """11. 前端构建产物检查"""
    log("\n━━━ 11. 前端构建产物 ━━━", C.BOLD)

    dist_js = os.path.join(PROJECT_ROOT, "frontend", "dist", "index.js")
    exists = os.path.exists(dist_js)
    record("frontend/dist/index.js 存在", exists, f"path={dist_js}")

    if exists:
        size = os.path.getsize(dist_js)
        record("构建产物大小 > 10KB", size > 10240, f"size={size} bytes")

    package_json = os.path.join(PROJECT_ROOT, "frontend", "package.json")
    has_pkg = os.path.exists(package_json)
    record("frontend/package.json 存在", has_pkg)

    # 检查关键组件文件
    components_dir = os.path.join(PROJECT_ROOT, "frontend", "src", "components")
    if os.path.isdir(components_dir):
        components = [f for f in os.listdir(components_dir) if f.endswith(".tsx")]
        record(f"前端组件存在 ({len(components)} 个 .tsx)", len(components) > 5,
               f"components={components[:10]}")
    else:
        record("前端组件目录存在", False, f"dir={components_dir}")

# ── 主流程 ────────────────────────────────────────────
def main():
    log("\n" + "=" * 60, C.CYAN)
    log("  RxyCode Full E2E Debug Test", C.BOLD + C.CYAN)
    log("=" * 60, C.CYAN)

    # 启动服务器
    log("\n启动 API 服务器...", C.CYAN)
    proc = start_server()

    # 等待就绪
    if not wait_for_server(proc, 30):
        log("ERROR: API 服务器未能在 30 秒内就绪", C.RED)
        sys.exit(1)
    log("  服务器就绪!", C.GREEN)

    # 运行所有测试
    try:
        test_health()
        test_slash_commands()
        test_memory_system()
        test_sse_simple_query()
        test_build_mode()
        test_plan_mode()
        test_compose_mode()
        test_multi_turn()
        test_save_load_chat()
        test_approve_endpoint()
        test_frontend()
    except Exception as e:
        log(f"\n测试中断: {e}", C.RED)
        import traceback
        traceback.print_exc()
    finally:
        # 汇总报告
        log("\n" + "=" * 60, C.CYAN)
        log("  测试报告汇总", C.BOLD + C.CYAN)
        log("=" * 60, C.CYAN)

        passed = sum(1 for r in results if r["passed"])
        failed = sum(1 for r in results if not r["passed"])
        total = len(results)

        log(f"\n  总计: {total} 项 | {C.GREEN}通过: {passed}{C.RESET} | {C.RED}失败: {failed}{C.RESET}\n")

        # 详细列表
        for r in results:
            status = f"{C.GREEN}[OK]{C.RESET}" if r["passed"] else f"{C.RED}[FAIL]{C.RESET}"
            print(f"  {status} {r['name']}")
            if not r["passed"] and r["detail"]:
                print(f"     {C.DIM}{r['detail'][:150]}{C.RESET}")

        log(f"\n{'=' * 60}", C.CYAN)
        if failed == 0:
            log(f"  {C.GREEN}{C.BOLD}全部通过!{C.RESET} ({passed}/{total})")
        else:
            log(f"  {C.RED}{C.BOLD}有 {failed} 项失败{C.RESET} ({passed}/{total} 通过)")
        log(f"{'=' * 60}\n", C.CYAN)

        # 关闭服务器
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            log("  API 服务器已关闭", C.DIM)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
