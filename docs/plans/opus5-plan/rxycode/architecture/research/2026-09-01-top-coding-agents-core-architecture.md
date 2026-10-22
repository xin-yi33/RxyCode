# 高星 coding agent 核结构调研（拆不拆上帝文件）

> **日期**：2026-09-01  
> **问题**：别人 core 里会不会留一个 6000+ 行文件硬写、不拆？  
> **方法**：GitHub 树 / 官方 ARCHITECTURE / 二次拆解文 / 仓内 `research/2026-08-08-8-projects-value-report.md`。star 为检索快照，不是 SPDX。  
> **禁止**：逆向闭源二进制当实现依据。Claude Code 只引用他人已公开的目录描述。

## 结论

**没有**「前 20 编码 agent 靠单文件 6000+ 行循环硬写还宣传可维护」的成功样板。  
体量大的项目用 **目录 / crate / 包** 切开 session、tools、sandbox、surface。  
个别仍有厚文件（Cline `Task` ~3756 行、Aider `base_coder.py` ~2k 行、OpenHands 曾报 `agent_controller.py` >1400 行）——维护者把它当 **债**，会开 issue 要拆，不当美德。  
RxyCode `core/agent_v2.py` ≈ 6850 行且测试直绑，**必须按缝拆**；方法是已有 `Session` 假面软连接，不是一次性重写。本目标不执行拆代码。

对照 Hermes：二次拆解称其 god file ~9000 行，被当作反面教材，不是抄作业对象。

## 表（≥20）

| # | 项目 | 约 star | 核怎么放 | 最大单文件量级（公开描述） | 对拆 agent_v2 |
|---|------|--------|----------|------------------------------|----------------|
| 1 | anomalyco/opencode | 148k–172k | `packages/opencode/src/session/`：prompt/processor/compaction 分文件 | 循环在 `prompt.ts` 等，不是单核全能 py | 拆 session 包 |
| 2 | google-gemini/gemini-cli | ~105k | CLI 包拆分 tools/config | 未见 6k 行单核宣传 | 模块化 CLI |
| 3 | openai/codex | ~90–120k | `codex-rs/core` ~15 万行但 **子目录** session/tools/sandboxing/agent/mcp/plugins；另 tui/app-server crate | 循环在 session/turn，不是单文件 6800 | **主参照**：大体量靠边界 |
| 4 | anthropics/claude-code（公开部分） | 高 | 他人 map：QueryEngine / tools / bridge 分文件（不把逆向当实现） | 工程按工具与查询引擎切开 | 表面可观察：斜杠与工具分模块 |
| 5 | cline/cline | ~61–67k | `src/core/{controller,task,webview}`；SDK 后 `@cline/core` vs `@cline/agents` | `Task` ~3756 行被拆解文称 god object | **反面**：厚文件是债 |
| 6 | OpenHands/OpenHands | ~72–85k | controller / runtime / event_stream / agenthub | `agent.py` ~191 行；controller 曾 >1400 并有拆分 issue | runtime 不进 loop 文件 |
| 7 | aaif-goose/goose | ~48–54k | Rust + MCP 扩展 | 能力外挂 | 外挂优于塞进核文件 |
| 8 | Aider-AI/aider | ~46–49k | `coders/` 子类拆编辑格式；io/commands/repo 分文件 | `base_coder.py` 约 2k 行级 | 编排可稍厚，仍远小于 6850 |
| 9 | continuedev/continue | ~33–36k | IDE 扩展：core vs GUI | 分包 | 表面/核分离 |
| 10 | Roo-Code（Cline fork） | ~22k | 同 Cline 模块树 | 同 Cline 债 | 勿复制 Task 上帝类 |
| 11 | Kilo-Code | ~15–20k | 多 IDE 包 | 平台化分模块 | 分表面 |
| 12 | charmbracelet/crush | ~20–25k | Go TUI 包 | 按 TUI 惯例拆 | 表面≠核 |
| 13 | SWE-agent/SWE-agent | ~18–20k | 环境 / agent / 历史分模块 | 研究型也拆 | 论文级拆法 |
| 14 | mini-SWE-agent | 中 | 默认 agent **约 100 行**（项目自述） | 循环薄是卖点 | 循环应薄 |
| 15 | Open Interpreter | ~62k | 终端解释器 + 工具 | 核与工具分离 | 工具不进上帝文件 |
| 16 | plandex-ai/plandex | ~15k | Go；计划/diff 沙箱 | 计划对象独立 | Plan 一等 |
| 17 | ByteDance DeerFlow | ~80k 量级 | checkpoint + event log 双写；controller 与 runtime | 仓内 08-08 报告 | 事件与 loop 分离 |
| 18 | FoundationAgents/MetaGPT | ~70k | SOP/角色分模块 | 08-08 报告 | 编排表而非一文件 |
| 19 | microsoft/autogen | ~48k | agent runtime 包 | 多包 | 不堆单文件 |
| 20 | openai/codex app-server 侧 | 同上仓 | JSON-RPC app-server crate ~4 万行级 | 协议与核 crate 分离 | 对齐 RxyCode appserver |
| 21 | iFurySt/open-codex-computer-use | ~1.9k | **CU 专用 MCP**，不进宿主 loop | 跨平台 runtime 独立进程 | CU **Adopt 此仓**，不写进 agent_v2 |
| 22 | pi / dsh（PHASE-K 调研） | — | 内核小、能力外挂 | 08-17 插件报告 | 能力开关不改 S1 |

## 对 ARCH-004 的一句话

拆核 = 学 Codex/OpenCode 的 **目录边界**，避免 Cline Task / 未拆的 agent_v2。软连接走现有 `core/session.py`。
