"""RxyCode UX Research - Test Script"""
import requests
import json
import time
import sys

API_URL = "http://localhost:8765"

def send_message(message, mode="build"):
    """Send a message to RxyCode and return the response."""
    start = time.time()
    try:
        resp = requests.post(
            f"{API_URL}/chat",
            json={"message": message, "mode": mode},
            timeout=120
        )
        elapsed = time.time() - start
        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": True,
                "response": data.get("response", ""),
                "tool_calls": data.get("tool_calls", []),
                "thinking": data.get("thinking", ""),
                "error": data.get("error"),
                "elapsed": round(elapsed, 2)
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {resp.status_code}: {resp.text}",
                "elapsed": round(elapsed, 2)
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "elapsed": round(time.time() - start, 2)
        }

def send_command(command):
    """Send a slash command to RxyCode."""
    try:
        resp = requests.post(
            f"{API_URL}/command",
            json={"command": command},
            timeout=30
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            return {"error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"error": str(e)}

def get_status():
    """Get current RxyCode status."""
    try:
        resp = requests.get(f"{API_URL}/status", timeout=10)
        return resp.json() if resp.status_code == 200 else None
    except:
        return None

def run_test(scenario_num, title, message, mode="build"):
    """Run a single test scenario and print results."""
    print(f"\n{'='*70}")
    print(f"场景 {scenario_num}: {title}")
    print(f"{'='*70}")
    print(f"模式: {mode}")
    print(f"用户输入: {message}")
    print(f"发送时间: {time.strftime('%H:%M:%S')}")
    print(f"{'─'*70}")
    
    result = send_message(message, mode)
    
    print(f"耗时: {result['elapsed']}s")
    print(f"成功: {result['success']}")
    
    if result.get("thinking"):
        print(f"\n[思考过程]:")
        print(result["thinking"][:500])
    
    if result.get("tool_calls"):
        print(f"\n[工具调用]: {len(result['tool_calls'])} 次")
        for tc in result["tool_calls"]:
            if isinstance(tc, dict):
                print(f"  - {tc.get('tool', 'unknown')}: {str(tc.get('input', ''))[:100]}")
            else:
                print(f"  - {str(tc)[:100]}")
    
    print(f"\n[Agent 回复]:")
    response = result.get("response", "")
    if response:
        print(response[:2000])
    else:
        print("(空回复)")
    
    if result.get("error"):
        print(f"\n[错误]: {result['error']}")
    
    # Get status after
    status = get_status()
    if status:
        print(f"\n[系统状态] 模式:{status.get('mode')} 模型:{status.get('model')} "
              f"Token入:{status.get('input_tokens')} 出:{status.get('output_tokens')} "
              f"内存:{status.get('memory_mb')}MB 缓存:{status.get('cache_size')}")
    
    print(f"{'='*70}\n")
    return result


if __name__ == "__main__":
    print("RxyCode UX Research Testing Suite")
    print(f"测试开始: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"API: {API_URL}")
    
    # Check server status
    status = get_status()
    if not status:
        print("ERROR: API server not reachable!")
        sys.exit(1)
    
    print(f"Server Status: model={status.get('model')}, mode={status.get('mode')}")
    print()
    
    results = {}
    
    # Scenario 1: New user onboarding
    results[1] = run_test(
        1, "新用户首次交互",
        "你好，我刚安装了RxyCode，你能帮我做什么？请介绍一下你的主要功能。"
    )
    
    # Scenario 2: Basic file creation
    results[2] = run_test(
        2, "基础文件创建",
        "帮我创建一个Python文件 hello.py，内容是打印Hello World并包含一个简单的加法函数"
    )
    
    # Scenario 3: Code understanding
    results[3] = run_test(
        3, "代码理解与解释",
        "读取刚才创建的hello.py文件，解释它的功能"
    )
    
    # Scenario 4: Bug fixing
    results[4] = run_test(
        4, "Bug修复",
        "我有一段代码 def divide(a, b): return a / b，用户反馈除以零时会崩溃，帮我修复这个bug"
    )
    
    # Scenario 5: Project exploration
    results[5] = run_test(
        5, "项目结构探索",
        "列出当前目录的文件结构，帮我理解这个项目是做什么的"
    )
    
    # Scenario 6: Complex multi-step task
    results[6] = run_test(
        6, "复杂多步骤任务",
        "创建一个计算器模块calculator.py，包含加减乘除四个函数，写好中文注释，然后再创建一个test_calculator.py测试文件"
    )
    
    # Scenario 7: Error handling - ambiguous request
    results[7] = run_test(
        7, "模糊请求处理",
        "帮我搞一下那个东西"
    )
    
    # Scenario 8: Plan mode test
    results[8] = run_test(
        8, "Plan模式测试",
        "分析当前项目的架构，给出优化建议",
        mode="plan"
    )
    
    # Summary
    print(f"\n{'='*70}")
    print("测试总结")
    print(f"{'='*70}")
    for num, r in results.items():
        status = "✓ 成功" if r["success"] else "✗ 失败"
        print(f"场景{num}: {status} | 耗时: {r['elapsed']}s | 回复长度: {len(r.get('response', ''))}字")
    
    print(f"\n测试结束: {time.strftime('%Y-%m-%d %H:%M:%S')}")
