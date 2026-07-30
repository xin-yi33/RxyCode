"""
Tests for utils/i18n.py - Internationalization.

Covers: translation, language switching, format interpolation, fallback.
"""
import pytest


class TestI18n:
    def _make_i18n(self, lang="zh"):
        from RxyCode.RxyCode1_1_0.utils.i18n import I18n
        return I18n(lang)

    def test_default_language_zh(self):
        i18n = self._make_i18n()
        assert i18n.lang == "zh"

    def test_english_language(self):
        i18n = self._make_i18n("en")
        assert i18n.lang == "en"

    def test_translate_zh(self):
        i18n = self._make_i18n("zh")
        result = i18n.t("mode_build")
        assert result == "构建"

    def test_translate_en(self):
        i18n = self._make_i18n("en")
        result = i18n.t("mode_build")
        assert result == "Build"

    def test_set_lang(self):
        i18n = self._make_i18n("zh")
        i18n.set_lang("en")
        assert i18n.lang == "en"
        assert i18n.t("mode_build") == "Build"

    def test_set_invalid_lang_ignored(self):
        i18n = self._make_i18n("zh")
        i18n.set_lang("fr")
        assert i18n.lang == "zh"

    def test_missing_key_returns_key(self):
        i18n = self._make_i18n("zh")
        result = i18n.t("nonexistent_key")
        assert result == "nonexistent_key"

    def test_format_interpolation(self):
        i18n = self._make_i18n("zh")
        result = i18n.t("mode_switched", mode="构建")
        assert "构建" in result

    def test_format_interpolation_en(self):
        i18n = self._make_i18n("en")
        result = i18n.t("mode_switched", mode="Build")
        assert "Build" in result

    def test_format_with_missing_kwarg(self):
        i18n = self._make_i18n("zh")
        # Should not crash if kwarg is missing
        result = i18n.t("mode_switched")
        assert isinstance(result, str)

    def test_empty_key(self):
        i18n = self._make_i18n()
        result = i18n.t("")
        assert result == ""

    def test_lang_property(self):
        i18n = self._make_i18n("en")
        assert i18n.lang == "en"

    def test_set_lang_back_to_zh(self):
        i18n = self._make_i18n("zh")
        i18n.set_lang("en")
        i18n.set_lang("zh")
        assert i18n.lang == "zh"
        assert i18n.t("mode_build") == "构建"

    def test_t_with_no_kwargs(self):
        i18n = self._make_i18n("zh")
        result = i18n.t("msg_goodbye")
        assert result == "再见！"

    def test_all_zh_keys_exist_in_en(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        zh_keys = set(STRINGS["zh"].keys())
        en_keys = set(STRINGS["en"].keys())
        # Both should have the same keys
        assert zh_keys == en_keys

    def test_global_instance_exists(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import i18n
        assert i18n is not None
        assert i18n.lang in ("zh", "en")


class TestI18nAllKeys:
    """Test every key in the STRINGS dict to ensure coverage."""

    def _make_i18n(self, lang="zh"):
        from RxyCode.RxyCode1_1_0.utils.i18n import I18n
        return I18n(lang)

    def test_zh_banner_subtitle(self):
        i18n = self._make_i18n("zh")
        assert i18n.t("banner_subtitle") == "通用 AI Agent"

    def test_en_banner_subtitle(self):
        i18n = self._make_i18n("en")
        assert i18n.t("banner_subtitle") == "General-Purpose AI Agent"

    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_compose_mode_describes_plan_then_execution(self, lang):
        i18n = self._make_i18n(lang)
        description = i18n.t("cmd_compose").lower()
        assert "子代理" not in description
        assert "sub-agent" not in description
        assert "plan" in description or "规划" in description

    def test_zh_cmd_clear(self):
        i18n = self._make_i18n("zh")
        assert "清除" in i18n.t("cmd_clear")

    def test_en_cmd_clear(self):
        i18n = self._make_i18n("en")
        assert "Clear" in i18n.t("cmd_clear")

    def test_zh_msg_goodbye(self):
        i18n = self._make_i18n("zh")
        assert i18n.t("msg_goodbye") == "再见！"

    def test_en_msg_goodbye(self):
        i18n = self._make_i18n("en")
        assert i18n.t("msg_goodbye") == "Goodbye!"

    def test_zh_agent_thinking(self):
        i18n = self._make_i18n("zh")
        assert i18n.t("agent_thinking") == "思考中"

    def test_en_agent_thinking(self):
        i18n = self._make_i18n("en")
        assert i18n.t("agent_thinking") == "Thinking"

    def test_zh_agent_complete(self):
        i18n = self._make_i18n("zh")
        assert i18n.t("agent_complete") == "完成"

    def test_en_agent_complete(self):
        i18n = self._make_i18n("en")
        assert i18n.t("agent_complete") == "Complete"

    def test_zh_msg_cleared(self):
        i18n = self._make_i18n("zh")
        assert i18n.t("msg_cleared") == "上下文已清除"

    def test_en_msg_cleared(self):
        i18n = self._make_i18n("en")
        assert i18n.t("msg_cleared") == "Context cleared"

    def test_zh_cap_code(self):
        i18n = self._make_i18n("zh")
        assert i18n.t("cap_code") == "代码开发"

    def test_en_cap_code(self):
        i18n = self._make_i18n("en")
        assert i18n.t("cap_code") == "Code Development"

    def test_zh_tool_not_found(self):
        i18n = self._make_i18n("zh")
        result = i18n.t("tool_not_found", tool="mytool")
        assert "mytool" in result

    def test_en_tool_not_found(self):
        i18n = self._make_i18n("en")
        result = i18n.t("tool_not_found", tool="mytool")
        assert "mytool" in result

    def test_zh_status_tokens(self):
        i18n = self._make_i18n("zh")
        assert i18n.t("status_tokens") == "Token"

    def test_en_status_tokens(self):
        i18n = self._make_i18n("en")
        assert i18n.t("status_tokens") == "Tokens"

    def test_zh_help_title(self):
        i18n = self._make_i18n("zh")
        assert "可用命令" in i18n.t("help_title")

    def test_en_help_title(self):
        i18n = self._make_i18n("en")
        assert "Available Commands" in i18n.t("help_title")

    def test_zh_mem_saved(self):
        i18n = self._make_i18n("zh")
        assert i18n.t("mem_saved") == "记忆已保存"

    def test_en_mem_saved(self):
        i18n = self._make_i18n("en")
        assert i18n.t("mem_saved") == "Memory saved"

    def test_zh_sched_no_tasks(self):
        i18n = self._make_i18n("zh")
        assert i18n.t("sched_no_tasks") == "没有定时任务"

    def test_en_sched_no_tasks(self):
        i18n = self._make_i18n("en")
        assert i18n.t("sched_no_tasks") == "No scheduled tasks"

    def test_zh_capability_greeting(self):
        i18n = self._make_i18n("zh")
        assert "你好" in i18n.t("capability_greeting")

    def test_en_capability_greeting(self):
        i18n = self._make_i18n("en")
        assert "Hello" in i18n.t("capability_greeting")
