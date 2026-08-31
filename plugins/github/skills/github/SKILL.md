---
name: github
description: 用 gh 或官方 GitHub MCP 处理仓库、Issues、Pull Request 和 Actions。
---

# GitHub

用户提到 GitHub 仓库、Issue、Pull Request、Actions、release 或代码审查时使用本技能。

## 优先顺序

1. 本机有 `gh` 且 `gh auth status` 已登录时，优先用 `gh`（例如 `gh issue list`、`gh pr create`、`gh run list`）。不要把 token 写进命令行、仓库或回复。
2. 否则使用已连接的 GitHub MCP 工具。只调用服务器实际列出的工具，不要编造工具名。
3. 本地 MCP 由 `github-mcp-server stdio` 启动；没有该二进制时用 `docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server`。鉴权来自插件页保存的 PAT，或环境变量 `GITHUB_PERSONAL_ACCESS_TOKEN` / `GH_TOKEN`。

## MCP 工具集

以当前会话实际列出的工具为准。常见工具集包括 `context`、`issues`、`pull_requests`、`repos`、`actions`。写操作（建 Issue、开 PR）前先确认仓库与分支。

## 不要做

- 不要把 PAT 写进仓库、commit、日志或对用户的回复
- 不要假设远程 HTTP MCP（`api.githubcopilot.com`）已经接通；本插件走本地 stdio
