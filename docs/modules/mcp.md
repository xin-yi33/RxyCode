# mcp/ - MCP Integration

## What Is This Module?
Implements Model Context Protocol (MCP) client for connecting to external MCP servers. MCP servers provide additional tools and resources to the agent.

## Key Files
| File | Purpose |
|------|---------|
| client.py | MCPClient - connects to MCP servers and exposes their tools |

## Core Code: client.py (MCPClient)

**How MCP Works:**
1. MCP servers are configured in `config.yaml` under `mcpServers`.
2. `MCPClient` launches each stdio server with an argv list (`shell=False`).
3. A dedicated stdout reader dispatches newline-delimited UTF-8 JSON-RPC
   responses while a separate thread drains bounded/redacted stderr logs.
4. The client performs `initialize`, validates the negotiated protocol, sends
   `notifications/initialized`, and discovers every paginated `tools/list` page.
5. Server tools become LangChain `StructuredTool` objects, but are registered
   only in `ToolOrchestrator`. Calls therefore retain the central approval,
   timeout, audit, evidence, cancellation, and side-effect-journal path.
6. `AgentV2` keeps a fingerprint for each configured server and checks the
   on-disk MCP config before every request. Adds, removals, per-server edits,
   disconnects, and `tools/list_changed` notifications refresh only affected
   process/tool registrations; unchanged healthy clients survive unrelated
   failures and edits.
7. A failed server exposes no stale tools and enters per-fingerprint
   exponential backoff (5 seconds initially, doubling to a 300-second cap).
   Calls during the cooldown skip reconnection; changing that server's config
   resets its backoff and makes it immediately eligible.

**Key Methods:**
- `connect()`: start, initialize, negotiate, and discover tools
- `get_tools()`: return validated discovered tools
- `call_tool(name, args)`: JSON-Schema validate, invoke with a real request
  deadline, and return bounded/redacted content
- `disconnect()`: unblock requests and terminate the complete process tree
- `load_mcp_servers(config)`: return lifecycle-owned clients and tools

**Configuration:**
- `mcpServers` in `config.yaml`: `{name: {type, command, args, env, timeout}}`
- Only `type: stdio` is currently supported. Commands and arguments are never
  shell-concatenated. The child inherits only the official SDK-style safe OS
  allowlist plus explicitly configured `env` values. Environment values are
  never returned by `runtime_status()`.
- MCP annotations are untrusted. Dynamic names default to `WRITE`; a positive
  `destructiveHint` can only escalate the local minimum to `DANGER`, while a
  remote `readOnlyHint` can never lower it. Normal approval rules still apply.
- Configured MCP commands are trusted host processes, not OS-sandboxed child
  workloads. `runtime_status()` reports `process_isolation=host_process`
  explicitly. Operators that need process/container isolation should configure
  a sandbox launcher such as Docker as the command and pass its arguments in
  `args`.
- Aggregate runtime status also reports `backoff_servers` and the nearest
  `next_retry_seconds`. It does not expose config fingerprints, commands,
  arguments, environment values, or server content.

The wire implementation follows the current
[MCP stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
and mirrors the lifecycle ownership shown by the official
[Python SDK stdio client](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/clients/stdio_client.py).
