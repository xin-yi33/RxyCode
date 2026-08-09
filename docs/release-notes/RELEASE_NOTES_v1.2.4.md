# RxyCode v1.2.4

## 简要说明 / Summary

这一版打磨"添加模型"体验，并让常用操作更顺手：

- 输入 `/addm` 等高亮建议后直接按回车即可执行，无需手动点击
- 添加模型时按服务商自动分组展示，支持一键填入预设 URL
- 内置 OpenCode Go 预设，开箱即用

## 亮点 / Highlights

- **斜杠命令回车即执行** — 输入 `/addm` 等高亮建议后直接 Enter 执行（↑↓ 选择，Tab 仍可补全）
- **URL 推断服务商分组** — 自定义 endpoint 按 URL 自动归组；`/model` 按预设名 / 推断分组 / 其他展示
- **OpenCode Go 预设** — 内置 `https://opencode.ai/zen/go/v1`，添加模型一步到位

## 详细说明 / Details

### 添加模型

- 自定义「其他」路径：清空残留 Key、走批量导入；默认别名 = model id
- 确认添加模型时自动激活当前高亮项
- API Key 输入框明文光标显示

### 质量保障

- 评测体系落地：真实流水线任务、工具调用断言、基线对比、夜间自动对比 CI
- 前后端协议层落地：冻结 JSON Schema + TypeScript JSON-RPC 客户端与 CI 门禁

### 发布策略

- 一键安装默认钉死 **`v1.2.4`**
- **仅最新版开放安装包下载**；旧 Release 保留说明、移除 wheel/sdist

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
