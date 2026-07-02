"""RxyCode Backend - 模块化单体后端架构

基于五层分离架构 (意图 -> 规划 -> 执行 -> 验证 -> 汇报) 重构,
修复用户反馈的 P0/P1 级后端 bug。

核心模块:
    core.environment   - 环境感知 (修复 P0-3 路径错误)
    core.shell         - Shell 抽象层 (修复 P0-2B 语法混淆)
    core.execution     - 执行层超时/重试/降级 (修复 P0-2A 超时)
    core.verification  - 验证层 (修复 P0-1 幻觉性成功)
    core.session       - 会话上下文隔离 (修复 P1-1 上下文泄露)
    core.tool_registry - 工具注册表
"""

__version__ = "0.4.0"
__all__ = ["core", "tools"]
