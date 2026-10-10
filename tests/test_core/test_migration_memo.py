"""get_data_dir legacy 迁移的进程内记忆（2026-10-11 /model 修复的一部分）.

迁移是幂等的"缺则补齐"，同一目标目录进程内跑一次即可；此前每次
get_data_dir 都重扫 legacy 目录，热路径上白白多花 0.4s+。
"""

from __future__ import annotations

from pathlib import Path

from config import settings


def _install_spy(monkeypatch, tmp_path: Path) -> tuple[list, set]:
    calls: list[Path] = []
    monkeypatch.setattr(
        settings, "_copy_missing_items", lambda source, target: calls.append(source)
    )
    moved: set[str] = set()
    monkeypatch.setattr(settings, "_MIGRATED_TARGETS", moved)
    # 迁移分支只在目标 == DEFAULT_CONFIG_DIR 时触发；清掉 env 让其走默认目录。
    monkeypatch.delenv("RXYCODE_DATA_DIR", raising=False)
    monkeypatch.setattr(settings, "DEFAULT_CONFIG_DIR", tmp_path / "default_config")
    return calls, moved


def test_migration_runs_once_per_target(monkeypatch, tmp_path: Path):
    calls, _moved = _install_spy(monkeypatch, tmp_path)
    settings.get_data_dir()
    assert len(calls) == 2  # 两个 legacy 根各一次
    settings.get_data_dir()
    assert len(calls) == 2  # 同目录第二次不再重扫


def test_new_target_dir_migrates_again(monkeypatch, tmp_path: Path):
    calls, _moved = _install_spy(monkeypatch, tmp_path)
    settings.get_data_dir()
    monkeypatch.setattr(settings, "DEFAULT_CONFIG_DIR", tmp_path / "another_config")
    settings.get_data_dir()
    assert len(calls) == 4  # 新目录各自迁移一次
