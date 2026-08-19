# PhaseG-H2 luna 审计

- 模型：`gpt-5.6-luna`
- 网关：OpenCode Go `https://opencode.ai/zen/go/v1/responses`
- **VERDICT: PASS**（经 FAIL 多轮修改后通过）

对照 H2：initialize/initialized、版本范围 1.0.0–1.1.0、capability 仅 `true`、JSON-RPC 稳定码分类（含 -32008 overloaded）、ClientTransport close/cancel、未改 schema。
