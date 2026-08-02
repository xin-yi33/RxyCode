# RxyCode v1.2.4

## 亮点 / Highlights

添加模型体验打磨、斜杠命令回车即执行；Phase 1 评测 harness 收口；Phase 2 类型化协议与 TypeScript JSON-RPC 客户端落地。

## 新增 / Added

- **斜杠回车执行** — 输入 `/addm` 等高亮建议后直接 Enter 执行（↑↓ 选择，Tab 仍可补全）
- **URL 推断服务商分组** — 自定义 endpoint 按 URL 归组；`/model` 按预设名 / 推断分组 / 其他
- **OpenCode Go 预设** — `https://opencode.ai/zen/go/v1`
- **Phase 1 eval harness** — 真实 AgentV2 流水线任务、tool_used 断言、baseline、夜间对比 CI
- **Phase 2 协议层** — 冻结 JSON schema + TS JSON-RPC 客户端与 CI gate

## 变更 / Changed

- 自定义「其他」路径：清空残留 Key、走批量 onboard；默认别名 = model id
- 确认添加模型时激活当前高亮项
- 一键安装默认钉死 **`v1.2.4`**
- **仅最新版开放安装包下载**；旧 Release 保留说明、移除 wheel/sdist

## 修复 / Fixed

- API Key 输入框明文光标
- 夜间 eval / live lane 的 CI secret 与 env 处理
- 安装与打包契约测试对齐 1.2.4

## 安装 / Install

**推荐（v1.2.4）：**

```powershell
# Windows
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.4/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.4/install.sh | sh
```

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.2.4"
```

**下载策略：** 仅本页（v1.2.4）提供 wheel / sdist。更早版本的 GitHub Release **不开放**安装包下载。

## 资产 / Assets

- `rxycode-1.2.4-py3-none-any.whl`
- `rxycode-1.2.4.tar.gz`
