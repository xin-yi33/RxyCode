# RxyCode v1.4.3

2026-10-14。产品版本 **1.4.3**。JSON-RPC 仍是 `1.1.0`。这次只发布 CLI / OpenTUI 源码包 `rxycode-1.4.3.tar.gz`，不发布新的 Desktop 安装包。

桌面安装包仍在 [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10)。

## 安装

```bash
uv tool install --force --refresh "git+https://github.com/xin-yi33/RxyCode.git@v1.4.3"
```

或：

```bash
python -m pip install --no-cache-dir --force-reinstall rxycode-1.4.3.tar.gz
```

Windows：

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.3/install.ps1 | iex"
```

macOS / Linux：

```bash
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.3/install.sh | sh
```

## 这次你能直接感觉到的变化

### 工具 schema 变小，MCP 按需出现

每轮请求里的 schema 仍是内置工具加上 `tool_search`。MCP、插件，以及 `download_skill`、`download_mcp`、`team_install`，不进这份 schema。

模型用 `tool_search` 按关键词取出完整定义。定义留在原来的历史消息里。同一个消息上下文里不会重复发送。清空历史、批准计划进入 Build、切换会话、载入另一份对话，或者另一个隔离子任务，才会重新给出定义。

完整 discovery 不再被普通输出去重吞掉，也不再被默认 2000 字符截断切碎。

### 写完代码，结果里带着检查

`write_file` 落盘之后会做语法检查。Python 再跑 `ruff` 的 `F` 和 `E9`，未定义的名字会以「第 N 行第 M 列」回到同一次工具结果。JavaScript 在有 `node` 时用 `node --check`。检查失败不会把已经写下的文件撤回去。

### 系统破坏命令不会执行

Linux、macOS、Windows 上会毁掉系统的命令在进入 shell 之前拒绝。`full_auto` 和人工批准都不能放行。

包括对根目录、系统目录和用户主目录的递归删除，格式化磁盘，`dd` 写设备，关机重启，把下载内容直接送进 shell，以及 Windows 上的 `format`、`bcdedit /set`、结束 `lsass` 这类关键进程。

`rm -rf ./build` 这种项目里的相对清理不在黑名单里。

### 长输出只留首尾

命令输出超过 200 行时，上下文保留开头 50 行和结尾 50 行。全文在 spill 文件里，结果会告诉模型用 `read` 去读。单行很长、但不超过 200 行，不走这次按行截断。

### 每次工具调用都能查

审计记录包含时间、脱敏参数、截断结果、耗时、会话和上下文，以及这次为什么被放行。指标汇总调用次数、成功率和平均耗时。同一工具连续失败 3 次、超时，或输出落盘失败，会写一条告警。审计失败不会打断工具本身。

## 协议

JSON-RPC 兼容版本没有改，仍是 `1.1.0`。

开发过程里的逐条记录见 [CHANGELOG_v1.4.3.md](CHANGELOG_v1.4.3.md)。上一版说明见 [RELEASE_NOTES_v1.4.2.md](RELEASE_NOTES_v1.4.2.md)。
