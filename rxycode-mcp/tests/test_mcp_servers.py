#!/usr/bin/env python
"""
RxyCode MCP 服务器测试套件
==========================
测试 4 个 MCP 服务器的核心工具功能，验证问题修复效果。

运行方式：
  cd rxycode-mcp
  python -m pytest tests/ -v
"""

import json
import os
import tempfile
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import rxycode_verify_mcp as verify_mod
import rxycode_shell_mcp as shell_mod
import codebase_explorer_mcp as explorer_mod
import task_progress_mcp as task_mod


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def parse_result(result_str: str) -> dict:
    """解析 MCP 工具返回的 JSON 字符串。"""
    return json.loads(result_str)


# ---------------------------------------------------------------------------
# 验证层 MCP 测试 (rxycode-verify) — 解决 P0-1
# ---------------------------------------------------------------------------

class TestVerifyMCP:
    """验证层 MCP 测试 —— 拦截幻觉性成功。"""

    def setup_method(self):
        """每个测试前创建临时文件。"""
        self.tmpdir = tempfile.mkdtemp()
        self.real_file = os.path.join(self.tmpdir, "hello.py")
        with open(self.real_file, "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a + b\n\nprint(add(1, 2))\n")

    def test_verify_file_exists_true(self):
        """验证存在的文件应返回 verified=True。"""
        result = parse_result(verify_mod.verify_file_exists(self.real_file))
        assert result["verified"] is True
        assert "size_bytes" in result["details"]
        assert result["details"]["is_file"] is True

    def test_verify_file_exists_false(self):
        """验证不存在的文件应返回 verified=False 和修正声明。"""
        fake_path = os.path.join(self.tmpdir, "nonexistent.py")
        result = parse_result(verify_mod.verify_file_exists(fake_path))
        assert result["verified"] is False
        assert "correction" in result
        assert "不存在" in result["correction"]

    def test_verify_file_content_match(self):
        """验证文件内容模式匹配应返回 verified=True。"""
        result = parse_result(
            verify_mod.verify_file_content(self.real_file, [r"def add"])
        )
        assert result["verified"] is True
        assert result["details"]["pattern_results"][0]["found"] is True

    def test_verify_file_content_mismatch(self):
        """验证文件内容不匹配应返回 verified=False 和修正声明。"""
        result = parse_result(
            verify_mod.verify_file_content(self.real_file, [r"def multiply"])
        )
        assert result["verified"] is False
        assert "correction" in result
        assert "def multiply" in result["correction"]

    def test_verify_file_created_success(self):
        """组合验证：文件存在且内容匹配。"""
        result = parse_result(
            verify_mod.verify_file_created(self.real_file, [r"def add", r"print"])
        )
        assert result["verified"] is True

    def test_verify_file_created_nonexistent(self):
        """组合验证：文件不存在。"""
        fake_path = os.path.join(self.tmpdir, "fake.py")
        result = parse_result(verify_mod.verify_file_created(fake_path))
        assert result["verified"] is False

    def test_verify_command_executed_success(self):
        """验证命令成功执行。"""
        result = parse_result(
            verify_mod.verify_command_executed("echo hello", timeout=5)
        )
        assert result["verified"] is True
        assert result["details"]["exit_code"] == 0

    def test_verify_command_executed_failure(self):
        """验证命令失败应返回 verified=False。"""
        result = parse_result(
            verify_mod.verify_command_executed("exit 1", timeout=5)
        )
        assert result["verified"] is False
        assert "correction" in result

    def test_fact_check_paths_all_exist(self):
        """批量路径核查——全部存在。"""
        result = parse_result(
            verify_mod.fact_check_paths([self.real_file, self.tmpdir])
        )
        assert result["verified"] is True

    def test_fact_check_paths_some_missing(self):
        """批量路径核查——部分不存在。"""
        result = parse_result(
            verify_mod.fact_check_paths([self.real_file, "/nonexistent/path"])
        )
        assert result["verified"] is False
        assert "/nonexistent/path" in result["details"]["missing"]

    def test_compute_file_hash(self):
        """计算文件哈希。"""
        result = parse_result(verify_mod.compute_file_hash(self.real_file))
        assert "hash" in result
        assert len(result["hash"]) == 64  # SHA-256

    def test_list_directory_real(self):
        """列出目录真实内容。"""
        result = parse_result(verify_mod.list_directory_real(self.tmpdir))
        data = json.loads(result) if isinstance(result, str) else result
        assert data["entry_count"] >= 1


