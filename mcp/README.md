# MCP Runtime

This module connects configured Model Context Protocol stdio servers to the
production Agent tool path.

`MCPClient` uses the MCP 2025-11-25 newline-delimited UTF-8 JSON-RPC transport.
It owns the subprocess, reader and stderr threads, initialization/version
negotiation, paginated tool discovery, request deadlines, disconnect cleanup,
input JSON-Schema validation, and bounded output rendering. It deliberately
does not use the old LSP-style `Content-Length` framing.

`load_mcp_servers()` converts validated remote tools into LangChain
`StructuredTool` objects. `AgentV2` loads them at initialization and checks the
on-disk `mcpServers` configuration before every request. It keeps a fingerprint
per server and refreshes only added, removed, changed, disconnected, or
`tools/list_changed` servers. Unchanged healthy clients and their registered
tools retain object/process identity when another optional server fails or is
edited. A broken or changed server exposes no stale tools.

Connection failures are tracked per server and per current fingerprint. Retry
delay starts at 5 seconds, doubles after each failure, and is capped at 300
seconds; requests during that cooldown do not pay the server's connection
timeout again. Changing the server configuration resets its backoff and makes
it immediately eligible. Therefore a successful `download_mcp` change is live
on the next request without restarting the process, while an unrelated healthy
server is not restarted.

Dynamic tools are registered directly with `ToolOrchestrator`, not invoked from
the MCP adapter. This preserves the shared permission, timeout, audit, evidence,
cancellation, and crash-safe side-effect journal. MCP tool names are unknown to
the static policy table and fail closed to `WRITE` risk. A positive remote
`destructiveHint` raises that local minimum to `DANGER`; `readOnlyHint` is never
trusted to downgrade it.

The process receives only the official SDK-style safe OS environment allowlist
plus explicitly configured `env` values. It still runs as a trusted host
process: RxyCode does not claim an OS sandbox around arbitrary MCP commands.
Use a container/sandbox launcher as the configured command when stronger
process isolation is required.

Runtime status is intentionally aggregate-only: configured server count,
connected server count, exposed tool count, sanitized error types,
`backoff_servers`, and the nearest `next_retry_seconds`, plus the non-secret
trust-boundary labels `host_process` and `safe_allowlist_plus_explicit`. It never
returns command lines, arguments, environment variables, responses, or config
fingerprints.
