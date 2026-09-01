# log/ — process logging

## Purpose

Structured key=value logging with an 8-character run id, rotating file under
the user data dir, and secret redaction (`log.log_helpers.redact_sensitive`).

## Public surface

- `log.logger.setup_logging`
- `log.logger.get_logger`
- `log.log_helpers.redact_sensitive` / `classify_agent_result`

## Dependencies

Inbound: core, appserver, tools. Outbound: none (must not take a dependency on the graph).

## How to test

`pytest tests/test_log tests -k redact --timeout=180` (and plugin tests that
assert OAuth tokens never appear in `list_plugins` JSON).
