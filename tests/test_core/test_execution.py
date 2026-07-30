"""
Tests for execution/tool_orchestrator.py.
"""
from unittest.mock import MagicMock


class TestToolOrchestrator:
    def _make_orchestrator(self):
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
        return ToolOrchestrator()

    def _make_tool(self, name="test_tool", desc="A test"):
        tool = MagicMock()
        tool.name = name
        tool.description = desc
        return tool

    def test_init(self):
        orch = self._make_orchestrator()
        assert orch is not None

    def test_register_tool(self):
        orch = self._make_orchestrator()
        tool = self._make_tool("mytool")
        orch.register("mytool", tool)
        assert orch.get("mytool") is tool

    def test_get_nonexistent(self):
        orch = self._make_orchestrator()
        assert orch.get("nonexistent") is None

    def test_register_many(self):
        orch = self._make_orchestrator()
        t1 = self._make_tool("t1")
        t2 = self._make_tool("t2")
        orch.register_many({"t1": t1, "t2": t2})
        assert orch.get("t1") is t1
        assert orch.get("t2") is t2

    def test_get_all(self):
        orch = self._make_orchestrator()
        t1 = self._make_tool("t1")
        t2 = self._make_tool("t2")
        orch.register("t1", t1)
        orch.register("t2", t2)
        all_tools = orch.get_all()
        assert len(all_tools) == 2

    def test_list_names(self):
        orch = self._make_orchestrator()
        orch.register("alpha", self._make_tool())
        orch.register("beta", self._make_tool())
        names = orch.list_names()
        assert "alpha" in names
        assert "beta" in names

    def test_empty_list_names(self):
        orch = self._make_orchestrator()
        assert orch.list_names() == []

    def test_empty_get_all(self):
        orch = self._make_orchestrator()
        assert orch.get_all() == {}

    def test_select_tools_empty_hint(self):
        orch = self._make_orchestrator()
        t1 = self._make_tool("read")
        orch.register("read", t1)
        result = orch.select_tools([])
        assert isinstance(result, list)

    def test_select_tools_with_hint(self):
        orch = self._make_orchestrator()
        t1 = self._make_tool("read", "Read files")
        t2 = self._make_tool("write", "Write files")
        orch.register("read", t1)
        orch.register("write", t2)
        result = orch.select_tools(["read"])
        assert isinstance(result, list)

    def test_select_tools_no_match_returns_readonly_subset(self):
        """On hint mismatch, return only the read-only core subset
        (read/view/grep/glob/ls style), not every tool."""
        orch = self._make_orchestrator()
        read_t = self._make_tool("read")
        write_t = self._make_tool("write")
        bash_t = self._make_tool("bash")
        orch.register("read", read_t)
        orch.register("write", write_t)
        orch.register("bash", bash_t)
        result = orch.select_tools(["nonexistent_hint"])
        assert read_t in result
        assert write_t not in result
        assert bash_t not in result

    def test_select_tools_no_match_empty_registry_returns_empty(self):
        orch = self._make_orchestrator()
        result = orch.select_tools(["nonexistent_hint"])
        assert result == []

    def test_select_tools_no_match_only_write_tools_returns_empty(self):
        orch = self._make_orchestrator()
        orch.register("write", self._make_tool("write"))
        orch.register("edit", self._make_tool("edit"))
        result = orch.select_tools(["nonexistent_hint"])
        assert result == []

    def test_select_tools_empty_hint_still_returns_all(self):
        orch = self._make_orchestrator()
        orch.register("write", self._make_tool("write"))
        orch.register("read", self._make_tool("read"))
        result = orch.select_tools([])
        assert len(result) == 2

    def test_register_overwrites(self):
        orch = self._make_orchestrator()
        t1 = self._make_tool("tool1")
        t2 = self._make_tool("tool1")
        orch.register("tool1", t1)
        orch.register("tool1", t2)
        assert orch.get("tool1") is t2

    def test_register_many_empty(self):
        orch = self._make_orchestrator()
        orch.register_many({})
        assert orch.get_all() == {}

    def test_select_tools_matching_description(self):
        orch = self._make_orchestrator()
        t = self._make_tool("xyz", "Read file contents")
        orch.register("xyz", t)
        result = orch.select_tools(["read"])
        assert t in result

    def test_select_tools_case_insensitive(self):
        orch = self._make_orchestrator()
        t = self._make_tool("Read")
        orch.register("Read", t)
        result = orch.select_tools(["read"])
        assert t in result

    def test_web_search_alias_selects_registered_websearch_tool(self):
        orch = self._make_orchestrator()
        search = self._make_tool("websearch", "Search the web")
        orch.register("websearch", search)
        assert orch.get("web_search") is search
        assert orch.select_tools(["web_search"]) == [search]

    def test_unknown_hint_readonly_fallback_includes_research_tools(self):
        orch = self._make_orchestrator()
        search = self._make_tool("websearch")
        fetch = self._make_tool("webfetch")
        write = self._make_tool("write")
        orch.register("websearch", search)
        orch.register("webfetch", fetch)
        orch.register("write", write)

        result = orch.select_tools(["unknown_external_fact_tool"])

        assert search in result
        assert fetch in result
        assert write not in result

    def test_read_effect_filters_write_and_unknown_tools_from_llm(self):
        from langchain_core.tools import StructuredTool

        from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

        def inspect() -> str:
            """Inspect data."""
            return "read"

        def mutate() -> str:
            """Mutate data."""
            return "write"

        orch = self._make_orchestrator()
        orch.register(
            "read",
            StructuredTool.from_function(inspect, name="read"),
        )
        orch.register(
            "write",
            StructuredTool.from_function(mutate, name="write"),
        )
        orch.register(
            "external_unknown",
            StructuredTool.from_function(mutate, name="external_unknown"),
        )

        proxies = orch.select_safe_tools([], max_risk=RiskLevel.READ)

        assert [tool.name for tool in proxies] == ["read"]
