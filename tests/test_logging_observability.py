"""
Logging observability fixes — verifies issues #3 / #5 / #6 from the log audit.

#6: /status and /models heartbeat request logs are downgraded to DEBUG, so they
    stop flooding the log every 30s and hiding real events. The decision lives in
    the module-level QUIET_PATHS set consumed by the request-logging middleware.
#5: chat requests log the (truncated) prompt + mode, and completions log an
    (truncated) answer preview; failures log the error. Implemented as pure
    helpers (_log_chat_request / _log_chat_completed / _log_chat_error) so the
    endpoint stays thin and the behavior is unit-testable.
#3: the startup model label is resolved from config (not the misleading literal
    "default"); _do_init additionally logs the real model name.

Run with:
    PYTHONPATH="D:/agent-demo/RxyCode:D:/agent-demo/RxyCode/RxyCode1_1_0" \
        /d/Anaconda3/python.exe -m pytest tests/test_logging_observability.py -q
"""
import sys

for _p in ("D:/agent-demo/RxyCode", "D:/agent-demo/RxyCode/RxyCode1_1_0"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PKG = "RxyCode.RxyCode1_1_0"


def test_quiet_paths_include_heartbeats():
    """#6: heartbeat endpoints are in QUIET_PATHS (downgraded to DEBUG)."""
    import importlib
    helpers = importlib.import_module(f"{PKG}.log.log_helpers")
    assert "/status" in helpers.QUIET_PATHS
    assert "/models" in helpers.QUIET_PATHS


def test_log_chat_request_logs_prompt_and_mode():
    """#5: request logging captures the prompt (truncated) + mode."""
    import importlib
    helpers = importlib.import_module(f"{PKG}.log.log_helpers")
    logger = MagicMock()
    msg = "帮我用Python写一个跑酷小游戏"
    helpers.log_chat_request(logger, "build", msg)
    extra = logger.info.call_args.kwargs["extra"]
    assert extra["prompt"] == msg
    assert extra["mode"] == "build"
    assert extra["prompt_len"] == len(msg)


def test_log_chat_completed_logs_truncated_preview():
    """#5: completion logging truncates the answer preview to 200 chars."""
    import importlib
    helpers = importlib.import_module(f"{PKG}.log.log_helpers")
    logger = MagicMock()
    long = "x" * 500
    helpers.log_chat_completed(logger, "build", long)
    extra = logger.info.call_args.kwargs["extra"]
    assert extra["answer_preview"] == "x" * 200
    assert extra["answer_len"] == 500


def test_log_chat_error_logs_detail():
    """#5: agent failure is logged at ERROR with the detail string."""
    import importlib
    helpers = importlib.import_module(f"{PKG}.log.log_helpers")
    logger = MagicMock()
    helpers.log_chat_error(logger, "build", RuntimeError("boom-detail-123"))
    extra = logger.error.call_args.kwargs["extra"]
    assert "boom-detail-123" in extra["error"]
    assert extra["mode"] == "build"


@pytest.mark.parametrize(
    ("result", "expected_status"),
    [
        ("normal answer", "succeeded"),
        ("[cancelled]", "cancelled"),
        ("[workflow cancelled]", "cancelled"),
        ("[Build paused at ~30s] budget reached", "timed_out"),
        ("[error: tool 'read' timed out after 3s]", "timed_out"),
        ("[search error: All engines failed or timed out]", "timed_out"),
        ("[workflow timeout: script took too long]", "timed_out"),
        ("[no input: question timed out]", "timed_out"),
        ("Download failed: Connection timed out (30s)", "timed_out"),
        ("[task_stall_timeout] no progress", "timed_out"),
        ("[task_max_time] maximum elapsed time reached", "timed_out"),
        ("[stall] Task 'build' did not complete normally.", "timed_out"),
        ("[max_time] Task 'build' did not complete normally.", "timed_out"),
        ("[agent error: boom]", "failed"),
        ("[agent error] boom", "failed"),
        ("[Pipeline error] recursion", "failed"),
        ("[Build failed after ~12s] graph exploded", "failed"),
        ("[Build incomplete: No completed tasks to synthesize.]", "failed"),
        ("[Executor error] RuntimeError: boom", "failed"),
        ("[evidence failed: invalid HTML artifact]", "failed"),
        ("[error] file not found", "failed"),
        ("[error executing bash: boom]", "failed"),
        ("[blocked: write path not allowed]", "failed"),
        ("[rejected: no approval broker available]", "failed"),
        ("[rejected by user: bash]", "failed"),
        ("[dry-run] not executed", "failed"),
        ("[max tool-call rounds reached]", "failed"),
        ("[workflow error: boom]", "failed"),
        ("Error: Invalid URL format", "failed"),
        ("Download failed: HTTP Error 404", "failed"),
        ("Failed to install skill 'review': unavailable", "failed"),
        (
            "I could not verify the requested current information from external sources, so I will not guess.",
            "failed",
        ),
    ],
)
def test_classify_agent_result_distinguishes_terminal_states(result, expected_status):
    import importlib
    helpers = importlib.import_module(f"{PKG}.log.log_helpers")

    assert helpers.classify_agent_result(result)[0] == expected_status


@pytest.mark.parametrize(
    ("result", "expected_status"),
    [
        ("tool output", "success"),
        ("[blocked: write path not allowed]", "error"),
        ("[workflow cancelled]", "error"),
        ("[error: formatter timed out (30s)]", "timeout"),
    ],
)
def test_tool_display_status_never_presents_non_success_as_success(
    result, expected_status
):
    import importlib
    helpers = importlib.import_module(f"{PKG}.log.log_helpers")

    assert helpers.tool_display_status(result) == expected_status


def test_chat_logging_redacts_secrets_and_includes_request_run_id():
    import importlib
    helpers = importlib.import_module(f"{PKG}.log.log_helpers")
    logger = MagicMock()
    secret = "sk-" + "abcdefghijklmnopqrstuvwxyz" + "123456"

    helpers.log_chat_request(logger, "build", f"token={secret}", run_id="run-123")
    request_extra = logger.info.call_args.kwargs["extra"]
    assert request_extra["run_id"] == "run-123"
    assert secret not in request_extra["prompt"]
    assert "[REDACTED]" in request_extra["prompt"]

    helpers.log_chat_error(logger, "build", RuntimeError(f"Authorization: Bearer {secret}"), run_id="run-123")
    error_extra = logger.error.call_args.kwargs["extra"]
    assert error_extra["run_id"] == "run-123"
    assert secret not in error_extra["error"]


def test_run_monitor_aggregates_terminal_states_without_content():
    import importlib
    monitor_module = importlib.import_module(f"{PKG}.log.monitor")
    monitor = monitor_module.RunMonitor()

    monitor.record("run-ok", "succeeded", 1.5)
    monitor.record("run-fail", "failed", 0.5)
    snapshot = monitor.snapshot()

    assert snapshot["total_runs"] == 2
    assert snapshot["status_counts"] == {"succeeded": 1, "failed": 1}
    assert snapshot["average_duration_s"] == 1.0
    assert snapshot["last_run"] == {"run_id": "run-fail", "status": "failed", "duration_s": 0.5}
    assert "prompt" not in str(snapshot).lower()
    assert "answer" not in str(snapshot).lower()


def test_run_monitor_deduplicates_observers_and_counts_evidence():
    import importlib
    monitor_module = importlib.import_module(f"{PKG}.log.monitor")
    monitor = monitor_module.RunMonitor()

    monitor.record_evidence(
        "run-shared",
        {
            "status": "failed",
            "executed": True,
            "artifacts": [{"exists": True, "valid": False}],
        },
    )
    monitor.record("run-shared", "failed", 0.25)
    monitor.record("run-shared", "failed", 0.5)

    snapshot = monitor.snapshot()
    assert snapshot["total_runs"] == 1
    assert snapshot["status_counts"] == {"failed": 1}
    assert snapshot["tool_evidence"] == {"total": 1, "failed": 1}
    assert snapshot["artifact_evidence"] == {"total": 1, "failed": 1}
    assert snapshot["last_run"]["tool_evidence"] == {
        "total": 1,
        "failed": 1,
    }


def test_run_monitor_aggregates_plan_execution_metrics_without_content():
    import importlib
    monitor_module = importlib.import_module(f"{PKG}.log.monitor")
    monitor = monitor_module.RunMonitor()

    monitor.record(
        "run-metrics",
        "failed",
        2.0,
        metrics={
            "steps": 7,
            "replans": 2,
            "failure_attribution": {"tool_error": 1, "planning_error": 1},
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 30,
                "total_tokens": 130,
            },
        },
    )

    snapshot = monitor.snapshot()
    assert snapshot["success_rate"] == 0.0
    assert snapshot["average_steps"] == 7.0
    assert snapshot["average_replans"] == 2.0
    assert snapshot["failure_attribution"] == {
        "tool_error": 1,
        "planning_error": 1,
    }
    assert snapshot["token_usage"] == {
        "input_tokens": 100,
        "output_tokens": 30,
        "total_tokens": 130,
    }
    assert "user_input" not in snapshot["last_run"]
    assert "answer" not in str(snapshot["last_run"]).lower()


