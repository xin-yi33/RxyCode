# Deterministic Test Fixtures

本目录保存 RxyCode 自己生成的最小确定性样本。它们用于普通 CI，不是线上请求日志，也不是从其他 Agent 仓库复制的 provider cassette。

## 目录

### `responses/`

Scripted LLM 响应数组。每一项会转换为一个 LangChain `AIMessage`：

```json
[
  {
    "content": "",
    "tool_calls": [
      {
        "name": "write",
        "args": {
          "filePath": "$artifact_path",
          "content": "$artifact_content"
        },
        "id": "call_write_1",
        "type": "tool_call"
      }
    ]
  },
  {
    "content": "Artifact created and verified.",
    "tool_calls": []
  }
]
```

`tests/conftest.py` 中的 `load_scripted_messages` 使用 `string.Template.safe_substitute`，只替换测试显式传入的变量。变量名使用稳定、可读的 snake_case；不得把环境变量或 secret 隐式注入 fixture。

### `sessions/`

会话存储、resume 和迁移样本。样本应使用固定名称、固定角色顺序和项目虚构内容，不包含真实用户对话、绝对用户目录或 access token。

### `artifacts/`

文件工具执行后的期望产物。内容应足够小，能通过完整内容或 SHA-256 验证。二进制或大型产物应由测试在临时目录生成，不提交到 fixtures。

## 更新流程

1. 先说明生产协议为何变化，并修改对应行为断言。
2. 用项目测试辅助代码生成候选 fixture，不直接保存 provider 原始响应。
3. 删除时间戳、随机 ID、token/cost、主机路径和非语义 metadata。
4. 搜索 `api_key`、`authorization`、`bearer`、cookie、邮箱和本机目录等敏感内容。
5. 运行消费该 fixture 的定向测试，再运行 `python -m pytest tests -m "not live and not pty"`。
6. 评审时同时检查 fixture diff 和生产协议 diff；普通 CI 不自动重写 golden 文件。

## 兼容性规则

- JSON 使用 UTF-8、两空格缩进和稳定字段顺序。
- Tool call 的 `name`、`args`、`id`、`type` 必须符合当前 LangChain 消息契约。
- 同一场景内 ID 固定且唯一；跨场景不依赖 ID 相等。
- 错误场景保存结构化错误类型和最小消息，不保存完整 provider stack 或 header。
- 如果未来增加 HTTP record/replay，必须先定义版本化 schema、匹配规则、脱敏器和 secret scanner；录制只能显式开启，CI 只能 playback。
