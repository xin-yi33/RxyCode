"""
Tests for cache/text_normalizer.py - Text normalization for cache keys.
"""
import pytest


class TestNormalizeQuery:
    def _norm(self, text):
        from RxyCode.RxyCode1_1_0.cache.text_normalizer import normalize_query
        return normalize_query(text)

    def test_strips_whitespace(self):
        result = self._norm("  hello  world  ")
        assert "  " not in result

    def test_lowercases(self):
        result = self._norm("HELLO World")
        assert result == result.lower()

    def test_removes_punctuation(self):
        result = self._norm("hello, world!")
        assert "," not in result
        assert "!" not in result

    def test_strips_chinese_filler(self):
        # "请" and "帮我" are filler words that get stripped
        r1 = self._norm("请查看Python")
        r2 = self._norm("查看Python")
        # After stripping "请", synonym (查看->看), and lowercasing
        assert r1 == r2

    def test_empty_string(self):
        assert self._norm("") == ""

    def test_none_input(self):
        assert self._norm(None) == ""

    def test_chinese_punctuation(self):
        result = self._norm("你好，世界！")
        assert "，" not in result
        assert "！" not in result

    def test_idempotent(self):
        text = "请帮我解释Python，谢谢！"
        r1 = self._norm(text)
        r2 = self._norm(r1)
        assert r1 == r2

    def test_strips_english_filler(self):
        result = self._norm("please help me with Python")
        assert "please" not in result
        assert "help" not in result

    def test_synonym_standardization(self):
        result = self._norm("查看文件")
        assert "看" in result

    def test_preserves_core_content(self):
        result = self._norm("解释Python")
        assert "python" in result

    def test_newlines_collapsed(self):
        result = self._norm("line1\nline2\nline3")
        assert "\n" not in result

    def test_mixed_case_preserved_after_lower(self):
        result = self._norm("PyThOn")
        assert result == "python"


class TestNormalizeToolArgs:
    def _norm(self, args):
        from RxyCode.RxyCode1_1_0.cache.text_normalizer import normalize_tool_args
        return normalize_tool_args(args)

    def test_empty_dict(self):
        assert self._norm({}) == ""

    def test_none(self):
        assert self._norm(None) == ""

    def test_single_arg(self):
        result = self._norm({"path": "/tmp/test.py"})
        assert "path" in result
        assert "/tmp/test.py" in result

    def test_order_independent(self):
        r1 = self._norm({"a": "1", "b": "2"})
        r2 = self._norm({"b": "2", "a": "1"})
        assert r1 == r2

    def test_different_args_different_result(self):
        r1 = self._norm({"path": "/a/b.py"})
        r2 = self._norm({"path": "/c/d.py"})
        assert r1 != r2

    def test_strips_whitespace_in_values(self):
        result = self._norm({"path": "  /tmp/test.py  "})
        assert "  " not in result or "/tmp/test.py" in result

    def test_non_string_value(self):
        result = self._norm({"count": 42})
        assert "42" in result

    def test_multiple_args(self):
        result = self._norm({"a": "1", "b": "2", "c": "3"})
        assert "a=1" in result or "a=" in result
        assert "b=2" in result or "b=" in result
        assert "c=3" in result or "c=" in result


class TestExtractIntent:
    def _extract(self, text):
        from RxyCode.RxyCode1_1_0.cache.text_normalizer import extract_intent
        return extract_intent(text)

    def test_single_sentence(self):
        result = self._extract("hello world")
        assert "hello" in result

    def test_multiple_sentences_chinese(self):
        result = self._extract("第一句话。第二句话")
        assert "第二句话" in result

    def test_last_sentence_returned(self):
        result = self._extract("old sentence。current request")
        assert "current" in result

    def test_empty_string(self):
        assert self._extract("") == ""

    def test_with_newlines(self):
        result = self._extract("line1\nline2")
        assert "line2" in result

    def test_with_question_marks(self):
        result = self._extract("what is python？what is java")
        assert "java" in result