def test_run_monitor_metadata_upsert_preserves_existing_execution_metrics():
    import importlib
    monitor_module = importlib.import_module(f"{PKG}.log.monitor")
    monitor = monitor_module.RunMonitor()

    monitor.record(
        "run-shared",
        "failed",
        2.0,
        metrics={
            "steps": 3,
            "replans": 1,
            "failure_attribution": {"model_error": 1},
            "token_usage": {
                "input_tokens": 7,
                "output_tokens": 2,
                "total_tokens": 9,
            },
        },
    )
    # CLI/API wrappers observe the same AgentV2 run and only know final
    # status/duration. Their upsert must not erase the richer inner record.
    monitor.record("run-shared", "failed", 2.5)

    snapshot = monitor.snapshot()
    assert snapshot["total_runs"] == 1
    assert snapshot["status_counts"] == {"failed": 1}
    assert snapshot["total_duration_s"] == 2.5
    assert snapshot["average_steps"] == 3.0
    assert snapshot["average_replans"] == 1.0
    assert snapshot["failure_attribution"] == {"model_error": 1}
    assert snapshot["token_usage"] == {
        "input_tokens": 7,
        "output_tokens": 2,
        "total_tokens": 9,
    }
    assert snapshot["last_run"]["steps"] == 3
    assert snapshot["last_run"]["failure_attribution"] == {"model_error": 1}


