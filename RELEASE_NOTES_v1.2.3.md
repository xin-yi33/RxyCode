# RxyCode v1.2.3

## 亮点 / Highlights

OpenCode 式「连接服务商」添加模型流程全面升级：预设服务商 discover 后**多选批量入库**，`/model` 按服务商分组展示。

## 新增 / Added

- **预设批量入库** — discover 成功后默认全选模型，一次 `POST /models/onboard/batch` 写入（`skip_probe=true`，不逐个 chat 探活）
- **`POST /models/onboard/batch`** — 批量添加 API，返回 `{added, skipped, active, message}`
- **`GET /models` category** — 每条模型带 `category`（来自 `provider_name`），供 `/model` 分组
- **10 个主流服务商预设** — `GET /models/presets`，仅含 provider + base URL，不含 model id
- **模型发现** — `POST /models/discover` 只读查询厂商目录，失败时结构化 `error_code`
- **最近常用** — `config.recent_models` + `GET /models` 的 `recent` 字段
- **`DialogSelect` 多选模式** — 空格勾选、Enter 确认批量
- **模型元数据** — `provider_id` / `provider_name` 持久化到配置

## 变更 / Changed

- **预设路径跳过昵称** — discover → 多选 → batch；自定义 URL 仍单条 onboard + 探活
- **`/model` 按服务商分组** — 最近常用 / DeepSeek / … / 其他 / 操作
- **`/addmodel` 向导** — 统一 `DialogSelect` / `DialogPrompt` 交互（搜索、↑↓、Esc、鼠标 hover）

## 修复 / Fixed

- discover **auth/transport** 失败回到 Key 屏；仅 `unsupported_catalogue` 才进手填 model id
- 自定义 URL **非 HTTPS 本地拒绝**
- 模型列表 **Esc 回退一步** 而非直接关闭
- discover 错误 **结构化分流**（`error_code`）

## 安装 / Install

**推荐（v1.2.3）：**

```powershell
# Windows
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.3/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.3/install.sh | sh
```

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.2.3"
```

**上一版仍可下载（本次特例）：** [v1.2.2](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.2) 的 wheel / sdist 继续保留。安装上一版：

```bash
RXYCODE_VERSION=1.2.2 curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.2/install.sh | sh
# 或
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.2.2"
```

## 资产 / Assets

- `rxycode-1.2.3-py3-none-any.whl`
- `rxycode-1.2.3.tar.gz`
