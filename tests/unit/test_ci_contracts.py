from __future__ import annotations

from pathlib import Path

import pytest

from scripts.require_live_credentials import main, missing_credentials
from tests import conftest


def test_live_credential_check_rejects_missing_or_blank_values(monkeypatch, capsys):
    monkeypatch.delenv("RXYCODE_LIVE_API_KEY", raising=False)
    assert missing_credentials() == ["RXYCODE_LIVE_API_KEY"]
    assert main() == 2
    output = capsys.readouterr().out
    assert "::error" in output
    assert "RXYCODE_LIVE_API_KEY" in output

    monkeypatch.setenv("RXYCODE_LIVE_API_KEY", "   ")
    assert missing_credentials() == ["RXYCODE_LIVE_API_KEY"]


def test_live_credential_check_never_prints_secret(monkeypatch, capsys):
    secret = "test-secret-that-must-not-be-printed"
    monkeypatch.setenv("RXYCODE_LIVE_API_KEY", secret)
    assert main() == 0
    assert secret not in capsys.readouterr().out


def test_configured_test_root_is_partitioned_by_lane_and_worker(
    tmp_path, monkeypatch
):
    base = tmp_path / "artifacts" / "runtime"
    monkeypatch.setenv("RXYCODE_TEST_ROOT", str(base))
    monkeypatch.setenv("RXYCODE_TEST_RUN_ID", "linux/unit")
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")

    root, managed_temp = conftest._create_test_root()

    assert root == (base / "linux-unit" / "gw3").resolve()
    assert root.is_dir()
    assert managed_temp is False


def test_coverage_configuration_includes_root_entrypoints():
    project_root = Path(__file__).resolve().parents[2]
    config = (project_root / ".coveragerc").read_text(encoding="utf-8")
    assert "source = ." in config
    assert "api_server.py" not in config.split("omit =", 1)[1]
    assert "main.py" not in config.split("omit =", 1)[1]


def test_ci_uses_isolated_coverage_files_and_failure_artifact_root():
    project_root = Path(__file__).resolve().parents[2]
    workflow = (project_root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("COVERAGE_FILE=artifacts/coverage-data/") == 5
    assert "--cov-append" not in workflow
    assert "coverage combine --keep artifacts/coverage-data" in workflow
    assert '-m "serial and not live and not pty" -n 0' in workflow
    assert "RXYCODE_TEST_ROOT:" in workflow
    assert "artifacts/runtime" in workflow
    assert "Require live provider credentials" in workflow


def test_process_singletons_can_be_mutated_without_escaping_test():
    from RxyCode.RxyCode1_1_0.core import tracing
    from RxyCode.RxyCode1_1_0.core.safety import approval, audit
    from RxyCode.RxyCode1_1_0.log.monitor import run_monitor
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    approval.set_approval_broker(object())
    tracing.reset_tracer("must-not-leak")
    audit._default_logger = object()
    token_stats.add_usage(11, 7)
    run_monitor.record("must-not-leak", "ok", 1.0)


def test_process_singletons_start_clean_after_prior_test():
    from RxyCode.RxyCode1_1_0.core import tracing
    from RxyCode.RxyCode1_1_0.core.safety import approval, audit
    from RxyCode.RxyCode1_1_0.log.monitor import run_monitor
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    assert approval.get_approval_broker() is None
    assert tracing.get_tracer().run_id != "must-not-leak"
    assert audit._default_logger is None
    assert token_stats.total_tokens == 0
    assert run_monitor.snapshot()["total_runs"] == 0


@pytest.mark.asyncio
async def test_api_chat_lock_can_be_left_locked_without_escaping_test():
    from RxyCode.RxyCode1_1_0 import api_server

    await api_server._chat_lock.acquire()
    assert api_server._chat_lock.locked()


def test_api_chat_lock_starts_unlocked_after_prior_test():
    from RxyCode.RxyCode1_1_0 import api_server

    assert not api_server._chat_lock.locked()
