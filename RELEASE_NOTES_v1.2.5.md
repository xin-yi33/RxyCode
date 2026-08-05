# RxyCode v1.2.5

RxyCode 是一个规划-执行型的 AI 编程助手：把复杂任务自动拆解成子任务，通过安全工具编排器执行、验证结果后综合出最终答案，全程实时流式输出到终端界面。

## 简要说明 / Summary

这一版聚焦三件事：**更好的模型适配、更快的启动、更稳的界面**。

- 深度适配 DeepSeek / 通义千问 / Claude 等模型，Token 统计与上下文窗口更准确
- 界面与核心之间的通信协议升级，交互更快更稳
- 启动速度明显提升，冷启动更快进入对话
- 文件修改类请求自动走完整的"分析—规划—执行—验证"流水线

## 亮点 / Highlights

- **模型支持更广、更准** — 新增 DeepSeek、通义千问（Qwen）、Anthropic Claude 的适配层：思考模式识别、1M 超大上下文窗口、缓存命中计费、中文分词估算等均按各家规范解析，不再一刀切
- **界面更流畅** — OpenTUI 默认改用本地 stdio 通道与核心通信（HTTP 保留为回退），审批交互更可靠，后端报错不再刷到聊天屏幕上
- **启动更快** — 消除核心模块循环依赖、收敛延迟导入，冷启动耗时下降
- **更懂你要改什么** — 显式请求路由：识别"改一下这个文件 / 这段代码"的意图时走完整流水线，而不是简单问答
- **小但重要的修复** — 沙箱路径逃逸、API Key 读取兜底、思考开关跨对话保持

## 详细说明 / Details

### 模型与适配

- **DeepSeek**：自动识别思考型模型（thinking 模式）、1M 上下文窗口、缓存命中计费、温度参数按需生效
- **通义千问（Qwen）**：中文分词启发式估算、缓存字段解析、混合思考模型支持
- **Anthropic Claude**：适配框架落地，为后续完整支持铺路
- **Token 统计**：按模型规格解析 tokenizer，计数失败时自动兜底，不阻塞对话
- **提示词查找**：Prompt 模板支持按对话阶段 / 界面语言 / 模型变体查找与自动回退

### 界面与交互（OpenTUI）

- 默认使用 stdio JSON-RPC 通信，HTTP 传输保留为回退方案
- 修复审批请求生命周期问题
- 后端 stderr 不再直接打印到界面
- 思考（思维链）展开开关在多次提问之间保持

### 架构与性能

- 请求路由模块化：显式路由指令替代硬编码关键词
- 核心包循环依赖清零，延迟 import 收敛到 50 以下（有回归测试守护）
- API 服务端瘦身为纯 HTTP/SSE 适配器，统一走会话门面

### 安全与修复

- 修复 readcode / workdir 类任务可能逃出工作目录沙箱的执行路径
- API Key 读取支持 secret 兜底（环境变量为空时自动回退）
- 版本打包契约测试对齐 1.2.5

### 质量保障

- 评测系统支持并行门禁编排与单任务超时
- OpenTUI stdio 传输补充集成与回归测试覆盖

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
