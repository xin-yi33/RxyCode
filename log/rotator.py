"""
Timestamped agent-run log retention: one file per run, 72h sliding window.

每启动一次（一次 setup_logging）生成一个带时间戳的日志文件：
    rxycode_YYYY-MM-DD_HH-MM-SS_<runid>.log
文件名时间戳即权威时间，排序/清理都基于它而不是 mtime，避免拷贝、备份
或触摸文件导致 mtime 漂移后误删。

策略：
- 保留窗口默认 72 小时（``RETENTION_HOURS``，可用 RXYCODE_LOG_RETENTION_HOURS 覆盖）。
- ``prune_old_logs`` 在每次访问日志目录时被调用（setup_logging / list_log_files /
  open_log_dir），按文件名时间戳升序排序后，删除超出窗口的文件；窗口内的不删。
- ``list_log_files`` 永远返回按时间戳升序排序的列表（新文件在末尾）。

纯函数/副作用边界：``parse_log_timestamp``、``iter_log_files_sorted`` 无副作用；
``prune_old_logs`` 只删除过期文件；``new_log_path`` 只负责命名，不创建文件。
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Iterator, Optional

# 72h 默认保留窗口（秒）
RETENTION_HOURS = float(os.environ.get("RXYCODE_LOG_RETENTION_HOURS", "72"))
RETENTION_SECONDS = RETENTION_HOURS * 3600.0

# 文件名时间戳：rxycode_2026-10-01_13-45-07_ab12cd34.log
# 允许可选的轮转后缀 .1 / .2（RotatingFileHandler 产生），它们随主文件一起排序/清理。
LOG_NAME_RE = re.compile(
    r"^(?P<prefix>[A-Za-z0-9-]+)_(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})"
    r"(?:_(?P<runid>[A-Za-z0-9]+))?\.log(?P<rot>\.\d+)?$"
)

TS_FORMAT = "%Y-%m-%d_%H-%M-%S"


def parse_log_timestamp(name: str) -> Optional[float]:
    """从日志文件名解析时间戳（epoch 秒）。解析失败返回 None。"""
    m = LOG_NAME_RE.match(Path(name).name)
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group("ts"), TS_FORMAT))
    except (ValueError, OverflowError):
        return None


def new_log_path(log_dir: Path, run_id: str, *, prefix: str = "rxycode") -> Path:
    """生成一个新的按时间戳命名的日志文件路径（不创建文件）。"""
    ts = time.strftime(TS_FORMAT, time.localtime())
    safe_run = re.sub(r"[^A-Za-z0-9]+", "", run_id)[:8] or "norunid"
    path = log_dir / f"{prefix}_{ts}_{safe_run}.log"
    # 同一秒内多次启动时避免互相覆盖
    counter = 1
    while path.exists():
        path = log_dir / f"{prefix}_{ts}_{safe_run}_{counter}.log"
        counter += 1
    return path


def iter_log_files_sorted(log_dir: Path, *, prefix: str = "rxycode") -> Iterator[Path]:
    """按文件名时间戳升序（旧->新）产出日志文件。

    无法解析时间戳的文件排在最后（视为最新，不参与基于时间戳的清理）。
    """
    if not log_dir.is_dir():
        return
    entries = []
    for entry in log_dir.iterdir():
        if not entry.is_file():
            continue
        ts = parse_log_timestamp(entry.name)
        if ts is None:
            continue
        entries.append((ts, entry.name, entry))
    entries.sort(key=lambda item: (item[0], item[1]))
    for _, _, entry in entries:
        yield entry


def prune_old_logs(
    log_dir: Path,
    *,
    now: Optional[float] = None,
    retention_seconds: Optional[float] = None,
    prefix: str = "rxycode",
) -> list[Path]:
    """删除超出保留窗口的日志文件，返回被删除的路径列表（按时间戳升序）。

    只在窗口外（mtime/时间戳早于 now - retention_seconds）才删除；
    无法解析时间戳的文件不删。删除失败静默跳过——日志清理永远不能
    影响主流程。
    """
    cutoff = (now if now is not None else time.time()) - (
        retention_seconds if retention_seconds is not None else RETENTION_SECONDS
    )
    removed: list[Path] = []
    for entry in iter_log_files_sorted(log_dir, prefix=prefix):
        ts = parse_log_timestamp(entry.name)
        if ts is None or ts >= cutoff:
            continue
        try:
            entry.unlink()
            removed.append(entry)
        except OSError:
            continue
    return removed


def list_log_files(
    log_dir: Path,
    *,
    prune: bool = True,
    prefix: str = "rxycode",
) -> list[Path]:
    """每次访问日志目录的统一入口：先按 72h 窗口清理，再返回按时间戳升序的列表。"""
    if prune:
        prune_old_logs(log_dir, prefix=prefix)
    return list(iter_log_files_sorted(log_dir, prefix=prefix))
