"""layer=unit P7"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_u_p7_03_event_type_visible_in_protocol_and_client():
    """layer=unit U-P7-03 消费面验收：事件类型在 protocol/ 与 frontend/protocol-client 类型树可见
    （确定性静态断言：源文件结构/grep——非 codegen 运行步骤、不在 WAIVED_LIVE 之列）"""
    proto = REPO / "protocol" / "timeout_decision.py"
    assert proto.exists(), "protocol/timeout_decision.py 不存在"
    head = proto.read_text(encoding="utf-8")
    assert "class TimeoutDecisionEvent" in head
    assert "event/timeout_decision" in head

    notifications = (REPO / "protocol" / "notifications.py").read_text(encoding="utf-8")
    assert "TimeoutDecisionEvent" in notifications               # 通知面注册可见

    client_src = REPO / "frontend" / "protocol-client" / "src"
    ts_files = sorted(client_src.rglob("*.ts"))
    assert ts_files, "frontend/protocol-client 类型树缺失"
    body = "\n".join(p.read_text(encoding="utf-8") for p in ts_files)
    assert "TimeoutDecision" in body                             # TS 类型可见（codegen 产物或手写内建）
    assert "timeout_decision" in body
