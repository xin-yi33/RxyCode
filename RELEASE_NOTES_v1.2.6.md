# RxyCode v1.2.6

RxyCode 是一个规划-执行型的 AI 编程助手：把复杂任务自动拆解成子任务，通过安全工具编排器执行、验证结果后综合出最终答案，全程实时流式输出到终端界面。

> **推荐使用 v1.2.6。** v1.2.5 存在几个影响日常使用的已知问题（联网读取部分网页会报解码错误、询问 MCP 相关内容可能被误判为"安装 MCP 服务"、中文 Windows 下工具输出乱码等），本版已全部修复并通过回归测试。

## 简要说明 / Summary

这一版是**可靠性修复版**：聚焦修复真实使用中暴露的问题，让联网读取、命令执行、意图识别更稳更准。

- 修复联网读取网页时的压缩解码错误，网页抓取不再失败
- 修复对话中提及 MCP 可能被误当成"安装 MCP 服务"的误判
- 修复中文 Windows 下命令输出乱码
- 优化 Windows 下的命令适配，Agent 写的小型 bash 习惯命令也能正确执行
- 修复了内部评测与 CI 中发现的不稳定问题，构建发布更稳

## 亮点 / Highlights

- **网页抓取更可靠** — 修复了部分网页因压缩编码导致的读取失败，联网搜索与网页阅读更稳
- **意图识别更精准** — 只有明确说"安装 / 添加某个 MCP 服务"时才会触发安装流程；只是**询问或解释** MCP 相关话题不会再误触安装
- **中文不乱码** — 中文 Windows 下命令执行结果优先按 UTF-8 解码，乱码问题解决
- **命令执行更省心** — Windows 下自动把 `ls -la`、多行文本、`&` 连接符等小习惯转成等价 PowerShell 写法，Agent 写命令不用再"切换心智"

## 详细说明 / Details

### 修复的 Bug

- **网页抓取解码错误（webfetch）** — 读取部分启用 brotli/gzip 压缩的网页时报 `brotli: decoder failed`，导致抓取失败。现在已正确识别压缩内容，不再二次解码。
- **MCP 误判（请求路由）** — 之前问"什么是 MCP 协议 / MCP 是做什么的"这类解释性问题，有可能被识别为"下载安装 MCP 服务"，从而在配置里静默添加一个 npx MCP 服务。现在只有包含明确安装动词（下载 / 安装 / 添加 / install / add 等）的句子才会走安装流程。
- **命令输出中文乱码（shell 工具）** — 中文 Windows（zh-CN）下执行命令的输出被按 GBK 解码导致乱码。现在优先按 UTF-8 解码，仅在确实无法解码时才回退到系统默认编码。
- **Windows 命令适配（shell 工具）** — Agent 习惯写的小型 POSIX 命令在 Windows 上会失败，现在自动翻译：
  - `ls -la` → `Get-ChildItem -Force`
  - 多行 heredoc 文本 → PowerShell here-string
  - 单独的 `&` 连接符 → `;`
- **稳定性修复（构建与发布）** — 修复了前端 stdio 通信测试与安装脚本测试中的不稳定问题，CI 与发布流程更稳。

### 验证与回归

- 后端修复相关测试、安装脚本测试、打包契约测试全部通过
- 前端 Ink 界面 1502 项测试、OpenTUI 界面 128 项测试全部通过
- 两个前端项目的 TypeScript 类型检查通过

## 安装 / Install

**推荐（v1.2.6）：**

```powershell
# Windows
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.6/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.6/install.sh | sh
```

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.2.6"
```

**下载策略：** 仅本页（v1.2.6）提供 wheel / sdist。更早版本的 GitHub Release **不开放**安装包下载。

## 资产 / Assets

- `rxycode-1.2.6-py3-none-any.whl`
- `rxycode-1.2.6.tar.gz`
