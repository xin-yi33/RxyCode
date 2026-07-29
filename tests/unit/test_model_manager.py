from config.model_manager import get_builtin_model_presets, resolve_model_preset


def test_volces_ark_preset_is_available_with_expected_defaults():
    presets = get_builtin_model_presets()

    assert "volces-ark" in presets
    preset = presets["volces-ark"]
    assert preset["name"] == "Volces Ark"
    assert preset["base_url"] == "https://ark.cn-beijing.volces.com/api/v3"
    assert preset["provider"] == "volces-ark"


def test_resolve_model_preset_accepts_volces_aliases():
    resolved = resolve_model_preset("volces")
    assert resolved["provider"] == "volces-ark"
    assert resolved["base_url"] == "https://ark.cn-beijing.volces.com/api/v3"
