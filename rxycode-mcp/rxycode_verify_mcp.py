#!/usr/bin/env python
"""
RxyCode 验证层 MCP 服务器 (rxycode-verify)
============================================
实现 ADR-001：验证层拦截幻觉性成功。

这是反腐败层（Anti-corruption Layer）—— 在 RxyCode 向用户报告"已创建文件"/"已运行测试"
等成功声明之前，必须调用本服务器的验证工具独立核查操作是否真正发生。

解决：P0-1 幻觉性成功（Agent 谎报任务完成）

设计原则：
  1. 永不信任声明 —— 所有声称的操作都要独立验证
  2. 返回结构化裁决 —— {verified, evidence, correction}
  3. 验证失败时给出修正声明 —— 告诉 Agent 应该说什么
  4. 无副作用 —— 验证操作不修改任何文件
"""

import os
import re
import json
import hashlib
import subprocess
import platform
from pathlib import Path
from datetime import datetime
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "rxycode-verify",
    instructions="RxyCode 验证层 —— 拦截幻觉性成功，独立核查所有成功声明",
)


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_stat(path: str) -> dict | None:
    """安全获取文件状态，不存在返回 None。"""
    try:
        st = os.stat(path)
        return {
            "exists": True,
            "size_bytes": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "is_file": os.path.isfile(path),
            "is_dir": os.path.isdir(path),
        }
    except (OSError, ValueError):
        return None


