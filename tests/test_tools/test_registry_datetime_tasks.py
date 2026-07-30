"""
Tests for tools/registry.py, tools/installer.py, tools/datetime_tool.py,
tools/task_tool.py, tools/history_tool.py.
"""
import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestToolRegistry:
    def _make_registry(self):
        from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry
        return ToolRegistry()

    def _make_tool(self, name="test_tool", desc="A test tool"):
        from langchain_core.tools import StructuredTool
        return StructuredTool.from_function(
            func=lambda: "ok", name=name, description=desc
        )

    def test_register_tool(self):
        reg = self._make_registry()
        tool = self._make_tool("mytool")
        reg.register(tool)
        assert reg.get("mytool") is tool

    def test_get_nonexistent_tool(self):
        reg = self._make_registry()
        assert reg.get("nonexistent") is None

    def test_register_alias(self):
        reg = self._make_registry()
        tool = self._make_tool("original")
        reg.register(tool)
        assert reg.register_alias("alias", "original") is True

    def test_alias_for_nonexistent_target(self):
        reg = self._make_registry()
        assert reg.register_alias("alias", "nonexistent") is False

    def test_get_all_returns_non_alias_tools(self):
        reg = self._make_registry()
        t1 = self._make_tool("tool1")
        t2 = self._make_tool("tool2")
        reg.register(t1)
        reg.register(t2)
        reg.register_alias("alias1", "tool1")
        all_tools = reg.get_all()
        assert len(all_tools) == 2

    def test_get_names_includes_aliases(self):
        reg = self._make_registry()
        t1 = self._make_tool("tool1")
        reg.register(t1)
        reg.register_alias("alias1", "tool1")
        names = reg.get_names()
        assert "tool1" in names
        assert "alias1" in names

    def test_get_descriptions(self):
        reg = self._make_registry()
        t1 = self._make_tool("tool1", "First tool")
        reg.register(t1)
        desc = reg.get_descriptions()
        assert "tool1" in desc
        assert "First tool" in desc

    def test_remove_existing_tool(self):
        reg = self._make_registry()
        t1 = self._make_tool("tool1")
        reg.register(t1)
        assert reg.remove("tool1") is True
        assert reg.get("tool1") is None

    def test_remove_nonexistent_tool(self):
        reg = self._make_registry()
        assert reg.remove("nonexistent") is False

    def test_remove_alias(self):
        reg = self._make_registry()
        t1 = self._make_tool("tool1")
        reg.register(t1)
        reg.register_alias("alias1", "tool1")
        assert reg.remove("alias1") is True
        assert "alias1" not in reg.get_names()

    def test_get_all_deduplicates_by_identity(self):
        reg = self._make_registry()
        t1 = self._make_tool("tool1")
        reg.register(t1)
        reg.register_alias("alias1", "tool1")
        reg.register_alias("alias2", "tool1")
        all_tools = reg.get_all()
        assert len(all_tools) == 1

    def test_empty_registry_get_all(self):
        reg = self._make_registry()
        assert reg.get_all() == []

    def test_empty_registry_get_names(self):
        reg = self._make_registry()
        assert reg.get_names() == []

    def test_empty_registry_get_descriptions(self):
        reg = self._make_registry()
        assert reg.get_descriptions() == ""

    def test_overwrite_existing_tool(self):
        reg = self._make_registry()
        t1 = self._make_tool("tool1", "v1")
        t2 = self._make_tool("tool1", "v2")
        reg.register(t1)
        reg.register(t2)
        assert reg.get("tool1") is t2

    def test_multiple_aliases_point_to_same_tool(self):
        reg = self._make_registry()
        t1 = self._make_tool("original")
        reg.register(t1)
        reg.register_alias("alias1", "original")
        reg.register_alias("alias2", "original")
        assert reg.get("alias1") is t1
        assert reg.get("alias2") is t1

    def test_get_descriptions_excludes_aliases(self):
        reg = self._make_registry()
        t1 = self._make_tool("tool1", "desc1")
        reg.register(t1)
        reg.register_alias("alias1", "tool1")
        desc = reg.get_descriptions()
        lines = [l for l in desc.split("\n") if l.strip()]
        assert len(lines) == 1


