# history/ - File Change Tracking

## What Is This Module?
Tracks file modifications with diff generation (pure in-memory change tracking,
not command/conversation history). Used by edit/write tooling to snapshot
changes and produce unified diffs.

## Key Files
| File | Purpose |
|------|---------|
| tracker.py | `FileTracker` - records file modifications with diff generation; `ChangeRecord` - single file change snapshot; `get_file_tracker()` - process singleton |

## Core Code: tracker.py

**Tracked Events:**
- File reads (optional record)
- File writes and edits with before/after content snapshots
- Diff generation between snapshots

**Key Methods (FileTracker):**
- record_read(path): Optionally record a read
- record_write(path, content): Record a write change
- record_edit(path, old_text, new_text): Record a surgical edit change
- get_changes() -> list[ChangeRecord]: Retrieve all recorded changes
- get_diff_summary(path) -> str: Produce a unified diff for a file
- clear(): Clear history

There is no `log_command` / `log_tool_call` / `get_history` API and no
`~/.rxycode/history/` storage — this module is a lightweight in-memory diff
tracker, not a command/conversation history store.

User-visible Undo of files+messages is UPDATE-01 轨 J `session/revert` (git
best-effort) **while the process is alive**. Crash-safe before-images are
UPDATE-01 轨 K2 disk snapshots (`workspace_snapshot_store_is_durable()==True`).
`FileTracker` stays a process-local cache (`file_tracker_is_durable()==False`)
and must not keep unbounded full-file copies. See
[`../plans/opus5-plan/rxycode/research/2026-09-15-session-durability-snapshots-loop-timeout.md`](../plans/opus5-plan/rxycode/research/2026-09-15-session-durability-snapshots-loop-timeout.md).