def _verdict(verified: bool, evidence: str, correction: str = "",
             details: dict | None = None) -> str:
    """构造结构化验证裁决（JSON 字符串）。"""
    result = {
        "verified": verified,
        "evidence": evidence,
        "correction": correction,
        "timestamp": _now(),
        "details": details or {},
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 验证工具
# ---------------------------------------------------------------------------

@mcp.tool()
def verify_file_exists(path: str) -> str:
    """验证文件是否真实存在。

    在 RxyCode 声称"已创建文件 X"或"文件 X 已更新"后调用此工具。
    独立检查文件系统，返回文件的真实元数据。

    Args:
        path: 要验证的文件绝对路径或相对路径

    Returns:
        JSON 裁决：verified=true 表示文件确实存在并附元数据；
        verified=false 表示文件不存在，correction 字段给出应向用户报告的修正声明。
    """
    abs_path = os.path.abspath(path)
    stat = _safe_stat(abs_path)

    if stat is None or not stat["exists"]:
        return _verdict(
            verified=False,
            evidence=f"文件系统检查：{abs_path} 不存在",
            correction=f"声明修正：文件 '{path}' 实际并不存在。请勿声称已创建该文件，"
                       f"应告知用户文件创建失败并重试。",
            details={"checked_path": abs_path},
        )

    if not stat["is_file"]:
        return _verdict(
            verified=False,
            evidence=f"{abs_path} 存在但不是文件（is_dir={stat['is_dir']}）",
            correction=f"声明修正：'{path}' 是目录而非文件，与「已创建文件」声明不符。",
            details=stat,
        )

    return _verdict(
        verified=True,
        evidence=f"文件 {abs_path} 确实存在，大小 {stat['size_bytes']} 字节，"
                 f"最后修改于 {stat['modified']}",
        details=stat,
    )


@mcp.tool()
def verify_file_content(path: str, expected_patterns: list[str]) -> str:
    """验证文件是否包含期望的内容模式。

    在 RxyCode 声称"文件 X 已包含函数 add/subtract/multiply"后调用此工具。
    读取真实文件内容，逐一检查期望的模式是否存在。

    Args:
        path: 文件路径
        expected_patterns: 期望在文件中出现的内容模式列表（正则或普通字符串）

    Returns:
        JSON 裁决：列出每个模式的匹配结果，全部匹配才 verified=true。
    """
    abs_path = os.path.abspath(path)
    stat = _safe_stat(abs_path)

    if stat is None or not stat.get("is_file"):
        return _verdict(
            verified=False,
            evidence=f"无法验证内容：文件 {abs_path} 不存在或不可读",
            correction=f"声明修正：无法验证 '{path}' 的内容，因为文件不存在。"
                       f"文件可能从未被真正创建。",
            details={"checked_path": abs_path},
        )

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        return _verdict(
            verified=False,
            evidence=f"读取文件失败：{e}",
            correction=f"声明修正：无法读取 '{path}'，文件可能已损坏或无权限。",
        )

    pattern_results = []
    all_matched = True
    for pattern in expected_patterns:
        found = bool(re.search(pattern, content))
        pattern_results.append({"pattern": pattern, "found": found})
        if not found:
            all_matched = False

    if all_matched:
        return _verdict(
            verified=True,
            evidence=f"文件 {abs_path} 包含全部 {len(expected_patterns)} 个期望模式",
            details={"pattern_results": pattern_results,
                     "file_size": len(content),
                     "preview": content[:200]},
        )
    else:
        missing = [r["pattern"] for r in pattern_results if not r["found"]]
        return _verdict(
            verified=False,
            evidence=f"文件 {abs_path} 缺少 {len(missing)} 个期望模式：{missing}",
            correction=f"声明修正：'{path}' 中并不包含声称的内容。"
                       f"以下内容未在文件中找到：{missing}。"
                       f"应告知用户文件内容与声明不符。",
            details={"pattern_results": pattern_results,
                     "actual_preview": content[:500]},
        )


@mcp.tool()
def verify_file_created(path: str, expected_patterns: list[str] | None = None) -> str:
    """验证文件是否被真正创建（组合验证：存在性 + 可选内容）。

    专用于"我已创建文件 X"这类声明。先验证文件存在，再验证内容（如指定）。

    Args:
        path: 声称创建的文件路径
        expected_patterns: 可选，期望文件包含的内容模式列表

    Returns:
        JSON 裁决。
    """
    existence = verify_file_exists(path)
    existence_data = json.loads(existence)

    if not existence_data["verified"]:
        return existence  # 文件不存在，直接返回失败裁决

    if expected_patterns:
        content = verify_file_content(path, expected_patterns)
        content_data = json.loads(content)
        if not content_data["verified"]:
            return content  # 内容不匹配

        return _verdict(
            verified=True,
            evidence=f"文件 '{path}' 存在且包含全部期望内容",
            details={"existence": existence_data["details"],
                     "content": content_data["details"]},
        )

    return existence


@mcp.tool()
def verify_command_executed(command: str, working_dir: str | None = None,
                            timeout: int = 30) -> str:
    """验证一个命令是否可以成功执行（实际重新执行）。

    在 RxyCode 声称"已运行 pytest 测试"或"已执行命令 X"后调用此工具。
    实际执行命令并捕获真实输出和退出码。

    注意：此工具会真实执行命令，仅用于验证幂等或只读命令。

    Args:
        command: 要验证的命令
        working_dir: 工作目录（可选，默认当前目录）
        timeout: 超时秒数（默认 30s）

    Returns:
        JSON 裁决：包含真实 exit_code、stdout（截断）、stderr（截断）。
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=working_dir or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        verified = (result.returncode == 0)
        evidence = (f"命令退出码: {result.returncode}（{'成功' if verified else '失败'}）\n"
                    f"stdout: {result.stdout[:500]}\n"
                    f"stderr: {result.stderr[:300]}")

        if verified:
            return _verdict(verified=True, evidence=evidence,
                            details={"exit_code": result.returncode,
                                     "stdout": result.stdout[:1000],
                                     "stderr": result.stderr[:500]})
        else:
            return _verdict(
                verified=False,
                evidence=evidence,
                correction=f"声明修正：命令 '{command}' 实际执行失败（退出码 {result.returncode}）。"
                           f"应告知用户执行失败及错误信息，而非声称成功。",
                details={"exit_code": result.returncode,
                         "stdout": result.stdout[:1000],
                         "stderr": result.stderr[:500]},
            )
    except subprocess.TimeoutExpired:
        return _verdict(
            verified=False,
            evidence=f"命令在 {timeout}s 内未完成（超时）",
            correction=f"声明修正：命令 '{command}' 执行超时，可能未真正完成。"
                       f"应告知用户操作超时。",
            details={"timeout": timeout},
        )
    except Exception as e:
        return _verdict(
            verified=False,
            evidence=f"命令执行异常：{e}",
            correction=f"声明修正：命令 '{command}' 无法执行：{e}",
        )


@mcp.tool()
def verify_test_passed(test_command: str, working_dir: str | None = None,
                       timeout: int = 60) -> str:
    """验证测试是否真正通过（实际运行测试并检查结果）。

    专用于"所有测试用例均通过"这类声明。实际执行测试命令，
    解析输出判断是否真正通过。绝不信任未执行的测试声明。

    Args:
        test_command: 测试命令，如 "pytest" 或 "python -m pytest test_calculator.py"
        working_dir: 工作目录
        timeout: 超时秒数（默认 60s）

    Returns:
        JSON 裁决：包含真实测试输出和通过/失败判定。
    """
    result_str = verify_command_executed(test_command, working_dir, timeout)
    result = json.loads(result_str)

    if not result["verified"]:
        # 命令本身失败，测试未通过
        details = result.get("details", {})
        return _verdict(
            verified=False,
            evidence=f"测试命令执行失败。{result['evidence']}",
            correction=f"声明修正：测试并未通过。命令 '{test_command}' 执行失败。"
                       f"应告知用户测试失败并附上真实输出，而非声称「所有测试通过」。",
            details=details,
        )

    # 命令成功退出，进一步解析输出确认测试真正通过
    stdout = result.get("details", {}).get("stdout", "")
    # pytest 常见通过模式
    pass_patterns = [
        r"\d+ passed",
        r"OK\b",
        r"Ran \d+ tests.*OK",
        r"Tests passed",
        r"PASSED",
    ]
    # pytest 常见失败模式
    fail_patterns = [
        r"\d+ failed",
        r"FAILED",
        r"ERROR",
        r"Traceback",
    ]

    has_pass = any(re.search(p, stdout) for p in pass_patterns)
    has_fail = any(re.search(p, stdout) for p in fail_patterns)

    if has_fail:
        return _verdict(
            verified=False,
            evidence=f"测试输出中检测到失败标记。输出：{stdout[:500]}",
            correction="声明修正：测试存在失败用例，并非「所有测试通过」。"
                       "应告知用户测试失败并附上失败详情。",
            details={"stdout": stdout[:1000]},
        )

    if has_pass:
        return _verdict(
            verified=True,
            evidence=f"测试输出确认通过。{stdout[:300]}",
            details={"stdout": stdout[:1000]},
        )

    # 退出码 0 但无明显通过/失败标记
    return _verdict(
        verified=True,
        evidence=f"测试命令退出码 0（退出码表示成功），但输出中未检测到明确的通过标记。"
                 f"输出：{stdout[:300]}",
        details={"stdout": stdout[:1000], "note": "建议人工确认输出"},
    )


@mcp.tool()
def fact_check_paths(paths: list[str]) -> str:
    """批量事实核查路径引用。

    在 RxyCode 描述项目结构或引用文件路径时调用此工具。
    检查所有引用的路径是否真实存在，消除"项目结构幻觉"。

    解决 P1-2：Agent 虚构不存在的目录和文件。

    Args:
        paths: 要核查的路径列表

    Returns:
        JSON 裁决：列出每个路径的存在状态，全部存在才 verified=true。
    """
    results = []
    all_exist = True
    for p in paths:
        abs_p = os.path.abspath(p)
        stat = _safe_stat(abs_p)
        exists = stat is not None and stat["exists"]
        results.append({
            "path": p,
            "resolved": abs_p,
            "exists": exists,
            "info": stat,
        })
        if not exists:
            all_exist = False

    if all_exist:
        return _verdict(
            verified=True,
            evidence=f"全部 {len(paths)} 个路径均存在",
            details={"paths": results},
        )
    else:
        missing = [r["path"] for r in results if not r["exists"]]
        return _verdict(
            verified=False,
            evidence=f"{len(missing)} 个路径不存在：{missing}",
            correction=f"声明修正：以下路径实际并不存在：{missing}。"
                       f"请勿在输出中描述这些路径的内容或结构，"
                       f"应先使用 codebase-explorer 工具获取真实文件列表。",
            details={"paths": results, "missing": missing},
        )


@mcp.tool()
def compute_file_hash(path: str, algorithm: str = "sha256") -> str:
    """计算文件哈希值，用于确认文件内容未被篡改。

    可用于验证"文件已更新"声明——对比更新前后的哈希值。

    Args:
        path: 文件路径
        algorithm: 哈希算法（sha256/md5，默认 sha256）

    Returns:
        JSON 包含文件哈希值，或错误信息。
    """
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        return _verdict(
            verified=False,
            evidence=f"文件不存在：{abs_path}",
            correction=f"无法计算哈希，文件 '{path}' 不存在。",
        )

    try:
        h = hashlib.new(algorithm)
        with open(abs_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return json.dumps({
            "path": abs_path,
            "algorithm": algorithm,
            "hash": h.hexdigest(),
            "timestamp": _now(),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _verdict(
            verified=False,
            evidence=f"计算哈希失败：{e}",
            correction=f"无法计算 '{path}' 的哈希值。",
        )


@mcp.tool()
def list_directory_real(path: str, recursive: bool = False,
                        max_depth: int = 3) -> str:
    """列出目录的真实内容（基于文件系统，非推测）。

    在描述目录结构前调用此工具获取真实文件列表。
    这是消除"项目结构幻觉"的基础工具。

    Args:
        path: 目录路径
        recursive: 是否递归列出
        max_depth: 递归最大深度（默认 3）

    Returns:
        JSON 包含真实的目录结构。
    """
    abs_path = os.path.abspath(path)
    if not os.path.isdir(abs_path):
        return _verdict(
            verified=False,
            evidence=f"目录不存在：{abs_path}",
            correction=f"目录 '{path}' 不存在，无法列出内容。",
        )

    entries = []

    def _scan(dir_path: str, depth: int):
        if depth > max_depth:
            return
        try:
            for name in sorted(os.listdir(dir_path)):
                full = os.path.join(dir_path, name)
                rel = os.path.relpath(full, abs_path)
                is_dir = os.path.isdir(full)
                entries.append({
                    "path": rel,
                    "type": "dir" if is_dir else "file",
                    "depth": depth,
                })
                if is_dir and recursive and depth < max_depth:
                    _scan(full, depth + 1)
        except PermissionError:
            pass

    _scan(abs_path, 1)

    return json.dumps({
        "root": abs_path,
        "entry_count": len(entries),
        "entries": entries,
        "timestamp": _now(),
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
