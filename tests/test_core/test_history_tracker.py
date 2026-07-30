"""
Tests for history/tracker.py - File change tracking and diff generation.
"""
import os
import time
import pytest
from pathlib import Path


class TestChangeRecord:
    def test_default_values(self):
        from RxyCode.RxyCode1_1_0.history.tracker import ChangeRecord
        record = ChangeRecord(
            file_path="/test.py",
            old_content=None,
            new_content="hello",
            timestamp=time.time(),
        )
        assert record.tool == ""
        assert record.additions == 0
        assert record.removals == 0
        assert record.diff == ""

    def test_custom_values(self):
        from RxyCode.RxyCode1_1_0.history.tracker import ChangeRecord
        record = ChangeRecord(
            file_path="/test.py",
            old_content="old",
            new_content="new",
            timestamp=1234567890,
            tool="edit",
            additions=1,
            removals=1,
            diff="--- a\n+++ b\n",
        )
        assert record.file_path == "/test.py"
        assert record.tool == "edit"
        assert record.additions == 1
        assert record.removals == 1


class TestFileTracker:
    def _make_tracker(self):
        from RxyCode.RxyCode1_1_0.history.tracker import FileTracker
        return FileTracker()

    def test_record_read(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "test.txt"
        f.write_text("content", encoding="utf-8")
        tracker.record_read(str(f), "content")
        # Internal state should have snapshot
        abs_path = os.path.abspath(str(f))
        assert abs_path in tracker._snapshots

    def test_record_write_new_file(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "new.txt"
        record = tracker.record_write(str(f), "new content", "write")
        assert record.additions >= 1
        assert "new content" in record.new_content

    def test_record_write_overwrite(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "test.txt"
        f.write_text("old content", encoding="utf-8")
        tracker.record_read(str(f), "old content")
        record = tracker.record_write(str(f), "new content", "write")
        assert "old content" in record.old_content
        assert "new content" in record.new_content

    def test_record_edit(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        tracker.record_read(str(f), "hello world")
        record = tracker.record_edit(str(f), "hello", "hi", "edit")
        assert record is not None
        assert "hi world" in record.new_content

    def test_record_edit_string_not_found(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        tracker.record_read(str(f), "hello")
        record = tracker.record_edit(str(f), "nonexistent", "x", "edit")
        assert record is None

    def test_get_changes_empty(self):
        tracker = self._make_tracker()
        assert tracker.get_changes() == []

    def test_get_changes_after_write(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "test.txt"
        f.write_text("content", encoding="utf-8")
        tracker.record_write(str(f), "new", "write")
        changes = tracker.get_changes()
        assert len(changes) == 1

    def test_get_changes_for_file(self, tmp_path):
        tracker = self._make_tracker()
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("a", encoding="utf-8")
        f2.write_text("b", encoding="utf-8")
        tracker.record_write(str(f1), "new a", "write")
        tracker.record_write(str(f2), "new b", "write")
        changes = tracker.get_changes_for_file(str(f1))
        assert len(changes) == 1

    def test_get_changes_for_nonexistent_file(self):
        tracker = self._make_tracker()
        assert tracker.get_changes_for_file("/nonexistent") == []

    def test_get_diff_summary_empty(self):
        tracker = self._make_tracker()
        summary = tracker.get_diff_summary()
        assert "No changes" in summary

    def test_get_diff_summary_with_changes(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2", encoding="utf-8")
        tracker.record_write(str(f), "line1\nline2\nline3", "write")
        summary = tracker.get_diff_summary()
        assert "files" in summary.lower() or "+" in summary

    def test_get_last_diff_empty(self):
        tracker = self._make_tracker()
        assert tracker.get_last_diff() == ""

    def test_get_last_diff_after_write(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "test.txt"
        f.write_text("old", encoding="utf-8")
        tracker.record_read(str(f), "old")
        tracker.record_write(str(f), "new", "write")
        diff = tracker.get_last_diff()
        assert len(diff) > 0

    def test_clear(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "test.txt"
        f.write_text("content", encoding="utf-8")
        tracker.record_write(str(f), "new", "write")
        tracker.clear()
        assert tracker.get_changes() == []
        assert tracker._snapshots == {}

    def test_clear_resets_read_times(self):
        tracker = self._make_tracker()
        tracker._read_times["/test"] = 12345.0
        tracker.clear()
        assert tracker._read_times == {}

    def test_multiple_changes_tracked(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "test.txt"
        f.write_text("v1", encoding="utf-8")
        tracker.record_write(str(f), "v2", "write")
        tracker.record_write(str(f), "v3", "write")
        tracker.record_write(str(f), "v4", "write")
        changes = tracker.get_changes()
        assert len(changes) == 3

    def test_diff_shows_additions_and_removals(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "test.txt"
        f.write_text("old line", encoding="utf-8")
        tracker.record_read(str(f), "old line")
        record = tracker.record_write(str(f), "new line", "write")
        assert record.additions >= 1
        assert record.removals >= 1

    def test_write_to_unread_file_reads_first(self, tmp_path):
        tracker = self._make_tracker()
        f = tmp_path / "test.txt"
        f.write_text("existing", encoding="utf-8")
        # Record write without prior read
        record = tracker.record_write(str(f), "modified", "write")
        assert record.old_content == "existing"


class TestGetFileTracker:
    def test_returns_singleton(self):
        from RxyCode.RxyCode1_1_0.history.tracker import get_file_tracker
        t1 = get_file_tracker()
        t2 = get_file_tracker()
        assert t1 is t2

    def test_returns_file_tracker_instance(self):
        from RxyCode.RxyCode1_1_0.history.tracker import get_file_tracker, FileTracker
        tracker = get_file_tracker()
        assert isinstance(tracker, FileTracker)
