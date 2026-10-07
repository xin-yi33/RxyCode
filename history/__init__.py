"""File change tracking module.

废弃代码（2026-10-01 注释）：生产链路零调用——tools/edit、tools/write 均不
import 本模块（grep 验证：仅 tests/test_core/test_history_tracker.py 引用）。
docs/modules/history.md 声称"被 edit/write tooling 使用"与现状不符；用户级
Undo 的权威实现是 UPDATE-01 轨 J `session/revert`（git best-effort）与轨 K2
磁盘快照，本模块仅为进程内 cache（file_tracker_is_durable()==False）。
保留注释存档，接线或删除二选一前不再扩散引用。
"""

from .tracker import FileTracker, ChangeRecord

__all__ = ["FileTracker", "ChangeRecord"]
