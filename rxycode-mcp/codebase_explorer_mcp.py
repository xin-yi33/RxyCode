#!/usr/bin/env python
"""
代码库探测 MCP 服务器 (codebase-explorer)
==========================================
实现 ADR-001 事实核查 —— 消除项目结构幻觉。

强制 Agent 在描述项目结构前先探测真实文件系统。
解决 P1-2：Agent 虚构不存在的目录（如 Minecraft-Unity、Minecraft-Web）。

设计原则：
  1. 事实锚定 —— 所有项目描述必须基于真实文件系统探测
  2. 先探测后描述 —— 绝不允许基于"推测"描述文件内容
  3. 结构化输出 —— 返回真实的文件树、项目类型、技术栈
"""

import os
import json
from pathlib import Path
from datetime import datetime
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "codebase-explorer",
    instructions="代码库探测 —— 基于真实文件系统的项目结构分析，消除幻觉",
)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 常见忽略目录
DEFAULT_IGNORE_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv",
    "venv", "env", ".env", ".tox", ".pytest_cache", ".mypy_cache",
    ".idea", ".vscode", "dist", "build", "target", ".next", ".nuxt",
    "coverage", ".coverage", "htmlcov", ".eggs", "*.egg-info",
}

# 项目类型检测规则（文件名/目录名 → 项目类型）
PROJECT_TYPE_MARKERS = {
    "python": ["setup.py", "pyproject.toml", "requirements.txt", "setup.cfg",
               "Pipfile", "tox.ini", "conftest.py"],
    "node": ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
    "typescript": ["tsconfig.json"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts", "gradle.properties"],
    "csharp": ["*.csproj", "*.sln", "ProjectSettings", "Assembly-CSharp.csproj"],
    "go": ["go.mod", "go.sum"],
    "rust": ["Cargo.toml", "Cargo.lock"],
    "ruby": ["Gemfile", "Gemfile.lock", "Rakefile"],
    "php": ["composer.json", "artisan"],
    "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
    "unity": ["ProjectSettings", "Assets", "Library"],
    "web": ["index.html", "webpack.config.js", "vite.config.js", "vite.config.ts"],
}

# 技术栈文件标记
TECH_STACK_MARKERS = {
    "pytest": ["pytest.ini", "conftest.py", "pyproject.toml"],
    "docker": ["Dockerfile", "docker-compose.yml"],
    "kubernetes": ["k8s", "deploy.yaml", "deployment.yaml"],
    "ci_github": [".github/workflows"],
    "ci_gitlab": [".gitlab-ci.yml"],
    "database": ["migrations", "alembic", "prisma"],
}


# ---------------------------------------------------------------------------
# 内部函数
# ---------------------------------------------------------------------------

def _should_ignore(name: str, ignore_patterns: set[str]) -> bool:
    """判断文件/目录是否应被忽略。"""
    for pattern in ignore_patterns:
        if pattern.startswith("*"):
            if name.endswith(pattern[1:]):
                return True
        elif name == pattern:
            return True
    return False


def _scan_tree(root: str, max_depth: int, ignore_dirs: set[str],
               ignore_patterns: set[str], current_depth: int = 0) -> list[dict]:
    """递归扫描目录树。"""
    entries = []
    if current_depth >= max_depth:
        return entries

    try:
        for name in sorted(os.listdir(root)):
            if _should_ignore(name, ignore_dirs) or _should_ignore(name, ignore_patterns):
                continue

            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, root)
            is_dir = os.path.isdir(full_path)

            entry = {
                "name": name,
                "path": rel_path,
                "type": "dir" if is_dir else "file",
                "depth": current_depth + 1,
            }

            if not is_dir:
                try:
                    entry["size_bytes"] = os.path.getsize(full_path)
                    ext = os.path.splitext(name)[1].lower()
                    if ext:
                        entry["extension"] = ext
                except OSError:
                    pass
            else:
                entry["children"] = _scan_tree(
                    full_path, max_depth, ignore_dirs, ignore_patterns,
                    current_depth + 1
                )

            entries.append(entry)
    except PermissionError:
        pass

    return entries


def _count_entries(tree: list[dict]) -> dict:
    """统计文件树中的文件数和目录数。"""
    files = 0
    dirs = 0
    extensions = {}

    def _count(nodes):
        nonlocal files, dirs
        for node in nodes:
            if node["type"] == "file":
                files += 1
                ext = node.get("extension", "(无扩展名)")
                extensions[ext] = extensions.get(ext, 0) + 1
            elif node["type"] == "dir":
                dirs += 1
                _count(node.get("children", []))

    _count(tree)
    return {"files": files, "dirs": dirs, "extensions": extensions}