def test_run_monitor_bounds_internal_run_id_tracking():
    import importlib
    monitor_module = importlib.import_module(f"{PKG}.log.monitor")
    monitor = monitor_module.RunMonitor()
    monitor._MAX_TRACKED_RUNS = 3

    for index in range(5):
        run_id = f"run-{index}"
        monitor.record_evidence(
            run_id,
            {"status": "succeeded", "executed": True, "artifacts": []},
        )
        monitor.record(run_id, "succeeded", 0.1)

    snapshot = monitor.snapshot()
    assert len(monitor._runs) == 3
    assert len(monitor._evidence_by_run) == 3
    assert snapshot["total_runs"] == 5
    assert snapshot["tool_evidence"] == {"total": 5, "failed": 0}


def test_model_label_resolves_from_config(monkeypatch):
    """#3: startup model label resolves from config, not the literal 'default'."""
    import importlib
    main = importlib.import_module(f"{PKG}.main")
    settings = importlib.import_module(f"{PKG}.config.settings")

    def _fake_load_config():
        return {
            "active_model": "deepseek",
            "models": {"deepseek": {"model_name": "deepseek-v4-flash", "base_url": "x"}},
        }
    monkeypatch.setattr(settings, "load_config", _fake_load_config)

    assert main._resolve_model_label(None) == "deepseek-v4-flash"
    # explicit CLI model wins
    assert main._resolve_model_label("my-model") == "my-model"
