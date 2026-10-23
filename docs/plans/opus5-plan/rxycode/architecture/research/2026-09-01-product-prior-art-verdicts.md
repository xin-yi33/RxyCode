# 备忘愿望 prior-art Verdict（写 PHASE-P 卡面前）

> **日期**：2026-09-01  
> **纪律**：PC0 — 写施工卡之前必须有 Verdict。Build 是最后一档。  
> **方法**：本仓对照 + GitHub / 注册表 + 备忘已列 skill + 本机闭源只抄可观察交互。  
> **快照**：公开 star / 许可以检索当日页面为准，不是核验级 SPDX。

| 备忘愿望 | Verdict | 证据 |
|----------|---------|------|
| 斜杠定死 skill | **Adopt** — shimo4228/search-first + obra/superpowers using-superpowers | 两条 SOP 互补；斜杠强制走 skill，正文仍渐进披露。本机已有 using-superpowers |
| 沙箱 + 访问档 | **Extend** — OpenAI Codex 公开 sandbox 文档 + OpenHands runtime（Docker）+ 本仓 `core/safety/` | 不自造隔离内核；在 isolation 缝接真执行隔离与档位 UX。白名单不是终点 |
| 结构化补丁 + 红绿 | **Extend** — Codex `apply_patch` 形态 + Aider editblock/udiff + OpenCode/Grok 对话流 diff | 替换 `tools/edit.py` 字符串替换为可审补丁；呈现抄开源 TUI，不嵌别人循环 |
| hooks | **Adopt** — Codex `hooks.json` 事件→shell（PHASE-K K14 已立项） | 网装默认关；不自创事件名除非 K14 表没有 |
| Computer Use | **Extend** — [iFurySt/open-codex-computer-use](https://github.com/iFurySt/open-codex-computer-use)（~1.9k★，MCP+CLI，macOS AX / Linux AT-SPI / Windows UIA） | **禁止自研跨平台 CUA**。RxyCode 做开关、前缀 L0/L1、CLI/GUI 对等。`cli_list`/`cli_run` 并存不得替代 |
| 加号已装插件 / 标签 / 旧会话 | **Build** 信息架构 — 本机闭源观察：Codex Desktop 加号三页 | 宿主仍用 PHASE-K plugin/*；第一屏不是 skill/MCP。无开源「加号组件」可整包装 |
| `/goal` 对象 | **Extend** — PHASE-N N4–N6 | 不另做存储；禁 localStorage 前缀 |
| `/goal` UX | **Build** 表面 — 本机闭源观察：Codex 目标模式侧栏 | 抄可观察交互 |
| Plan 模式 | **Extend** — 本仓 `appserver/plan_files.py` + Codex Plan 可观察门 | 未批准禁写项目文件 |
| Grok Build SOP | **Adopt** — Grok Build Plan/Search/Build 节拍 | 接到 goal，不发明第三套流水线 |
| GitHub 内嵌浏览器 | **Extend** — iFurySt 亦指向 open-browser-use；系统 WebView/CDP 优先于自带 Chromium | P2 |
| GUI 终端 | **Extend** — node-pty / 本机终端面板惯例 | P1 可降级为事件可见+外开 |
| 审计可见 diff | **Compose** — 与结构化补丁同一呈现 | 主去向 PP21 |
| 侧边聊天 | **Extend** — 本仓 `appserver/side_chat.py` + Cursor/Grok `/btw` 可观察 | P2 |
| 子代理点进 | **Extend** — Phase D/E 运行时 + OpenCode TUI 展开 | 只补表面 |
| 加内置团 | **Extend** — 本仓 `software_dev` + PHASE-L L11 矩阵 + WorkBuddy 可观察规模 | YAML 落盘；不进自动索引直到 L12 |

`open-codex-computer-use` 工具面（README）：`list_apps` `get_app_state` `click` `scroll` `drag` `type_text` `press_key` `set_value`。以无障碍树为主，符合「事实观察」。