def _detect_project_type(root: str) -> list[dict]:
    """基于真实文件检测项目类型。"""
    detected = []
    try:
        top_level = set(os.listdir(root))
    except OSError:
        return detected

    for project_type, markers in PROJECT_TYPE_MARKERS.items():
        matched_markers = []
        for marker in markers:
            if marker.startswith("*"):
                # 通配符匹配
                suffix = marker[1:]
                for item in top_level:
                    if item.endswith(suffix):
                        matched_markers.append(item)
            elif marker in top_level:
                matched_markers.append(marker)

        if matched_markers:
            detected.append({
                "type": project_type,
                "confidence": "high" if len(matched_markers) >= 2 else "medium",
                "evidence": matched_markers,
            })

    return detected


def _detect_tech_stack(root: str) -> list[str]:
    """检测技术栈。"""
    stack = []
    try:
        items = os.listdir(root)
    except OSError:
        return stack

    for tech, markers in TECH_STACK_MARKERS.items():
        for marker in markers:
            if marker in items:
                if tech not in stack:
                    stack.append(tech)
                break

    return stack


# ---------------------------------------------------------------------------
# MCP 工具
# ---------------------------------------------------------------------------

@mcp.tool()
def scan_project_tree(root: str, max_depth: int = 3,
                      ignore_dirs: list[str] | None = None,
                      ignore_patterns: list[str] | None = None) -> str:
    """扫描项目的真实文件树。

    在描述项目结构前必须调用此工具获取真实文件列表。
    解决 P1-2：Agent 虚构不存在的目录（如 Minecraft-Unity）。

    返回基于文件系统的真实目录树，包含文件大小、扩展名统计。
    绝不返回推测的内容。

    Args:
        root: 项目根目录路径
        max_depth: 最大扫描深度（默认 3）
        ignore_dirs: 额外要忽略的目录名列表
        ignore_patterns: 额外要忽略的文件模式列表（如 ["*.log"]）

    Returns:
        JSON 包含真实文件树和统计信息。
    """
    abs_root = os.path.abspath(root)
    if not os.path.isdir(abs_root):
        return json.dumps({
            "success": False,
            "error": f"目录不存在：{abs_root}",
            "suggestion": "请确认路径正确，或使用 detect_environment 获取当前用户目录。",
        }, ensure_ascii=False, indent=2)

    all_ignore_dirs = DEFAULT_IGNORE_DIRS.copy()
    if ignore_dirs:
        all_ignore_dirs.update(ignore_dirs)

    all_ignore_patterns = set(ignore_patterns or [])

    tree = _scan_tree(abs_root, max_depth, all_ignore_dirs, all_ignore_patterns)
    stats = _count_entries(tree)

    return json.dumps({
        "success": True,
        "root": abs_root,
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "max_depth": max_depth,
        "stats": {
            "file_count": stats["files"],
            "dir_count": stats["dirs"],
            "extensions": dict(sorted(stats["extensions"].items(),
                                      key=lambda x: -x[1])),
        },
        "tree": tree,
        "warning": "此文件树基于真实文件系统扫描，可直接引用。"
                   "描述项目结构时必须以此为准，不得推测。",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def detect_project_type(root: str) -> str:
    """检测项目的真实类型和技术栈。

    基于真实文件存在性判断（setup.py → Python，package.json → Node 等），
    而非基于文件名推测。

    解决 P1-2：之前 Agent 声称有 Unity 项目但实际不存在。

    Args:
        root: 项目根目录

    Returns:
        JSON 包含检测到的项目类型、置信度和证据文件。
    """
    abs_root = os.path.abspath(root)
    if not os.path.isdir(abs_root):
        return json.dumps({
            "success": False,
            "error": f"目录不存在：{abs_root}",
        }, ensure_ascii=False, indent=2)

    project_types = _detect_project_type(abs_root)
    tech_stack = _detect_tech_stack(abs_root)

    return json.dumps({
        "success": True,
        "root": abs_root,
        "detected_types": project_types,
        "tech_stack": tech_stack,
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "note": "项目类型基于真实文件检测，非推测。",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def list_real_files(pattern: str, root: str | None = None,
                    recursive: bool = True) -> str:
    """列出匹配模式的真实文件。

    使用 glob 模式匹配真实文件，绝不返回虚构的文件。
    用于验证"项目中包含 X 文件"类声明。

    Args:
        pattern: glob 模式，如 "**/*.py" 或 "*.json"
        root: 搜索根目录（默认当前目录）
        recursive: 是否递归搜索（** 模式）

    Returns:
        JSON 包含匹配的真实文件列表。
    """
    search_root = os.path.abspath(root or os.getcwd())
    if not os.path.isdir(search_root):
        return json.dumps({
            "success": False,
            "error": f"目录不存在：{search_root}",
        }, ensure_ascii=False, indent=2)

    import glob
    if recursive and "**" not in pattern:
        full_pattern = os.path.join(search_root, "**", pattern)
    else:
        full_pattern = os.path.join(search_root, pattern)

    matches = glob.glob(full_pattern, recursive=recursive)

    # 过滤忽略目录
    filtered = []
    for m in sorted(matches):
        parts = Path(m).parts
        if any(part in DEFAULT_IGNORE_DIRS for part in parts):
            continue
        filtered.append({
            "path": os.path.relpath(m, search_root),
            "absolute": m,
            "size_bytes": os.path.getsize(m) if os.path.isfile(m) else None,
        })

    return json.dumps({
        "success": True,
        "pattern": pattern,
        "root": search_root,
        "match_count": len(filtered),
        "matches": filtered,
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def verify_path_exists(path: str) -> str:
    """验证路径是否真实存在。

    在引用任何文件/目录路径前调用此工具确认存在性。
    解决 P1-2：输出中引用的文件路径自动验证存在性。

    Args:
        path: 要验证的路径

    Returns:
        JSON 包含路径存在状态和元数据。
    """
    abs_path = os.path.abspath(path)
    exists = os.path.exists(abs_path)

    result = {
        "path": path,
        "resolved": abs_path,
        "exists": exists,
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
    }

    if exists:
        result["is_file"] = os.path.isfile(abs_path)
        result["is_dir"] = os.path.isdir(abs_path)
        if result["is_file"]:
            result["size_bytes"] = os.path.getsize(abs_path)
            result["extension"] = os.path.splitext(abs_path)[1]
        elif result["is_dir"]:
            try:
                result["entry_count"] = len(os.listdir(abs_path))
            except OSError:
                result["entry_count"] = None
    else:
        result["warning"] = (
            "此路径不存在。请勿在输出中引用或描述此路径的内容。"
            "如需了解真实项目结构，请使用 scan_project_tree。"
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def search_codebase(query: str, root: str | None = None,
                    file_pattern: str = "*", max_results: int = 20) -> str:
    """在真实文件内容中搜索代码。

    搜索实际文件内容，而非推测。返回包含查询的真实文件和匹配行。

    Args:
        query: 搜索关键词或正则表达式
        root: 搜索根目录（默认当前目录）
        file_pattern: 文件名过滤模式（默认 *，即所有文件）
        max_results: 最大返回结果数（默认 20）

    Returns:
        JSON 包含匹配的文件和行内容。
    """
    import re
    search_root = os.path.abspath(root or os.getcwd())
    if not os.path.isdir(search_root):
        return json.dumps({
            "success": False,
            "error": f"目录不存在：{search_root}",
        }, ensure_ascii=False, indent=2)

    results = []
    query_re = None
    try:
        query_re = re.compile(query, re.IGNORECASE)
    except re.error:
        # 非正则，按普通字符串处理
        pass

    for dirpath, dirnames, filenames in os.walk(search_root):
        # 跳过忽略目录
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_IGNORE_DIRS]

        for filename in filenames:
            if not _matches_pattern(filename, file_pattern):
                continue

            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, search_root)

            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, 1):
                        matched = False
                        if query_re:
                            if query_re.search(line):
                                matched = True
                        elif query.lower() in line.lower():
                            matched = True

                        if matched:
                            results.append({
                                "file": rel_path,
                                "line": line_num,
                                "content": line.rstrip()[:200],
                            })
                            if len(results) >= max_results:
                                return json.dumps({
                                    "success": True,
                                    "query": query,
                                    "root": search_root,
                                    "result_count": len(results),
                                    "results": results,
                                    "truncated": True,
                                }, ensure_ascii=False, indent=2)
            except (OSError, UnicodeDecodeError):
                continue

    return json.dumps({
        "success": True,
        "query": query,
        "root": search_root,
        "result_count": len(results),
        "results": results,
        "truncated": False,
    }, ensure_ascii=False, indent=2)


def _matches_pattern(filename: str, pattern: str) -> bool:
    """简单 glob 匹配。"""
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)


@mcp.tool()
def get_file_summary(path: str, max_lines: int = 50) -> str:
    """获取真实文件的摘要信息。

    读取真实文件的前 N 行和元数据，而非推测文件内容。
    用于"读取并解释文件 X"类任务。

    Args:
        path: 文件路径
        max_lines: 读取的最大行数（默认 50）

    Returns:
        JSON 包含文件元数据和内容摘要。
    """
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        return json.dumps({
            "success": False,
            "error": f"文件不存在：{abs_path}",
            "suggestion": "使用 list_real_files 查看可用文件。",
        }, ensure_ascii=False, indent=2)

    stat = os.stat(abs_path)
    ext = os.path.splitext(abs_path)[1]

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line.rstrip())
    except OSError as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "path": abs_path,
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "success": True,
        "path": abs_path,
        "size_bytes": stat.st_size,
        "extension": ext,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "line_count_shown": len(lines),
        "content_preview": "\n".join(lines),
        "note": "文件内容来自真实读取，非推测。",
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
