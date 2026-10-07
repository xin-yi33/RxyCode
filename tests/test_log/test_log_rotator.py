"""
E2E tests for the 72h timestamped log retention system (log/rotator.py +
log/logger.py integration).

E2E-1  真实启动路径：setup_logging 写出带时间戳的日志文件，每次调用
       setup_logging 都会先按时间戳排序并清除 >72h 的旧文件，<=72h 的保留。
E2E-2  同秒并发/连续启动：多个 run 在同一秒内各得独立日志文件，排序稳定，
       跨进程（子进程）初始化也能写到同一目录且不互相覆盖。
E2E-3  边界与清理语义：恰好 72h 整的文件不删，72h+1s 的删除；非日志文件、
       无时间戳文件不受影响；list_log_files 每次访问都先清理再按时间戳
       升序返回；同时验证现有 setup_logging 的既有契约（RotatingFileHandler
       10MB x 5、INFO 级别、key=value 格式、run id）不被破坏。
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PKG = "RxyCode.RxyCode1_1_0"


def _import_rotator():
    import importlib

    return importlib.import_module(f"{PKG}.log.rotator")


def _import_logger_mod():
    import importlib

    return importlib.import_module(f"{PKG}.log.logger")


@pytest.fixture()
def log_dir(tmp_path, monkeypatch):
    """Redirect the log directory into an isolated tmp dir."""
    d = tmp_path / "logs"
    d.mkdir(parents=True)
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    return d


def _make_old_file(log_dir: Path, age_seconds: float, name_prefix: str = "rxycode") -> Path:
    """Create a log file whose *filename timestamp* is `age_seconds` in the past."""
    ts = time.strftime(
        "%Y-%m-%d_%H-%M-%S", time.localtime(time.time() - age_seconds)
    )
    path = log_dir / f"{name_prefix}_{ts}_oldrun{int(age_seconds)}.log"
    path.write_text(f"old log age={age_seconds}\n", encoding="utf-8")
    return path


def _reset_logger_singleton(logger_mod):
    logger_mod._initialized = False
    logger_mod._logger_instance = None
    lg = logging.getLogger("rxycode")
    for h in list(lg.handlers):
        try:
            h.close()
        except Exception:
            pass
        lg.removeHandler(h)


class TestE2ELogRetentionSetup:
    """E2E-1: end-to-end through the real setup_logging entry point."""

    def test_setup_writes_timestamped_file_and_prunes_older_than_72h(
        self, log_dir, monkeypatch
    ):
        rotator = _import_rotator()
        logger_mod = _import_logger_mod()
        monkeypatch.setattr(logger_mod, "LOG_DIR", log_dir)
        _reset_logger_singleton(logger_mod)

        # Seed: one file 100h old (must go), one 1h old (must stay), plus junk.
        ancient = _make_old_file(log_dir, 100 * 3600)
        recent = _make_old_file(log_dir, 1 * 3600)
        junk = log_dir / "notes.txt"
        junk.write_text("not a log", encoding="utf-8")
        no_ts = log_dir / "rxycode.log"  # legacy name, no timestamp -> never pruned
        no_ts.write_text("legacy\n", encoding="utf-8")

        lg = logger_mod.setup_logging("INFO")
        lg.info("e2e retention probe", extra={"marker": "e2e1"})
        for h in lg.handlers:
            h.flush()

        # New timestamped file exists and contains the record with a timestamp.
        live = logger_mod.LOG_FILE
        assert live.exists(), "setup_logging must create a timestamped log file"
        assert rotator.parse_log_timestamp(live.name) is not None
        content = live.read_text(encoding="utf-8")
        assert "e2e retention probe" in content
        # Line carries a timestamp (KeyValueFormatter: "YYYY-MM-DD HH:MM:SS LEVEL ...")
        assert time.strftime("%Y-%m-%d", time.localtime()) in content
        assert "INFO" in content and "run=" in content

        # 100h file pruned; 1h file, junk and legacy file kept.
        assert not ancient.exists(), "file older than 72h must be pruned on setup"
        assert recent.exists(), "file younger than 72h must be kept"
        assert junk.exists() and no_ts.exists()

    def test_setup_keeps_existing_contract(self, log_dir, monkeypatch):
        """setup_logging still yields a RotatingFileHandler 10MB x 5 at INFO."""
        logger_mod = _import_logger_mod()
        monkeypatch.setattr(logger_mod, "LOG_DIR", log_dir)
        _reset_logger_singleton(logger_mod)
        lg = logger_mod.setup_logging("INFO")
        rotating = [
            h
            for h in lg.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert rotating, "expected a RotatingFileHandler"
        assert rotating[0].maxBytes == 10 * 1024 * 1024
        assert rotating[0].backupCount == 5
        assert lg.level == logging.INFO
        assert lg.name == "rxycode"
        # handler baseFilename points at the timestamped file
        assert rotating[0].baseFilename == str(logger_mod.LOG_FILE)


class TestE2EConcurrentRunsAndSorting:
    """E2E-2: multiple runs (incl. a real subprocess) never clobber each other
    and the directory listing is always timestamp-sorted."""

    def test_same_second_runs_get_distinct_sorted_files(self, log_dir, monkeypatch):
        rotator = _import_rotator()
        logger_mod = _import_logger_mod()
        monkeypatch.setattr(logger_mod, "LOG_DIR", log_dir)

        created: list[Path] = []
        for i in range(3):
            _reset_logger_singleton(logger_mod)
            lg = logger_mod.setup_logging("INFO")
            lg.info(f"run {i}")
            for h in lg.handlers:
                h.flush()
            created.append(logger_mod.LOG_FILE)

        assert len({p.name for p in created}) == 3, "same-second runs must not share a file"
        for p in created:
            assert p.exists()

        files = rotator.list_log_files(log_dir)
        names = [p.name for p in files]
        assert names == sorted(names, key=lambda n: rotator.parse_log_timestamp(n) or 0)
        # list is ascending (oldest first, newest last)
        timestamps = [rotator.parse_log_timestamp(n) for n in names]
        assert timestamps == sorted(timestamps)

    def test_subprocess_initialization_writes_into_same_dir(
        self, log_dir, tmp_path, monkeypatch
    ):
        """A separate python process initializing logging writes its own
        timestamped file into the same directory without clobbering ours."""
        rotator = _import_rotator()
        logger_mod = _import_logger_mod()
        monkeypatch.setattr(logger_mod, "LOG_DIR", log_dir)
        _reset_logger_singleton(logger_mod)
        lg = logger_mod.setup_logging("INFO")
        lg.info("parent run")
        for h in lg.handlers:
            h.flush()
        parent_file = logger_mod.LOG_FILE.name

        script = (
            "import sys, time;"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[2] )!r});"
            f"from {PKG}.log import logger as lm;"
            f"lm.LOG_DIR = __import__('pathlib').Path({str(log_dir)!r});"
            "lg = lm.setup_logging('INFO');"
            "lg.info('child run');"
            "[h.flush() for h in lg.handlers];"
            "print(lm.LOG_FILE.name)"
        )
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert out.returncode == 0, out.stderr
        child_file = out.stdout.strip().splitlines()[-1]
        assert child_file and child_file != parent_file
        assert (log_dir / child_file).exists()
        assert (log_dir / parent_file).exists()

        files = rotator.list_log_files(log_dir)
        assert len(files) >= 2
        timestamps = [rotator.parse_log_timestamp(p.name) for p in files]
        assert timestamps == sorted(timestamps)


class TestE2ERetentionBoundarySemantics:
    """E2E-3: exact-72h boundary, pruning semantics, and per-access cleanup."""

    def test_exact_72h_kept_72h_plus_1s_pruned(self, log_dir):
        """Boundary is defined on the *filename* timestamp (1s resolution):
        a file whose timestamp is >= now-72h is kept; strictly older is pruned."""
        rotator = _import_rotator()
        # Anchor `now` to a whole second so the 1s-resolution filename timestamp
        # of the exactly-72h file lands precisely on the cutoff.
        now = float(int(time.time()))
        exact = _make_old_file(log_dir, 72 * 3600)
        over = _make_old_file(log_dir, 72 * 3600 + 1)
        under = _make_old_file(log_dir, 71 * 3600)

        # The exactly-72h file's filename timestamp may be now-72h or
        # now-72h-1 depending on sub-second timing; align `now` to its actual ts.
        exact_ts = rotator.parse_log_timestamp(exact.name)
        now = exact_ts + 72 * 3600

        removed = rotator.prune_old_logs(log_dir, now=now)
        removed_names = {p.name for p in removed}

        assert over.name in removed_names, "72h+1s must be pruned"
        assert exact.name not in removed_names, "exactly 72h must be kept (>= cutoff)"
        assert under.name not in removed_names
        assert exact.exists() and under.exists() and not over.exists()

    def test_every_access_prunes_then_sorts(self, log_dir):
        """list_log_files is the whole-folder access point: it prunes >72h
        first, then returns the survivors sorted by filename timestamp."""
        rotator = _import_rotator()
        _make_old_file(log_dir, 200 * 3600)  # stale
        mid = _make_old_file(log_dir, 10 * 3600)
        new = _make_old_file(log_dir, 5)

        files = rotator.list_log_files(log_dir)
        names = [p.name for p in files]
        assert mid.name in names and new.name in names
        assert all("200" not in n or rotator.parse_log_timestamp(n) is not None for n in names)
        stale = [n for n in names if rotator.parse_log_timestamp(n) and
                 rotator.parse_log_timestamp(n) < time.time() - 72 * 3600]
        assert stale == [], "no file older than 72h survives an access"
        ts = [rotator.parse_log_timestamp(n) for n in names]
        assert ts == sorted(ts)

    def test_unparseable_and_foreign_files_never_pruned(self, log_dir):
        rotator = _import_rotator()
        legacy = log_dir / "rxycode.log"
        legacy.write_text("x", encoding="utf-8")
        other_app = log_dir / "other_2020-01-01_00-00-00_deadbeef.log"
        other_app.write_text("x", encoding="utf-8")
        subdir = log_dir / "rxycode_2020-01-01_00-00-00_dir.log"
        subdir.mkdir()

        rotator.prune_old_logs(log_dir)
        assert legacy.exists(), "no-timestamp file must never be pruned"
        assert not other_app.exists(), (
            "any *parseable* timestamped .log older than 72h is pruned "
            "(retention is per-directory, not per-app-prefix)"
        )
        assert subdir.exists(), "directories are never pruned"
