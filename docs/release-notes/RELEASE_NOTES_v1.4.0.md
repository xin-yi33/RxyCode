# RxyCode v1.4.0

打开终端，输入 `rxycode`。这一版只发命令行。桌面安装包没有跟上，还停在 [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0)。协议版本仍是 `1.1.0`。

> 整理稿里曾经写成 1.3.1。产品版本就是 **1.4.0**。

## 简要说明 / Summary

1.3.0 把桌面工作台交了出去。1.4.0 把终端里那个 agent 补到能长跑：上下文有一把尺子，会话会自己起名字，计划能批准再动手，网络抖一下会按同一张表重试。

- 新增：会话列表和自动标题，`/compact`，`/effort`，Computer Use，`final_answer`
- 新增：计划正文带标题，审批条才会出现；Shift+Enter / Ctrl+Enter 换行
- 修复：「不要写入文件」不再被证据门禁当成写任务；`/effort` 按 Esc 不再改成 default
- 修复：模型和读工具共用 5 次额外重试，间隔 2s / 4s / 8s / 16s / 30s
- 变更：GitHub Release **只上传 CLI sdist**，没有新的 Desktop exe / zip / AppImage

## 亮点 / Highlights

- **终端就是这一版的门面。** 不想装 Electron 也能用到会话、计划和重试。
- **换行终于是换行。** Windows 上 Shift+Enter 经常变成 `\r\n`，以前会直接发出去。现在它留在输入框里。
- **重试不再各说各话。** 模型网络失败和读工具失败用同一套次数和时间。
- **重复段落不再贴四遍。** 网关把整段又发来一次时，界面只留新的那一截。

## 详细说明 / Details

### 新增功能

- **上下文一把尺子** — `core/compaction.py` 的占用、微压缩和压缩阶梯。状态栏和 `/compact` 读同一套数字。
- **会话** — `core/session_list.py`、`core/session_title.py`。新窗口会记下来，标题由模型补。
- **计划审批** — `/plan` 的结果若没有 Markdown 标题会补上 `# 计划`，OpenTUI 打开已有的批准 / 拒绝条。
- **Computer Use 与收尾工具** — `core/cu/`、`tools/final_answer.py`、`tools/virtual_browser.py`、`tools/launch_intent.py`。
- **OpenTUI** — 工具卡片、计划面板、后续队列、会话列表。

### 修复的 Bug

- **Shift+Enter 发出去了** — ConPTY 把换行收成 CRLF。裸 CR 仍是发送，CRLF 是换行。
- **「不要写入文件」被要求写出文件** — 否定句先拿掉，后面还有肯定的写文件要求时门禁仍在。
- **子代理请求掉进只读 explore** — 提到子代理、并行或 Skill 时留在父代理，那边才有 `task` 和 `skill`。
- **`/effort` 不支持却改成 default** — 没有档位就显示不支持，Esc 只关闭。
- **同一段话贴四次** — 流式 `delta.content` 若是整段重发或全文快照，只追加新后缀。

### 变更

- 产品版本 **1.4.0**。协议版本保持 `1.1.0`。
- 本次 Release 资产是一个 `rxycode-1.4.0.tar.gz`。不发布 Desktop。

## 安装 / Install

```bash
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.4.0" rxycode
```

或：

```bash
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.0/install.sh | sh
rxycode
```

装完输入 `rxycode`。这是 OpenTUI，不是桌面程序。桌面端请继续用 v1.3.0 的安装包。

完整列表见 [CHANGELOG.md](../../CHANGELOG.md)。
