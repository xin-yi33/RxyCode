"""Canonical /help text for HTTP /command (OpenTUI DialogDoc + Ink)."""

from __future__ import annotations

HELP_TEXT = """\
日常：直接输入需求即可。默认是单 Agent 写代码（Build），不会自动拉专家团。

专家团（默认关闭，约 3× token / 2.5× 时间，完成率不升）
  专家团 = 团长按 SOP 派角色（内置 software_dev：PM→架构→前后端→测试→验证→审计）。
  普通「帮我写/改代码」走单人工具循环，所以你看不到它。要用必须显式打开或强制本轮。
  /agents                 查看 enabled / team / route / 预算
  /agents on|off          总开关（关时设置页不显示专家团子项）
  /agents route auto|solo|team
  /agents team software_dev
  /team <可拆任务>        本轮强制专家团（不必先 on）
  /solo <任务>            本轮强制单 Agent
  /why-mode               上次为什么是 solo 或 team
  /team-multi <任务>      多模型协作尚未启用，按同模型专家团跑
  自动成团（on 且 route=auto）需要可拆信号：「前后端/多模块」、提示里 ≥4 个源文件、
  或「重构/迁移/设计」。单文件修 bug、小改动、只读问答保持单 Agent。

子代理（默认开启：task + @agent；子代再派子代仍关）
  /children               列出当前会话的子代理
  /child <session_id>     切到指定子代理
  /parent                 回到父代理
  话里带「同时/并行/分别/批量」才可能图内并行。关掉：RXYCODE_SUBAGENTS=0

工作模式
  /plan  只规划不落盘    /build  执行工具    /compose  多步编排
  /mode <build|plan|compose>    Tab 也可切换模式

会话
  /session  /clear  /save-chat  /load-chat  /list-chats  /copy

模型
  /models  /model [name]  /effort [档位]
  /addmodel - 打开安全模型接入向导（密钥不写入命令）

记忆 / Skills / MCP
  /memory add|list|remove|search <args>
  /find-skill <name>  /addskill <name|url>  /list-skills  /remove-skill <name>
  /addmcp <name> <cmd> [args]  /list-mcp  /remove-mcp <name>

系统
  /settings  /permission [confirm_all|auto_edit|full_auto]
  /language zh|en  /thinking  /cache  /queue  /schedule
  /tutorial  /quickstart  /examples  /help  /exit
"""


def build_help_text() -> str:
    return HELP_TEXT
