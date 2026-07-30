"""
Tests for scheduler/cron.py and scheduler/manager.py.

Covers: cron parsing, shorthand expansion, field parsing, matching, scheduling.
"""
import json
import pytest
import threading
from datetime import datetime, timedelta
from pathlib import Path


def test_manual_and_cron_runs_cannot_execute_same_task_concurrently(tmp_path):
    from RxyCode.RxyCode1_1_0.scheduler.manager import TaskScheduler

    scheduler = TaskScheduler(storage_path=tmp_path / "tasks.json")
    started = threading.Event()
    release = threading.Event()
    calls = []

    def callback(prompt):
        calls.append(prompt)
        started.set()
        assert release.wait(timeout=2)
        return "done"

    scheduler.set_callback(callback)
    task = scheduler.add_task("* * * * *", "exactly once")
    worker = threading.Thread(target=scheduler.run_task, args=(task.id,))
    worker.start()
    try:
        assert started.wait(timeout=1)
        scheduler._check_and_run()
    finally:
        release.set()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert calls == ["exactly once"]
    assert task.run_count == 1
    assert scheduler._running_task_ids == set()


class TestParseCron:
    def _parse(self, expr):
        from RxyCode.RxyCode1_1_0.scheduler.cron import parse_cron
        return parse_cron(expr)

    def test_standard_5_fields(self):
        cron = self._parse("* * * * *")
        assert cron is not None

    def test_every_minute(self):
        cron = self._parse("* * * * *")
        now = datetime.now()
        assert cron.matches(now)

    def test_specific_minute(self):
        cron = self._parse("30 * * * *")
        match_time = datetime(2024, 1, 1, 10, 30)
        assert cron.matches(match_time)
        no_match = datetime(2024, 1, 1, 10, 31)
        assert not cron.matches(no_match)

    def test_specific_hour(self):
        cron = self._parse("* 9 * * *")
        match = datetime(2024, 1, 1, 9, 0)
        assert cron.matches(match)
        no_match = datetime(2024, 1, 1, 10, 0)
        assert not cron.matches(no_match)

    def test_specific_day(self):
        cron = self._parse("* * 15 * *")
        match = datetime(2024, 1, 15, 0, 0)
        assert cron.matches(match)
        no_match = datetime(2024, 1, 16, 0, 0)
        assert not cron.matches(no_match)

    def test_specific_month(self):
        cron = self._parse("* * * 6 *")
        match = datetime(2024, 6, 1, 0, 0)
        assert cron.matches(match)
        no_match = datetime(2024, 7, 1, 0, 0)
        assert not cron.matches(no_match)

    def test_weekday_matching(self):
        cron = self._parse("* * * * 1")  # Monday
        monday = datetime(2024, 1, 1, 0, 0)  # 2024-01-01 is Monday
        assert cron.matches(monday)
        tuesday = datetime(2024, 1, 2, 0, 0)
        assert not cron.matches(tuesday)

    def test_step_pattern(self):
        cron = self._parse("*/5 * * * *")
        assert cron.matches(datetime(2024, 1, 1, 0, 0))
        assert cron.matches(datetime(2024, 1, 1, 0, 5))
        assert cron.matches(datetime(2024, 1, 1, 0, 10))
        assert not cron.matches(datetime(2024, 1, 1, 0, 3))

    def test_step_pattern_hours(self):
        cron = self._parse("0 */2 * * *")
        assert cron.matches(datetime(2024, 1, 1, 0, 0))
        assert cron.matches(datetime(2024, 1, 1, 2, 0))
        assert not cron.matches(datetime(2024, 1, 1, 3, 0))

    def test_range_pattern(self):
        cron = self._parse("0 9-17 * * *")
        assert cron.matches(datetime(2024, 1, 1, 9, 0))
        assert cron.matches(datetime(2024, 1, 1, 12, 0))
        assert cron.matches(datetime(2024, 1, 1, 17, 0))
        assert not cron.matches(datetime(2024, 1, 1, 18, 0))
        assert not cron.matches(datetime(2024, 1, 1, 8, 0))

    def test_list_pattern(self):
        cron = self._parse("0 9,12,18 * * *")
        assert cron.matches(datetime(2024, 1, 1, 9, 0))
        assert cron.matches(datetime(2024, 1, 1, 12, 0))
        assert cron.matches(datetime(2024, 1, 1, 18, 0))
        assert not cron.matches(datetime(2024, 1, 1, 10, 0))

    def test_range_with_step(self):
        cron = self._parse("0-59/15 * * * *")
        assert cron.matches(datetime(2024, 1, 1, 0, 0))
        assert cron.matches(datetime(2024, 1, 1, 0, 15))
        assert cron.matches(datetime(2024, 1, 1, 0, 30))
        assert not cron.matches(datetime(2024, 1, 1, 0, 7))

    def test_too_few_fields(self):
        with pytest.raises(ValueError):
            self._parse("* * *")

    def test_too_many_fields(self):
        with pytest.raises(ValueError):
            self._parse("* * * * * *")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            self._parse("")

    def test_invalid_value(self):
        with pytest.raises(ValueError):
            self._parse("60 * * * *")  # minute > 59

    def test_invalid_hour(self):
        with pytest.raises(ValueError):
            self._parse("* 24 * * *")

    def test_invalid_day(self):
        with pytest.raises(ValueError):
            self._parse("* * 32 * *")

    def test_invalid_month(self):
        with pytest.raises(ValueError):
            self._parse("* * * 13 *")

    def test_invalid_weekday(self):
        with pytest.raises(ValueError):
            self._parse("* * * * 7")

    def test_invalid_field_syntax(self):
        with pytest.raises(ValueError):
            self._parse("abc * * * *")

    def test_invalid_step(self):
        with pytest.raises(ValueError):
            self._parse("*/0 * * * *")

    def test_invalid_range_start_gt_end(self):
        with pytest.raises(ValueError):
            self._parse("10-5 * * * *")


