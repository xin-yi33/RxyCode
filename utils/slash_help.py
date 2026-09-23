"""Canonical /help text for HTTP /command (OpenTUI DialogDoc + Ink)."""

from __future__ import annotations

HELP_TEXT = """\
日常：直接输入需求即可。默认是单 Agent 写代码（Build），不会自动拉专家团。agents.enabled=true 或本会话说过「开专家团」后，自动在 solo / 专家团 / explore 之间选择。

专家团（默认关闭，约 3× token / 2.5× 时间；打开后才自动成团）
  专家团 = 团长按 SOP 派角色（内置 software_dev：PM→架构→前后端→测试→验证→审计）。
  普通问候、单文件修 bug、短问答仍走单人。跨层实现会松一些进团。
  /agents                 查看 enabled / team / route / 预算
  /agents on|off          总开关（关时设置页不显示专家团子项）
  /agents route auto|solo|team
  /agents team software_dev
  /team <可拆任务>        本轮强制专家团（不必先 on）
  /explore <只读问题>    本轮强制 explore 子代理（不必 @）
  /solo <任务>            本轮强制单 Agent
  /why-mode               上次为什么是 solo / team / explore
  /team-multi <任务>      多模型协作尚未启用，按同模型专家团跑
  也可以直接说「开专家团」「用explore」「用子代理」。自动成团信号：前后端/多模块/完整功能、
  提示里 ≥2 个源文件且要改代码、或「重构/迁移/设计」。查代码/代码在哪/为什么这样工作（不写文件）走 explore。

子代理（默认开启：task 常驻工具表 + @agent；子代再派子代仍关）
  /children               列出当前会话的子代理
  /child <session_id>     切到指定子代理
  /parent                 回到父代理
  说「用子代理」后本会话一直露出 task。图内并行仍看「同时/并行/分别/批量」，与 execution.parallel_enabled 无关。关掉：RXYCODE_SUBAGENTS=0

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

计算机控制（Computer Use）
  默认关。打开后模型看到 ocu 原名：list_apps / get_app_state / click / type_text / press_key / set_value / scroll / drag / perform_secondary_action，外加 browser_open / browser_snapshot / browser_act。
  打开：config.yaml computer_use.enabled=true 且 computer_use.approved=true，然后新开会话；或环境变量 RXYCODE_COMPUTER_USE=1。
  独立 MCP：npm i -g open-computer-use（MIT）。不要用 cli_list/cli_run 冒充。浏览器任务优先 browser_*（无障碍树），不要像素连点。

系统
  /settings  /permission [confirm_all|auto_edit|full_auto]
  /language zh|en  /thinking  /cache  /queue  /schedule
  /tutorial  /quickstart  /examples  /help  /exit
"""


def build_help_text() -> str:
    return HELP_TEXT