class TestGetDatetime:
    def test_default_format(self):
        from RxyCode.RxyCode1_1_0.tools.datetime_tool import get_datetime
        result = get_datetime()
        assert len(result) == 19
        assert result[4] == "-"

    def test_custom_format(self):
        from RxyCode.RxyCode1_1_0.tools.datetime_tool import get_datetime
        result = get_datetime("%Y")
        assert len(result) == 4
        assert int(result) >= 2020

    def test_date_only_format(self):
        from RxyCode.RxyCode1_1_0.tools.datetime_tool import get_datetime
        result = get_datetime("%Y-%m-%d")
        assert len(result) == 10

    def test_time_only_format(self):
        from RxyCode.RxyCode1_1_0.tools.datetime_tool import get_datetime
        result = get_datetime("%H:%M:%S")
        assert len(result) == 8

    def test_invalid_format_falls_back(self):
        from RxyCode.RxyCode1_1_0.tools.datetime_tool import get_datetime
        result = get_datetime("%Q")
        assert isinstance(result, str)

    def test_empty_format(self):
        from RxyCode.RxyCode1_1_0.tools.datetime_tool import get_datetime
        result = get_datetime("")
        assert isinstance(result, str)

    def test_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.datetime_tool import datetime_tool
        assert datetime_tool.name == "datetime"

    def test_iso_format(self):
        from RxyCode.RxyCode1_1_0.tools.datetime_tool import get_datetime
        result = get_datetime("%Y-%m-%dT%H:%M:%S")
        assert "T" in result

    def test_unix_timestamp_format(self):
        from RxyCode.RxyCode1_1_0.tools.datetime_tool import get_datetime
        result = get_datetime("%s")
        # On some platforms %s may not be supported, just check it returns a string
        assert isinstance(result, str)
        assert len(result) > 0