class TestCronShorthand:
    def _parse(self, expr):
        from RxyCode.RxyCode1_1_0.scheduler.cron import parse_cron
        return parse_cron(expr)

    def test_hourly(self):
        cron = self._parse("@hourly")
        assert cron.matches(datetime(2024, 1, 1, 5, 0))
        assert not cron.matches(datetime(2024, 1, 1, 5, 30))

    def test_daily(self):
        cron = self._parse("@daily")
        assert cron.matches(datetime(2024, 1, 1, 0, 0))
        assert not cron.matches(datetime(2024, 1, 1, 12, 0))

    def test_weekly(self):
        cron = self._parse("@weekly")
        # 2024-01-07 is Sunday
        sunday = datetime(2024, 1, 7, 0, 0)
        assert cron.matches(sunday)

    def test_monthly(self):
        cron = self._parse("@monthly")
        assert cron.matches(datetime(2024, 1, 1, 0, 0))
        assert not cron.matches(datetime(2024, 1, 2, 0, 0))

    def test_yearly(self):
        cron = self._parse("@yearly")
        assert cron.matches(datetime(2024, 1, 1, 0, 0))
        assert not cron.matches(datetime(2024, 6, 1, 0, 0))

    def test_annually_same_as_yearly(self):
        cron = self._parse("@annually")
        assert cron.matches(datetime(2024, 1, 1, 0, 0))

    def test_every_5m(self):
        cron = self._parse("@every 5m")
        assert cron.matches(datetime(2024, 1, 1, 0, 0))
        assert cron.matches(datetime(2024, 1, 1, 0, 5))
        assert not cron.matches(datetime(2024, 1, 1, 0, 3))

    def test_every_1h(self):
        cron = self._parse("@every 1h")
        assert cron.matches(datetime(2024, 1, 1, 0, 0))
        assert cron.matches(datetime(2024, 1, 1, 1, 0))
        assert not cron.matches(datetime(2024, 1, 1, 0, 30))

    def test_every_2h30m(self):
        cron = self._parse("@every 2h30m")
        # 2h30m = 150 min -> */150 not clean, but should not crash
        assert cron is not None

    def test_every_1d(self):
        cron = self._parse("@every 1d")
        assert cron is not None

    def test_every_24h_becomes_daily(self):
        cron = self._parse("@every 24h")
        assert cron.matches(datetime(2024, 1, 1, 0, 0))

    def test_invalid_duration_char(self):
        with pytest.raises(ValueError):
            self._parse("@every 5x")

    def test_zero_duration(self):
        with pytest.raises(ValueError):
            self._parse("@every 0m")

    def test_case_insensitive(self):
        cron = self._parse("@HOURLY")
        assert cron.matches(datetime(2024, 1, 1, 5, 0))


class TestCronNextRun:
    def _parse(self, expr):
        from RxyCode.RxyCode1_1_0.scheduler.cron import parse_cron
        return parse_cron(expr)

    def test_next_run_every_minute(self):
        cron = self._parse("* * * * *")
        now = datetime(2024, 1, 1, 12, 0, 0)
        next_time = cron.next_run(now)
        assert next_time > now
        assert cron.matches(next_time)

    def test_next_run_hourly(self):
        cron = self._parse("0 * * * *")
        now = datetime(2024, 1, 1, 12, 30, 0)
        next_time = cron.next_run(now)
        assert next_time.minute == 0
        assert next_time.hour == 13

    def test_next_run_daily(self):
        cron = self._parse("0 0 * * *")
        now = datetime(2024, 1, 1, 12, 0, 0)
        next_time = cron.next_run(now)
        assert next_time.day == 2
        assert next_time.hour == 0
        assert next_time.minute == 0

    def test_next_run_is_at_least_one_minute_ahead(self):
        cron = self._parse("* * * * *")
        now = datetime(2024, 1, 1, 12, 0, 0)
        next_time = cron.next_run(now)
        assert next_time >= now + timedelta(minutes=1)

    def test_next_run_matches(self):
        cron = self._parse("30 9 * * 1-5")
        now = datetime(2024, 1, 1, 0, 0, 0)
        next_time = cron.next_run(now)
        assert cron.matches(next_time)


