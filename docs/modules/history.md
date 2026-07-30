# history/ - History Tracking

## What Is This Module?
Tracks command and conversation history for replay and analysis.

## Key Files
| File | Purpose |
|------|---------|
| tracker.py | HistoryTracker - logs commands, tool calls, and responses |

## Core Code: tracker.py

**Tracked Events:**
- User inputs with timestamps
- Tool calls with arguments and results
- LLM responses with token usage
- Mode switches and command executions

**Key Methods:**
- log_command(command, result): Log a command execution
- log_tool_call(name, args, result): Log a tool call
- get_history(limit) -> list: Retrieve recent history
- clear(): Clear history
- Storage: ~/.rxycode/history/
