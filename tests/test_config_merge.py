"""Config default merge — partial user YAML must inherit safety defaults."""
from RxyCode.RxyCode1_1_0.config.settings import _deep_merge, _default_config


def test_deep_merge_inherits_missing_safety_defaults():
    merged = _deep_merge(_default_config(), {"active_model": "test-model"})
    assert merged["safety"]["enabled"] is True
    assert merged["safety"]["auto_approve"] == []
    assert merged["active_model"] == "test-model"