class TestScheduledTask:
    def test_to_dict(self):
        from RxyCode.RxyCode1_1_0.scheduler.manager import ScheduledTask
        task = ScheduledTask(id="T1", cron_expr="@hourly", prompt="test")
        d = task.to_dict()
        assert d["id"] == "T1"
        assert d["cron_expr"] == "@hourly"
        assert d["prompt"] == "test"
        assert d["enabled"] is True

    def test_from_dict(self):
        from RxyCode.RxyCode1_1_0.scheduler.manager import ScheduledTask
        data = {"id": "T2", "cron_expr": "* * * * *", "prompt": "hello", "enabled": False}
        task = ScheduledTask.from_dict(data)
        assert task.id == "T2"
        assert task.enabled is False

    def test_roundtrip(self):
        from RxyCode.RxyCode1_1_0.scheduler.manager import ScheduledTask
        task = ScheduledTask(id="T3", cron_expr="@daily", prompt="daily task")
        d = task.to_dict()
        restored = ScheduledTask.from_dict(d)
        assert restored.id == task.id
        assert restored.cron_expr == task.cron_expr

    def test_default_values(self):
        from RxyCode.RxyCode1_1_0.scheduler.manager import ScheduledTask
        task = ScheduledTask(id="T4", cron_expr="@hourly", prompt="x")
        assert task.enabled is True
        assert task.run_count == 0
        assert task.last_run == ""
        assert task.last_result == ""


class TestTaskScheduler:
    def _make_scheduler(self, tmp_path):
        from RxyCode.RxyCode1_1_0.scheduler.manager import TaskScheduler
        return TaskScheduler(storage_path=tmp_path / "tasks.json")

    def test_add_task(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        task = sched.add_task("@hourly", "test prompt")
        assert task.id is not None
        assert task.cron_expr == "@hourly"
        assert task.prompt == "test prompt"

    def test_get_task(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        task = sched.add_task("@hourly", "get me")
        found = sched.get_task(task.id)
        assert found is not None
        assert found.prompt == "get me"

    def test_get_nonexistent_task(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        assert sched.get_task("nonexistent") is None

    def test_remove_task(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        task = sched.add_task("@hourly", "remove me")
        assert sched.remove_task(task.id) is True
        assert sched.get_task(task.id) is None

    def test_remove_nonexistent_task(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        assert sched.remove_task("nonexistent") is False

    def test_list_tasks(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        sched.add_task("@hourly", "task1")
        sched.add_task("@daily", "task2")
        tasks = sched.list_tasks()
        assert len(tasks) == 2

    def test_enable_task(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        task = sched.add_task("@hourly", "enable me")
        sched.disable_task(task.id)
        sched.enable_task(task.id)
        assert sched.get_task(task.id).enabled is True

    def test_disable_task(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        task = sched.add_task("@hourly", "disable me")
        sched.disable_task(task.id)
        assert sched.get_task(task.id).enabled is False

    def test_enable_nonexistent_task(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        assert sched.enable_task("nonexistent") is False

    def test_disable_nonexistent_task(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        assert sched.disable_task("nonexistent") is False

    def test_set_callback(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        callback = lambda prompt: "result"
        sched.set_callback(callback)
        assert sched._callback is not None

    def test_persist_and_load(self, tmp_path):
        from RxyCode.RxyCode1_1_0.scheduler.manager import TaskScheduler
        path = tmp_path / "tasks.json"
        sched1 = TaskScheduler(storage_path=path)
        sched1.add_task("@hourly", "persisted task")
        sched2 = TaskScheduler(storage_path=path)
        tasks = sched2.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].prompt == "persisted task"

    def test_terminal_result_is_persisted_without_truncation(self, tmp_path):
        from RxyCode.RxyCode1_1_0.scheduler.manager import TaskScheduler

        path = tmp_path / "tasks.json"
        scheduler = TaskScheduler(storage_path=path)
        expected = "scheduled:" + "x" * 1000
        scheduler.set_callback(lambda _prompt: expected)
        task = scheduler.add_task("@daily", "persist result")

        assert scheduler.run_task(task.id) is True
        restored = TaskScheduler(storage_path=path).get_task(task.id)
        assert restored.run_count == 1
        assert restored.last_status == "succeeded"
        assert restored.last_result == expected
        assert restored.last_run

    def test_same_cron_minute_runs_at_most_once(self, tmp_path):
        scheduler = self._make_scheduler(tmp_path)
        calls = []
        scheduler.set_callback(lambda prompt: calls.append(prompt) or "done")
        scheduler.add_task("* * * * *", "once per slot")

        scheduler._check_and_run()
        scheduler._check_and_run()

        assert calls == ["once per slot"]

    def test_start_stop_does_not_crash(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        sched.start()
        sched.stop()

    def test_add_task_with_custom_id(self, tmp_path):
        sched = self._make_scheduler(tmp_path)
        task = sched.add_task("@hourly", "custom id", task_id="custom123")
        assert task.id == "custom123"
        assert sched.get_task("custom123") is not None
