# scheduler/ - Scheduled Tasks

## What Is This Module?
Implements cron-like scheduled task execution. Users can schedule prompts to run at specific times.

## Key Files
| File | Purpose |
|------|---------|
| manager.py | ScheduledTaskManager - main scheduler with cron parsing |
| cron.py | CronExpression - parse and evaluate cron expressions |

## Core Code: manager.py (ScheduledTaskManager)

**Features:**
- Cron expression support (minute, hour, day, month, weekday)
- Shorthand: @hourly, @daily, @weekly, @monthly, @yearly, @annually, @every 30m
- Task enable/disable toggle
- Run count and last-run tracking (`last_status` / `last_result`)
- Each cron slot runs at most once per tick (`_claim_task` semantics)
- Persistent storage in `~/.RxyCode/scheduler_tasks.json` (path provided by
  `config.get_data_dir() / "scheduler_tasks.json"`)

OpenTUI `/loop` 的进程外时钟权威是 `appserver/schedule_service.py`（`schedule/create` + `restore_after_restart`，UPDATE-01 **U66**）。本包 `scheduler/` 是 Ink / `api_server.py` 的 cron 实现。禁止第三套 scheduler。禁止 `while True`。禁止把 Windows 任务计划当 P0。关窗后续跑 = 时钟恢复，不是复活被杀前台 bash。

**Key Methods:**
- add_task(cron_expr, prompt) -> Task: Create a scheduled task
- list_tasks() -> list[Task]: List all tasks
- get_task(id) -> Task: Look up a task
- remove_task(id) -> bool: Remove a task
- enable_task(id) / disable_task(id): Toggle task
- set_callback(cb): Register a run callback
- run_task(id): Run a task synchronously
- run_task_async(id): Run a task asynchronously (CancelledError -> `last_status="cancelled"`)
- start(): Start the scheduler loop (runs in background thread)
- stop(): Stop the scheduler loop

## Core Code: cron.py
- parse_cron(expr) -> CronExpression: Parse cron expression into a dataclass
- `CronExpression.matches(dt) -> bool`: Check if the expression fires at a datetime
- `CronExpression.next_run(after) -> datetime`: Compute the next fire time
- Supports: *, */N, ranges (1-5), lists (1,3,5), @hourly/@daily/@weekly/@monthly/@yearly/@every
