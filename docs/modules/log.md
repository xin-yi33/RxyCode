# log/ — process logging

## Purpose

Structured key=value logging with an 8-character run id, one timestamped file
per run under the user data dir, and secret redaction
(`log.log_helpers.redact_sensitive`).

Each `setup_logging` call (i.e. each agent run) writes a new file named
`rxycode_YYYY-MM-DD_HH-MM-SS_<runid>.log` (RotatingFileHandler, 10MB x 5).
Retention is a 72h sliding window (`RXYCODE_LOG_RETENTION_HOURS` overrides):
every access to the log directory — `setup_logging` and
`log.logger.list_log_files` — first sorts files by their *filename* timestamp
(not mtime) and prunes those older than 72h; files inside the window, files
without a parseable timestamp, and non-log files are never deleted. The naming,
sorting and pruning rules live in `log/rotator.py` (pure, separately testable).

## Public surface

- `log.logger.setup_logging` / `log.logger.get_logger` / `log.logger.list_log_files`
- `log.rotator` — `new_log_path`, `iter_log_files_sorted`, `prune_old_logs`,
  `list_log_files`, `parse_log_timestamp`, `RETENTION_HOURS`
- `log.log_helpers.redact_sensitive` / `classify_agent_result`

## Dependencies

Inbound: core, appserver, tools. Outbound: none (must not take a dependency on the graph).

## How to test

`pytest tests/test_log tests/test_core/test_logging.py --timeout=180` — includes
three E2E suites for the 72h retention system
(`tests/test_log/test_log_rotator.py`): real `setup_logging` write+prune,
same-second/multi-process runs with stable timestamp sorting, and the exact-72h
boundary semantics. Plus plugin tests that assert OAuth tokens never appear in
`list_plugins` JSON.