class TestTaskTool:
    def _manage(self, operation, id="", summary="", status="", event_summary=""):
        from RxyCode.RxyCode1_1_0.tools.task_tool import manage_tasks
        return manage_tasks(operation, id, summary, status, event_summary)

    def test_create_task(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        result = self._manage("create", summary="Test task")
        assert "Created task" in result

    def test_list_empty_tasks(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        result = self._manage("list")
        assert "no tasks" in result.lower()

    def test_list_tasks_after_create(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        self._manage("create", summary="Task A")
        self._manage("create", summary="Task B")
        result = self._manage("list")
        assert "Task A" in result
        assert "Task B" in result

    def test_get_existing_task(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        cr = self._manage("create", summary="Find me")
        tid = cr.split("Created task ")[1].split(":")[0]
        result = self._manage("get", id=tid)
        assert "Find me" in result

    def test_get_nonexistent_task(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        result = self._manage("get", id="T999")
        assert "not found" in result.lower()

    def test_start_task(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        cr = self._manage("create", summary="Start me")
        tid = cr.split("Created task ")[1].split(":")[0]
        result = self._manage("start", id=tid)
        assert "in_progress" in result

    def test_done_task(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        cr = self._manage("create", summary="Complete me")
        tid = cr.split("Created task ")[1].split(":")[0]
        result = self._manage("done", id=tid)
        assert "done" in result.lower()

    def test_block_task(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        cr = self._manage("create", summary="Block me")
        tid = cr.split("Created task ")[1].split(":")[0]
        result = self._manage("block", id=tid)
        assert "blocked" in result.lower()

    def test_unblock_task(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        cr = self._manage("create", summary="Unblock me")
        tid = cr.split("Created task ")[1].split(":")[0]
        self._manage("block", id=tid)
        result = self._manage("unblock", id=tid)
        assert "open" in result.lower()

    def test_abandon_task(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        cr = self._manage("create", summary="Abandon me")
        tid = cr.split("Created task ")[1].split(":")[0]
        result = self._manage("abandon", id=tid)
        assert "abandoned" in result.lower()

    def test_rename_task(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        cr = self._manage("create", summary="Old name")
        tid = cr.split("Created task ")[1].split(":")[0]
        result = self._manage("rename", id=tid, summary="New name")
        assert "New name" in result

    def test_unknown_operation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        cr = self._manage("create", summary="Test")
        tid = cr.split("Created task ")[1].split(":")[0]
        result = self._manage("invalid_op", id=tid)
        assert "error" in result.lower()

    def test_start_nonexistent_task(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        result = self._manage("start", id="T999")
        assert "not found" in result.lower()

    def test_task_id_increments(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        r1 = self._manage("create", summary="First")
        r2 = self._manage("create", summary="Second")
        id1 = r1.split("Created task ")[1].split(":")[0]
        id2 = r2.split("Created task ")[1].split(":")[0]
        assert id1 != id2

    def test_list_filter_by_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        cr = self._manage("create", summary="To filter")
        tid = cr.split("Created task ")[1].split(":")[0]
        self._manage("done", id=tid)
        result = self._manage("list", status="done")
        assert "To filter" in result

    def test_task_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.task_tool import task_tool
        assert task_tool.name == "task"


class TestHistoryToolTokenize:
    def test_tokenize_basic(self):
        from RxyCode.RxyCode1_1_0.tools.history_tool import _tokenize
        tokens = _tokenize("Hello World test-123")
        assert "hello" in tokens
        assert "world" in tokens

    def test_tokenize_empty(self):
        from RxyCode.RxyCode1_1_0.tools.history_tool import _tokenize
        assert _tokenize("") == []

    def test_tokenize_special_chars(self):
        from RxyCode.RxyCode1_1_0.tools.history_tool import _tokenize
        tokens = _tokenize("hello! @world? #test")
        assert "hello" in tokens
        assert "world" in tokens

    def test_tokenize_mixed_case(self):
        from RxyCode.RxyCode1_1_0.tools.history_tool import _tokenize
        tokens = _tokenize("Hello HELLO hello")
        assert all(t == "hello" for t in tokens)

    def test_tokenize_numbers(self):
        from RxyCode.RxyCode1_1_0.tools.history_tool import _tokenize
        tokens = _tokenize("test123 abc456")
        assert "test123" in tokens

    def test_tokenize_hyphens(self):
        from RxyCode.RxyCode1_1_0.tools.history_tool import _tokenize
        tokens = _tokenize("my-variable-name")
        assert "my-variable-name" in tokens


class TestHistoryToolBM25:
    def test_bm25_basic(self):
        from RxyCode.RxyCode1_1_0.tools.history_tool import _bm25
        query = ["python", "function"]
        doc = ["python", "function", "test", "code"]
        df = {"python": 1, "function": 1}
        score = _bm25(query, doc, avg_dl=4.0, N=1, df=df)
        assert score > 0

    def test_bm25_no_overlap(self):
        from RxyCode.RxyCode1_1_0.tools.history_tool import _bm25
        score = _bm25(["python"], ["java"], avg_dl=1.0, N=1, df={"python": 1})
        assert score == 0.0

    def test_bm25_empty_doc(self):
        from RxyCode.RxyCode1_1_0.tools.history_tool import _bm25
        score = _bm25(["test"], [], avg_dl=0, N=1, df={"test": 1})
        assert score == 0.0

    def test_bm25_empty_query(self):
        from RxyCode.RxyCode1_1_0.tools.history_tool import _bm25
        score = _bm25([], ["test"], avg_dl=1.0, N=1, df={})
        assert score == 0.0

    def test_bm25_zero_avg_dl(self):
        from RxyCode.RxyCode1_1_0.tools.history_tool import _bm25
        score = _bm25(["test"], ["test"], avg_dl=0, N=1, df={"test": 1})
        assert score == 0.0


class TestToolInstaller:
    def test_is_package_installed_true(self):
        from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller
        inst = ToolInstaller()
        assert inst.is_package_installed("os") is True

    def test_is_package_installed_false(self):
        from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller
        inst = ToolInstaller()
        assert inst.is_package_installed("nonexistent_xyz") is False

    def test_find_tool_package_known(self):
        from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller
        inst = ToolInstaller()
        assert inst.find_tool_package("pandas") == "pandas"

    def test_find_tool_package_unknown(self):
        from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller
        inst = ToolInstaller()
        assert inst.find_tool_package("Some-Tool") == "some_tool"

    def test_find_tool_package_case_insensitive(self):
        from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller
        inst = ToolInstaller()
        assert inst.find_tool_package("PANDAS") == "pandas"

    def test_find_tool_package_bs4_alias(self):
        from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller
        inst = ToolInstaller()
        assert inst.find_tool_package("bs4") == "beautifulsoup4"

    def test_find_tool_package_pil_alias(self):
        from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller
        inst = ToolInstaller()
        assert inst.find_tool_package("PIL") == "pillow"

    def test_get_install_suggestion_known(self):
        from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller
        inst = ToolInstaller()
        result = inst.get_install_suggestion("pandas")
        assert "pip install pandas" in result

    def test_get_install_suggestion_unknown(self):
        from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller
        inst = ToolInstaller()
        result = inst.get_install_suggestion("SomePackage")
        assert "pip install" in result

    def test_global_instance_exists(self):
        from RxyCode.RxyCode1_1_0.tools.installer import tool_installer
        assert tool_installer is not None
