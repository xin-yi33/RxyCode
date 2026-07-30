"""Few-shot examples for each pipeline stage.

Each example is a dict with ``input`` and ``output`` keys.
Examples are injected into the ``<EXAMPLES>`` XML section of role prompts.
"""

from __future__ import annotations

FEW_SHOT_EXAMPLES: dict[str, list[dict[str, str]]] = {
    "goal_planner": [
        {
            "input": "写一个 Python 爬虫，爬取豆瓣电影 Top 250",
            "output": (
                '{"goal": "实现豆瓣电影 Top 250 爬虫", '
                '"constraints": ["Python", "requests+bs4", "输出CSV"], '
                '"output_format": "code", "effect": "write"}'
            ),
        },
        {
            "input": "帮我分析这段代码的性能瓶颈",
            "output": (
                '{"goal": "分析代码性能瓶颈并给出优化建议", '
                '"constraints": ["分析现有代码", "给出具体优化方案"], '
                '"output_format": "markdown", "effect": "read"}'
            ),
        },
    ],
    "decomposer": [
        {
            "input": "Task: 实现用户注册登录系统",
            "output": (
                '[{"title": "设计数据库表结构", "description": "创建 users 表", '
                '"requirement": "包含 id, username, password_hash, email", '
                '"tools_hint": ["write"], "effect": "write", "depends_on_index": []}, '
                '{"title": "实现注册 API", "description": "POST /register", '
                '"requirement": "参数校验+密码哈希+写入数据库", '
                '"tools_hint": ["write", "bash"], "effect": "write", "depends_on_index": [0]}]'
            ),
        },
    ],
    "executor": [
        {
            "input": "Task: 创建 hello.py 打印 Hello World",
            "output": "print('Hello World')  # 使用 write 工具保存到 hello.py",
        },
    ],
    "validator": [
        {
            "input": "Task: 实现冒泡排序 | Result: def bubble_sort(arr)...",
            "output": (
                '{"passed": true, "completeness_score": 0.9, '
                '"relevance_score": 0.95, "format_score": 0.8, '
                '"issues": [], "suggestion": ""}'
            ),
        },
        {
            "input": "Task: 实现快速排序 | Result: (空结果)",
            "output": (
                '{"passed": false, "completeness_score": 0.0, '
                '"relevance_score": 0.0, "format_score": 0.0, '
                '"issues": ["结果为空，未产出任何代码"], '
                '"suggestion": "重新执行任务，生成快速排序实现"}'
            ),
        },
    ],
    "re_planner": [
        {
            "input": "Task: 实现用户认证 (失败: 缺少 JWT 签发逻辑)",
            "output": (
                '[{"title": "实现 JWT 签发函数", "description": "创建 generate_token(user_id)", '
                '"requirement": "使用 PyJWT，过期时间 24h", '
                '"tools_hint": ["write"], "effect": "write", "depends_on_index": []}, '
                '{"title": "实现认证中间件", "description": "解析 Authorization header", '
                '"requirement": "验证 Bearer token", '
                '"tools_hint": ["write"], "effect": "write", "depends_on_index": [0]}]'
            ),
        },
    ],
    "synthesizer": [
        {
            "input": "Tasks: [设计DB, 实现API, 编写测试] -> Results: [...]",
            "output": (
                "## 用户注册登录系统\n\n"
                "### 1. 数据库设计\n...\n"
                "### 2. API 实现\n...\n"
                "### 3. 测试覆盖\n..."
            ),
        },
    ],
    "subagent_decompose": [
        {
            "input": "Task: 实现一个博客系统，包含文章管理、用户认证、评论功能",
            "output": (
                '[{{"task": "设计数据库表结构（articles, users, comments）", '
                '"tools_hint": ["write"]}}, '
                '{{"task": "实现用户认证模块（注册/登录/JWT）", '
                '"tools_hint": ["write", "bash"]}}, '
                '{{"task": "实现文章 CRUD API", '
                '"tools_hint": ["write", "bash"]}}, '
                '{{"task": "实现评论功能模块", '
                '"tools_hint": ["write", "bash"]}}]'
            ),
        },
    ],
    "compose_plan": [
        {
            "input": "Task: 重构项目的配置管理模块，支持多环境配置",
            "output": (
                "1. 任务目标\n"
                "   重构 config/ 模块，支持 dev/staging/prod 多环境配置切换\n\n"
                "2. 执行步骤\n"
                "   a. 分析现有配置加载逻辑\n"
                "   b. 设计多环境配置架构\n"
                "   c. 实现 BaseConfig + 环境子类\n"
                "   d. 添加配置切换入口\n"
                "   e. 编写测试验证\n\n"
                "3. 具体操作\n"
                "   - 读取 config/settings.py 了解当前实现\n"
                "   - 创建 config/environments/ 目录\n"
                "   - 修改 load_config() 支持环境参数\n\n"
                "4. 预期结果\n"
                "   - config/ 可通过环境变量切换配置\n"
                "   - 所有测试通过\n"
            ),
        },
    ],
    "compose_build": [
        {
            "input": "Task: 按计划重构配置模块",
            "output": (
                "已按计划完成配置模块重构：\n"
                "- 创建了 config/environments/base.py\n"
                "- 创建了 config/environments/dev.py\n"
                "- 创建了 config/environments/prod.py\n"
                "- 修改了 config/settings.py 的 load_config()\n"
                "- 所有测试通过"
            ),
        },
    ],
}


def get_few_shot(key: str) -> list[dict[str, str]]:
    """Return few-shot examples for the given stage key."""
    return FEW_SHOT_EXAMPLES.get(key, [])


def format_few_shot(key: str) -> str:
    """Format few-shot examples as text for prompt injection."""
    examples = get_few_shot(key)
    if not examples:
        return ""
    parts = []
    for i, ex in enumerate(examples, 1):
        parts.append(f"Example {i}:\nInput: {ex['input']}\nOutput: {ex['output']}")
    return "\n\n".join(parts)