# ---------------------------------------------------------------------------
# 执行层 MCP 测试 (rxycode-shell) — 解决 P0-2, P0-3
# ---------------------------------------------------------------------------

class TestShellMCP:
    """执行层 MCP 测试 —— 可靠执行、环境感知。"""

    def test_detect_environment(self):
        """环境探测应返回真实信息。"""
        result = parse_result(shell_mod.detect_environment())
        assert "real_username" in result
        assert result["real_username"] != "unknown"
        assert "desktop" in result
        assert "available_shells" in result
        # 关键：桌面路径不应包含 "RxyCode"（进程身份）
        assert "RxyCode" not in result["desktop"]

    def test_resolve_user_path_desktop(self):
        """解析桌面路径应使用真实用户名。"""
        result = parse_result(shell_mod.resolve_user_path("desktop"))
        assert "resolved_path" in result
        assert "RxyCode" not in result["resolved_path"]

    def test_resolve_user_path_home(self):
        """解析主目录路径。"""
        result = parse_result(shell_mod.resolve_user_path("home"))
        assert "resolved_path" in result
        assert os.path.isdir(result["resolved_path"])

    def test_resolve_user_path_invalid(self):
        """无效路径类型应返回错误。"""
        result = parse_result(shell_mod.resolve_user_path("invalid_type"))
        assert "error" in result

    def test_execute_shell_success(self):
        """成功执行命令。"""
        result = parse_result(
            shell_mod.execute_shell("echo test123", timeout=10)
        )
        assert result["success"] is True
        assert "test123" in result["stdout"]

    def test_execute_shell_timeout(self):
        """超时命令应返回失败而非无限等待。"""
        # 使用一个会长时间运行的命令，设置短超时
        if os.name == "nt":
            cmd = "ping -n 10 127.0.0.1"
        else:
            cmd = "sleep 10"
        result = parse_result(shell_mod.execute_shell(cmd, timeout=2, max_retries=0))
        assert result["success"] is False
        # 应有超时或失败的明确信息
        assert result["timed_out"] is True or "stderr" in result

    def test_translate_command_ps_to_cmd(self):
        """翻译 PowerShell 语法到 CMD。"""
        result = parse_result(
            shell_mod.translate_command(
                "echo $env:USERPROFILE", "powershell", "cmd"
            )
        )
        assert result["changed"] is True
        assert "%USERPROFILE%" in result["translated"]
        assert "$env:" not in result["translated"]

    def test_translate_command_auto_detect(self):
        """自动检测 Shell 语法。"""
        result = parse_result(
            shell_mod.translate_command(
                "$env:PATH", "auto", "cmd"
            )
        )
        assert result["detected_syntax"] == "powershell"

    def test_write_file_safely_success(self):
        """安全写入文件。"""
        path = os.path.join(tempfile.mkdtemp(), "test_write.py")
        result = parse_result(
            shell_mod.write_file_safely(path, "print('hello')\n")
        )
        assert result["success"] is True
        assert result["content_verified"] is True
        assert os.path.isfile(path)

    def test_write_file_safely_with_dirs(self):
        """安全写入文件——自动创建父目录。"""
        path = os.path.join(tempfile.mkdtemp(), "subdir", "nested", "file.py")
        result = parse_result(
            shell_mod.write_file_safely(path, "# content", create_dirs=True)
        )
        assert result["success"] is True

    def test_read_file_safely_success(self):
        """安全读取文件。"""
        path = os.path.join(tempfile.mkdtemp(), "read_test.txt")
        with open(path, "w") as f:
            f.write("test content")
        result = parse_result(shell_mod.read_file_safely(path))
        assert result["success"] is True
        assert "test content" in result["content"]

    def test_read_file_safely_nonexistent(self):
        """读取不存在的文件应返回明确错误而非超时。"""
        result = parse_result(shell_mod.read_file_safely("/nonexistent/file.txt"))
        assert result["success"] is False
        assert "不存在" in result["error"]


# ---------------------------------------------------------------------------
# 代码库探测 MCP 测试 (codebase-explorer) — 解决 P1-2
# ---------------------------------------------------------------------------

