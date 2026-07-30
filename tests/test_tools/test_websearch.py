"""
Tests for tools/websearch.py - Web search with multi-engine fallback.

Covers: search function, engine selection, error handling, tool structure.
"""
import pytest
from unittest.mock import patch, MagicMock
import httpx


class TestWebSearchInput:
    def test_default_values(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import WebSearchInput
        wsi = WebSearchInput(query="test")
        assert wsi.query == "test"
        assert wsi.numResults == 5

    def test_custom_values(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import WebSearchInput
        wsi = WebSearchInput(query="python tutorial", numResults=10)
        assert wsi.query == "python tutorial"
        assert wsi.numResults == 10


class TestSearchWeb:
    def test_empty_query(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import search_web
        with patch("RxyCode.RxyCode1_1_0.tools.websearch._search_baidu", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_duckduckgo", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_google", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_bing", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_via_redirect", return_value=[]):
            result = search_web("", 5)
            assert isinstance(result, str)

    def test_returns_string(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import search_web
        # Mock all engines to avoid real network calls
        with patch("RxyCode.RxyCode1_1_0.tools.websearch._search_baidu", return_value=["result 1"]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_duckduckgo", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_google", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_bing", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_via_redirect", return_value=[]):
            result = search_web("test query", 1)
            assert isinstance(result, str)
            assert "result 1" in result

    def test_num_results_limit(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import search_web
        with patch("RxyCode.RxyCode1_1_0.tools.websearch._search_baidu", return_value=["r1"]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_duckduckgo", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_google", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_bing", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_via_redirect", return_value=[]):
            result = search_web("python", 1)
            assert isinstance(result, str)

    def test_all_engines_fail_returns_error(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import search_web
        with patch("RxyCode.RxyCode1_1_0.tools.websearch._search_baidu", side_effect=Exception("fail")), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_duckduckgo", side_effect=Exception("fail")), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_google", side_effect=Exception("fail")), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_bing", side_effect=Exception("fail")), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_via_redirect", side_effect=Exception("fail")):
            result = search_web("test", 5)
            assert "error" in result.lower() or "no results" in result.lower()


class TestEngineFunctions:
    def test_duckduckgo_returns_list(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import _search_duckduckgo
        # Mock httpx to avoid actual network calls
        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.text = '<a rel="nofollow" class="result__a" href="http://example.com">Title</a>'
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp
            result = _search_duckduckgo("test", 5)
            assert isinstance(result, list)

    def test_google_returns_list(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import _search_google
        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.text = '<a href="/url?q=http://example.com&sa=U">Title</a>'
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
            result = _search_google("test", 5)
            assert isinstance(result, list)

    def test_bing_returns_list(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import _search_bing
        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.text = '<li class="b_algo"><a href="http://example.com">Title</a><p>Snippet</p></li>'
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
            result = _search_bing("test", 5)
            assert isinstance(result, list)

    def test_baidu_returns_list(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import _search_baidu
        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.text = '<h3><a href="http://example.com">Title</a></h3>'
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
            result = _search_baidu("test", 5)
            assert isinstance(result, list)

    def test_lite_ddg_returns_list(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import _search_via_redirect
        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.text = 'rel="nofollow" href="http://example.com">Title</a>'
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp
            result = _search_via_redirect("test", 5)
            assert isinstance(result, list)

    def test_duckduckgo_max_results(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import _search_duckduckgo
        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.text = """
            <a rel="nofollow" class="result__a" href="http://1.com">1</a>
            <span class="result__snippet">s1</span>
            <a rel="nofollow" class="result__a" href="http://2.com">2</a>
            <span class="result__snippet">s2</span>
            <a rel="nofollow" class="result__a" href="http://3.com">3</a>
            <span class="result__snippet">s3</span>
            """
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp
            result = _search_duckduckgo("test", 2)
            assert len(result) <= 2


class TestWebSearchTool:
    def test_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import websearch_tool
        assert websearch_tool.name == "websearch"

    def test_tool_description(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import websearch_tool
        assert isinstance(websearch_tool.description, str)

    def test_tool_has_args_schema(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import websearch_tool
        assert websearch_tool.args_schema is not None

    def test_tool_invoke(self):
        from RxyCode.RxyCode1_1_0.tools.websearch import websearch_tool
        with patch("RxyCode.RxyCode1_1_0.tools.websearch._search_baidu", return_value=["mock result"]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_duckduckgo", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_google", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_bing", return_value=[]), \
             patch("RxyCode.RxyCode1_1_0.tools.websearch._search_via_redirect", return_value=[]):
            result = websearch_tool.invoke({"query": "python", "numResults": 1})
            assert isinstance(result, str)
            assert "mock result" in result

    def test_search_engines_list(self):
        """Verify the engines list contains expected engines."""
        from RxyCode.RxyCode1_1_0.tools.websearch import _search_baidu, _search_duckduckgo, _search_google, _search_bing, _search_via_redirect
        # These should be callable functions
        assert callable(_search_baidu)
        assert callable(_search_duckduckgo)
        assert callable(_search_google)
        assert callable(_search_bing)
        assert callable(_search_via_redirect)
