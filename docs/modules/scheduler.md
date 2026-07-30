# scheduler/ - Scheduled Tasks

## What Is This Module?
Implements cron-like scheduled task execution. Users can schedule prompts to run at specific times.

## Key Files
| File | Purpose |
|------|---------|
| manager.py | TaskScheduler - main scheduler with cron parsing |
| cron.py | CronParser - parse and evaluate cron expressions |

## Core Code: manager.py (TaskScheduler)

**Features:**
- Cron expression support (minute, hour, day, month, weekday)
- Shorthand: @hourly, @daily, @weekly, @every 30m
- Task enable/disable toggle
- Run count and last-run tracking
- Persistent storage in ~/.rxycode/scheduler_tasks.json

**Key Methods:**
- add_task(cron_expr, prompt) -> Task: Create a scheduled task
- list_tasks() -> list[Task]: List all tasks
- remove_task(id) -> bool: Remove a task
- enable_task(id) / disable_task(id): Toggle task
- start(): Start the scheduler loop (runs in background thread)
- stop(): Stop the scheduler loop

## Core Code: cron.py
- parse_cron(expr) -> dict: Parse cron expression into components
- should_run(task, current_time) -> bool: Check if task should run now
- Supports: *, */N, ranges (1-5), lists (1,3,5), @hourly/@daily/@weekly