class TestExplorerMCP:
    """代码库探测 MCP 测试 —— 消除项目结构幻觉。"""

    def setup_method(self):
        """创建测试项目结构。"""
        self.project_root = tempfile.mkdtemp()
        # 创建 Python 项目标记
        with open(os.path.join(self.project_root, "setup.py"), "w") as f:
            f.write("# setup")
        with open(os.path.join(self.project_root, "requirements.txt"), "w") as f:
            f.write("mcp>=1.0")
        # 创建源文件
        os.makedirs(os.path.join(self.project_root, "src"))
        with open(os.path.join(self.project_root, "src", "main.py"), "w") as f:
            f.write("def main():\n    print('hello world')\n")
        # 创建 __pycache__（应被忽略）
        os.makedirs(os.path.join(self.project_root, "__pycache__"))

    def test_scan_project_tree(self):
        """扫描项目真实文件树。"""
        result = parse_result(
            explorer_mod.scan_project_tree(self.project_root, max_depth=3)
        )
        assert result["success"] is True
        assert result["stats"]["file_count"] >= 3
        # __pycache__ 应被忽略
        for entry in result["tree"]:
            assert entry["name"] != "__pycache__"

    def test_detect_project_type_python(self):
        """检测 Python 项目类型。"""
        result = parse_result(explorer_mod.detect_project_type(self.project_root))
        assert result["success"] is True
        types = [t["type"] for t in result["detected_types"]]
        assert "python" in types

    def test_list_real_files(self):
        """列出匹配的真实文件。"""
        result = parse_result(
            explorer_mod.list_real_files("*.py", self.project_root)
        )
        assert result["success"] is True
        assert result["match_count"] >= 1
        # 不应返回虚构的文件
        for m in result["matches"]:
            assert os.path.exists(m["absolute"])

    def test_verify_path_exists_true(self):
        """验证存在的路径。"""
        result = parse_result(
            explorer_mod.verify_path_exists(os.path.join(self.project_root, "setup.py"))
        )
        assert result["exists"] is True
        assert result["is_file"] is True

    def test_verify_path_exists_false(self):
        """验证不存在的路径——应有警告。"""
        result = parse_result(
            explorer_mod.verify_path_exists(os.path.join(self.project_root, "Minecraft-Unity"))
        )
        assert result["exists"] is False
        assert "warning" in result

    def test_search_codebase(self):
        """搜索代码库真实内容。"""
        result = parse_result(
            explorer_mod.search_codebase("hello world", self.project_root)
        )
        assert result["success"] is True
        assert result["result_count"] >= 1
        assert "main.py" in result["results"][0]["file"]

    def test_get_file_summary(self):
        """获取文件摘要。"""
        result = parse_result(
            explorer_mod.get_file_summary(
                os.path.join(self.project_root, "src", "main.py")
            )
        )
        assert result["success"] is True
        assert "def main" in result["content_preview"]

    def test_get_file_summary_nonexistent(self):
        """获取不存在文件的摘要应返回错误。"""
        result = parse_result(
            explorer_mod.get_file_summary("/nonexistent/file.py")
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# 任务进度 MCP 测试 (task-progress) — 解决 P2-2, P2-3
# ---------------------------------------------------------------------------

class TestTaskProgressMCP:
    """任务进度追踪 MCP 测试 —— 结构化事件流。"""

    def test_start_task(self):
        """注册新任务。"""
        result = parse_result(
            task_mod.start_task("创建计算器", ["编写 calculator.py", "编写测试", "运行测试"])
        )
        assert "task_id" in result
        assert result["total_steps"] == 3
        assert result["status"] == "pending"

    def test_update_progress_running(self):
        """更新步骤为运行中。"""
        task = parse_result(
            task_mod.start_task("测试任务", ["步骤1", "步骤2"])
        )
        task_id = task["task_id"]
        result = parse_result(
            task_mod.update_progress(task_id, 0, "running", "开始执行步骤1")
        )
        assert result["step_status"] == "running"
        assert result["task_status"] == "running"

    def test_update_progress_success(self):
        """更新步骤为成功。"""
        task = parse_result(
            task_mod.start_task("测试任务", ["步骤1"])
        )
        task_id = task["task_id"]
        task_mod.update_progress(task_id, 0, "running", "开始")
        result = parse_result(
            task_mod.update_progress(task_id, 0, "success", "完成")
        )
        assert result["step_status"] == "success"
        assert result["progress_percent"] == 100.0
        assert result["task_status"] == "completed"

    def test_update_progress_failed(self):
        """更新步骤为失败。"""
        task = parse_result(
            task_mod.start_task("测试任务", ["步骤1", "步骤2"])
        )
        task_id = task["task_id"]
        result = parse_result(
            task_mod.update_progress(task_id, 0, "failed", "执行错误")
        )
        assert result["step_status"] == "failed"
        assert result["task_status"] == "failed"

    def test_log_tool_call(self):
        """记录工具调用。"""
        task = parse_result(
            task_mod.start_task("测试任务", ["步骤1"])
        )
        task_id = task["task_id"]
        result = parse_result(
            task_mod.log_tool_call(
                task_id, 0, "write_file",
                {"path": "/tmp/test.py", "content": "print(1)"},
                {"success": True}, "success", 0.5
            )
        )
        assert result["logged"] is True
        assert result["tool"] == "write_file"

    def test_get_task_status(self):
        """查询任务状态。"""
        task = parse_result(
            task_mod.start_task("测试任务", ["步骤1", "步骤2", "步骤3"])
        )
        task_id = task["task_id"]
        task_mod.update_progress(task_id, 0, "success", "完成步骤1")
        task_mod.update_progress(task_id, 1, "running", "执行步骤2")
        result = parse_result(task_mod.get_task_status(task_id))
        assert result["task"]["status"] == "running"
        assert result["task"]["current_step"] == 1

    def test_get_execution_log(self):
        """获取执行日志。"""
        task = parse_result(
            task_mod.start_task("测试任务", ["步骤1"])
        )
        task_id = task["task_id"]
        task_mod.update_progress(task_id, 0, "running", "开始")
        task_mod.update_progress(task_id, 0, "success", "完成")
        result = parse_result(task_mod.get_execution_log(task_id))
        assert result["total_events"] >= 3  # task_started + step_started + step_completed
        event_types = [e["event_type"] for e in result["events"]]
        assert "task_started" in event_types
        assert "step_completed" in event_types

    def test_get_all_tool_calls(self):
        """获取所有工具调用汇总。"""
        task = parse_result(
            task_mod.start_task("测试任务", ["步骤1"])
        )
        task_id = task["task_id"]
        task_mod.log_tool_call(task_id, 0, "write", {"path": "a.py"}, {}, "success", 0.1)
        task_mod.log_tool_call(task_id, 0, "read", {"path": "a.py"}, {}, "success", 0.05)
        task_mod.log_tool_call(task_id, 0, "bash", {"cmd": "ls"}, {}, "failed", 0.3)
        result = parse_result(task_mod.get_all_tool_calls(task_id))
        assert result["stats"]["total_calls"] == 3
        assert result["stats"]["by_tool"]["write"] == 1
        assert result["stats"]["by_status"]["failed"] == 1

    def test_list_active_tasks(self):
        """列出活跃任务。"""
        task_mod.start_task("活跃任务", ["步骤1"])
        result = parse_result(task_mod.list_active_tasks())
        assert result["active_count"] >= 1

    def test_nonexistent_task(self):
        """查询不存在的任务应返回错误。"""
        result = parse_result(task_mod.get_task_status("nonexistent_task"))
        assert "error" in result


# ---------------------------------------------------------------------------
# 端到端场景测试 —— 模拟用户报告中的问题场景
# ---------------------------------------------------------------------------

class TestEndToEndScenarios:
    """端到端测试 —— 验证用户报告中的具体问题是否被修复。"""

    def test_scenario_p0_1_hallucinated_success(self):
        """P0-1 场景：Agent 声称创建了文件但实际没有。

        验证层应拦截此幻觉。
        """
        tmpdir = tempfile.mkdtemp()
        claimed_path = os.path.join(tmpdir, "calculator.py")
        # Agent 声称创建了这个文件，但实际没有
        result = parse_result(verify_mod.verify_file_created(claimed_path))
        assert result["verified"] is False
        assert "不存在" in result["evidence"]
        # 修正声明应指导 Agent 说什么
        assert "correction" in result

    def test_scenario_p0_1_test_hallucination(self):
        """P0-1 场景：Agent 声称测试通过但实际没运行。

        验证层应实际运行测试并暴露谎言。
        """
        # 创建一个会失败的测试
        tmpdir = tempfile.mkdtemp()
        test_file = os.path.join(tmpdir, "test_fail.py")
        with open(test_file, "w") as f:
            f.write("def test_fail():\n    assert False\n")
        result = parse_result(
            verify_mod.verify_test_passed(
                f"{sys.executable} -m pytest {test_file} -q",
                timeout=30
            )
        )
        assert result["verified"] is False
        assert "correction" in result

    def test_scenario_p0_2_shell_syntax_confusion(self):
        """P0-2 场景：PowerShell 语法在 CMD 中执行。

        Shell 翻译器应检测并翻译语法。
        """
        ps_command = 'Join-Path $env:USERPROFILE "Desktop"'
        result = parse_result(
            shell_mod.translate_command(ps_command, "powershell", "cmd")
        )
        assert result["changed"] is True
        assert "$env:" not in result["translated"]
        assert "%USERPROFILE%" in result["translated"]

    def test_scenario_p0_3_path_error(self):
        """P0-3 场景：路径使用进程身份而非登录用户。

        环境探测应返回真实用户路径。
        """
        result = parse_result(shell_mod.detect_environment())
        desktop = result["desktop"]
        username = result["real_username"]
        # 桌面路径应包含真实用户名，不含 "RxyCode"
        assert "RxyCode" not in desktop
        assert username in desktop or username == os.path.basename(
            os.environ.get("USERPROFILE", "")
        )

    def test_scenario_p1_2_project_hallucination(self):
        """P1-2 场景：Agent 虚构项目结构。

        代码库探测应返回真实结构，验证虚构路径不存在。
        """
        tmpdir = tempfile.mkdtemp()
        # 只创建真实文件
        with open(os.path.join(tmpdir, "main.py"), "w") as f:
            f.write("# main")
        # Agent 声称存在 Minecraft-Unity 目录
        result = parse_result(
            explorer_mod.verify_path_exists(
                os.path.join(tmpdir, "Minecraft-Unity")
            )
        )
        assert result["exists"] is False
        assert "warning" in result

    def test_scenario_p0_2_write_timeout(self):
        """P0-2 场景：文件写入超时 120s。

        安全写入应在 15s 内完成或返回明确失败。
        """
        import time
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "hello.py")
        content = "print('Hello World')\n\ndef add(a, b):\n    return a + b\n"

        start = time.time()
        result = parse_result(shell_mod.write_file_safely(path, content, timeout=15))
        elapsed = time.time() - start

        assert result["success"] is True
        assert elapsed < 5  # 应远小于 120s
        assert result["content_verified"] is True

    def test_scenario_full_pipeline(self):
        """完整管道测试：创建文件 → 验证 → 记录进度。"""
        tmpdir = tempfile.mkdtemp()
        file_path = os.path.join(tmpdir, "calculator.py")
        content = (
            "def add(a, b):\n    return a + b\n\n"
            "def subtract(a, b):\n    return a - b\n"
        )

        # 1. 注册任务
        task = parse_result(
            task_mod.start_task(
                "创建计算器模块",
                ["写入 calculator.py", "验证文件", "验证内容"]
            )
        )
        task_id = task["task_id"]

        # 2. 步骤1：写入文件
        task_mod.update_progress(task_id, 0, "running", "开始写入")
        write_result = parse_result(shell_mod.write_file_safely(file_path, content))
        assert write_result["success"] is True
        task_mod.log_tool_call(task_id, 0, "write_file_safely",
                               {"path": file_path}, write_result, "success",
                               write_result["duration_s"])
        task_mod.update_progress(task_id, 0, "success", "文件已写入")

        # 3. 步骤2：验证文件存在
        task_mod.update_progress(task_id, 1, "running", "验证文件")
        exist_result = parse_result(verify_mod.verify_file_exists(file_path))
        assert exist_result["verified"] is True
        task_mod.update_progress(task_id, 1, "success", "文件验证通过")

        # 4. 步骤3：验证内容
        task_mod.update_progress(task_id, 2, "running", "验证内容")
        content_result = parse_result(
            verify_mod.verify_file_content(file_path, [r"def add", r"def subtract"])
        )
        assert content_result["verified"] is True
        task_mod.update_progress(task_id, 2, "success", "内容验证通过")

        # 5. 检查任务完成
        status = parse_result(task_mod.get_task_status(task_id))
        assert status["task"]["status"] == "completed"
        assert status["task"]["progress_percent"] == 100.0

        # 6. 检查执行日志
        log = parse_result(task_mod.get_execution_log(task_id))
        assert log["total_events"] >= 7  # 1 task_started + 3*2 step events


# ---------------------------------------------------------------------------
# 运行入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 简单运行器（无 pytest 依赖时）
    import traceback

    test_classes = [
        TestVerifyMCP, TestShellMCP, TestExplorerMCP,
        TestTaskProgressMCP, TestEndToEndScenarios
    ]

    total = 0
    passed = 0
    failed = 0

    for cls in test_classes:
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for method_name in methods:
            total += 1
            try:
                if hasattr(instance, "setup_method"):
                    instance.setup_method()
                getattr(instance, method_name)()
                passed += 1
                print(f"  PASS  {cls.__name__}.{method_name}")
            except Exception as e:
                failed += 1
                print(f"  FAIL  {cls.__name__}.{method_name}: {e}")
                traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print(f"{'='*60}")
    sys.exit(0 if failed == 0 else 1)
