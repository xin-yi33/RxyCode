你是 Phase G 前端卡审计员（gpt-5.6-luna）。只审计 PhaseG-H2。不要把 H3–H19 未做项判为 H2 失败。

# 规范

PHASE-G-FRONTEND.md PhaseG-H2 + DC-J1/J2/J3/J4 + §1.2 白名单 + §3.1 ClientTransport。
完整基线 G2：initialize/initialized、版本范围、client/server capability、stable error code、timeout、closed、unsupported、overloaded、configuration missing、protocol mismatch。
H2 协议变化：none。禁止改 protocol/schema.json 或 appserver。B2 若未冻结新 error schema，前端只能映射已有 JSON-RPC 码，不得发明 schema 字段。

必须实现：typed 状态；未声明能力不显示入口；错误可区分 retry / user / unrecoverable。
验收：pytest tests/test_protocol；protocol-client npm test。

# 相对上次 FAIL 的修复

1. 握手成功后发送 `initialized` 通知；失败不发送。
2. 具名 `PROTOCOL_VERSION_MIN/MAX` + `isValidProtocolVersion`；非法 SemVer 拒绝；`initializeHandshake` 用 versionRange 协商。
3. 删除 `data.error_code`。timeout/closed 用客户端类 `ProtocolTimeoutError` / `ProtocolDisconnectError`，不是 schema 字段。
4. 稳定 JSON-RPC 码：-32601 user unsupported、-32602/-32002 user config、其余码（含 -32000）unrecoverable。未知码不标 retry。
5. `ProtocolClient.close()` 置 closed、拒绝 pending 与后续 request，统一 `connection_closed`。
6. UI：`useModels` 未声明 models 不请求；`App.tsx` SessionList/ApprovalModal 经 `isUiEntryEnabled`；auto_review/multi_agent 无入口。

再修：
- overloaded 映射现有 JSON-RPC **-32008**（B2 JSONRPC_STABLE_CODE / OVERLOADED，retry），未改 schema。
- SemVer：拒绝前导零 `01.2.3`；允许 `1.1.0-beta.1` / `1.1.0+build.1`；非法版本 → protocol_mismatch，不抛异常。
- 版本范围 MIN=1.0.0 MAX=1.1.0。

再修：
- `initialized` 无参数，不发明 protocol_version 字段。
- 非字符串/非法版本一律 protocol_mismatch，compare 前类型检查。
- prerelease 按 SemVer 逐段比较（beta.2 < beta.10）。
- 删除未使用的 expectedProtocolVersion。

bun test handshake+error 16 pass。

# 输出

第一行 VERDICT: PASS 或 VERDICT: FAIL
然后逐条对照 H2 必须实现与 DC-J1/J3。FAIL 时只给 H2 规范内的必改项。
