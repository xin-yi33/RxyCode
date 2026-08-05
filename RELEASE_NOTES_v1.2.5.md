# RxyCode v1.2.5

## 亮点 / Highlights

Phase 2 收口：OpenTUI 全面切到 stdio JSON-RPC、消除关键词路由、收敛延迟 import、`api_server` 变薄为适配器；Phase A 模型适配层落地，接入 DeepSeek / Anthropic / Qwen 等 Provider 与能力驱动解析。

## 新增 / Added

- **Phase A 模型适配层** — LLM 构造统一走 Provider 层：`DeepSeekProvider`（reasoner 感知）、`AnthropicProvider` / `QwenProvider`、tokenizer spec 解析器、usage/reasoning 提取委托到 Provider、prompt (stage, locale, variant) 查找与回退
- **Phase 2 收口** — `protocol/` + `appserver` stdio JSON-RPC 全线贯通；OpenTUI 默认 stdio 传输（`RXYCODE_TRANSPORT=stdio`）
- **请求路由模块** — `core/request_routing.py` 显式路由指令，消除硬编码关键词；文件+修改意图请求走完整 pipeline
- **并发门禁编排** — `evals` 并行 gate 编排脚本与每任务超时
- **OpenTUI 迁移** — approval 生命周期修复、transport CI 覆盖、stderr 不再上屏

## 变更 / Changed

- **`api_server.py` 变薄** — SSE transport 与 model-onboarding 端点拆到独立模块，核心走 `Session` 门面
- **延迟 import 收敛** — `core/` 内部循环依赖清除，延迟 import 降到 50 以下（回归守卫 `test_lazy_import_budget` 通过）
- **一键安装默认钉死 `v1.2.5`**
- **仅最新版开放安装包下载**；v1.2.4 及其更早 Release 保留说明、移除 wheel/sdist

## 修复 / Fixed

- readcode / workdir 任务在 sandbox 外的执行路径
- 带 API key secret 回退的配置读取（`api_key_secret` 兜底）
- appserver 思考开关跨 prompt 持久化
- 版本打包契约测试对齐 1.2.5

## 安装 / Install

**推荐（v1.2.5）：**

```powershell
# Windows
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.5/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.5/install.sh | sh
```

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.2.5"
```

**下载策略：** 仅本页（v1.2.5）提供 wheel / sdist。更早版本的 GitHub Release **不开放**安装包下载。

## 资产 / Assets

- `rxycode-1.2.5-py3-none-any.whl`
- `rxycode-1.2.5.tar.gz`
