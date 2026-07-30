"""
Tests for utils/i18n.py - Internationalization.

Covers: STRINGS dict, I18n class, translation, language switching, global instance.
"""
import pytest


class TestStrings:
    def test_strings_has_zh(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        assert "zh" in STRINGS

    def test_strings_has_en(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        assert "en" in STRINGS

    def test_zh_has_keys(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        assert len(STRINGS["zh"]) > 10

    def test_en_has_keys(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        assert len(STRINGS["en"]) > 10

    def test_keys_match_between_languages(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        zh_keys = set(STRINGS["zh"].keys())
        en_keys = set(STRINGS["en"].keys())
        # Keys should match between languages
        assert zh_keys == en_keys, f"Keys differ: zh-only={zh_keys-en_keys}, en-only={en_keys-zh_keys}"

    def test_banner_subtitle_zh(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        assert "banner_subtitle" in STRINGS["zh"]

    def test_banner_subtitle_en(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        assert "banner_subtitle" in STRINGS["en"]

    def test_mode_keys_zh(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        assert "mode_build" in STRINGS["zh"]
        assert "mode_plan" in STRINGS["zh"]
        assert "mode_compose" in STRINGS["zh"]

    def test_msg_keys_present(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        for lang in ["zh", "en"]:
            assert "msg_goodbye" in STRINGS[lang]
            assert "msg_cleared" in STRINGS[lang]
            assert "msg_unknown_command" in STRINGS[lang]


class TestI18n:
    def _make(self, lang="zh"):
        from RxyCode.RxyCode1_1_0.utils.i18n import I18n
        return I18n(lang=lang)

    def test_default_lang(self):
        i18n = self._make()
        assert i18n.lang == "zh"

    def test_english_lang(self):
        i18n = self._make(lang="en")
        assert i18n.lang == "en"

    def test_translate_zh(self):
        i18n = self._make(lang="zh")
        result = i18n.t("banner_subtitle")
        assert "AI" in result or "编码" in result

    def test_translate_en(self):
        i18n = self._make(lang="en")
        result = i18n.t("banner_subtitle")
        assert "AI" in result or "Coding" in result

    def test_translate_missing_key(self):
        i18n = self._make()
        result = i18n.t("nonexistent_key_12345")
        assert result == "nonexistent_key_12345"

    def test_set_lang(self):
        i18n = self._make(lang="zh")
        i18n.set_lang("en")
        assert i18n.lang == "en"

    def test_set_lang_invalid(self):
        i18n = self._make(lang="zh")
        i18n.set_lang("fr")
        assert i18n.lang == "zh"  # Stays at previous

    def test_translate_with_format(self):
        i18n = self._make(lang="en")
        result = i18n.t("mode_switched", mode="Build")
        assert "Build" in result

    def test_translate_with_format_zh(self):
        i18n = self._make(lang="zh")
        result = i18n.t("mode_switched", mode="构建")
        assert "构建" in result

    def test_translate_with_missing_format_key(self):
        i18n = self._make(lang="en")
        # If format fails, should return the template string
        result = i18n.t("mode_switched", wrong_key="value")
        assert isinstance(result, str)

    def test_translate_empty_string(self):
        i18n = self._make()
        result = i18n.t("")
        assert result == ""

    def test_lang_property(self):
        i18n = self._make(lang="en")
        assert i18n.lang == "en"

    def test_switch_and_translate(self):
        i18n = self._make(lang="zh")
        zh_result = i18n.t("msg_goodbye")
        i18n.set_lang("en")
        en_result = i18n.t("msg_goodbye")
        assert zh_result != en_result


class TestGlobalInstance:
    def test_global_instance_exists(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import i18n
        assert i18n is not None

    def test_global_instance_is_i18n(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import i18n, I18n
        assert isinstance(i18n, I18n)

    def test_global_instance_has_lang(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import i18n
        assert i18n.lang in ("zh", "en")

    def test_global_instance_translate(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import i18n
        result = i18n.t("msg_goodbye")
        assert isinstance(result, str)
        assert len(result) > 0


class TestAllTranslations:
    """Verify every key has a non-empty translation in both languages."""

    def test_all_zh_translations_nonempty(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        for key, value in STRINGS["zh"].items():
            assert isinstance(value, str), f"Key {key} is not a string"
            assert len(value) > 0, f"Key {key} has empty translation"

    def test_all_en_translations_nonempty(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        for key, value in STRINGS["en"].items():
            assert isinstance(value, str), f"Key {key} is not a string"
            assert len(value) > 0, f"Key {key} has empty translation"

    def test_all_zh_translations_are_chinese(self):
        """Spot check that Chinese translations actually contain Chinese characters."""
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        # Check a few known Chinese translations
        assert any(ord(c) > 0x4e00 for c in STRINGS["zh"]["msg_goodbye"])
        assert any(ord(c) > 0x4e00 for c in STRINGS["zh"]["msg_cleared"])

    def test_all_en_translations_are_ascii(self):
        """Spot check that English translations are ASCII."""
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        assert STRINGS["en"]["msg_goodbye"].isascii()
        assert STRINGS["en"]["msg_cleared"].isascii()

    def test_command_keys_present(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        for lang in ["zh", "en"]:
            assert "cmd_help" in STRINGS[lang]
            assert "cmd_exit" in STRINGS[lang]
            assert "cmd_clear" in STRINGS[lang]

    def test_agent_keys_present(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        for lang in ["zh", "en"]:
            assert "agent_thinking" in STRINGS[lang]
            assert "agent_complete" in STRINGS[lang]
            assert "agent_error" in STRINGS[lang]

    def test_memory_keys_present(self):
        from RxyCode.RxyCode1_1_0.utils.i18n import STRINGS
        for lang in ["zh", "en"]:
            assert "mem_saved" in STRINGS[lang]
            assert "mem_removed" in STRINGS[lang]
            assert "mem_not_found" in STRINGS[lang]
