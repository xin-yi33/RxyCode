from __future__ import annotations

from RxyCode.RxyCode1_1_0.utils.slash_help import build_help_text


def test_help_explains_expert_team_default_and_how_to_invoke() -> None:
    text = build_help_text()
    assert "默认关闭" in text
    assert "不会自动拉专家团" in text
    assert "/team <可拆任务>" in text
    assert "/agents on|off" in text
    assert "/why-mode" in text
    assert "子代理" in text
    assert "/children" in text
    assert "子代理（默认开启" in text
    assert "/addmodel" in text
    assert "密钥不写入命令" in text
    assert "<key>" not in text
    assert "/permission" in text


def test_help_text_has_no_credential_placeholders() -> None:
    text = build_help_text()
    lowered = text.lower()
    for needle in ("sk-", "api_key", "<key>", "secret"):
        assert needle not in lowered
