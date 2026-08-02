"""Tests for appserver JSON-RPC approval broker."""

from __future__ import annotations

import asyncio

import pytest

from appserver.approval import JsonRpcApproval
from appserver.runtime import bind_prompt_context, reset_prompt_context
from core.safety.approval import ApprovalRequest
from core.safety.policy import RiskLevel


@pytest.mark.asyncio
async def test_jsonrpc_approval_round_trip():
    async def send_request(method: str, params: dict) -> dict:
        assert method == "approval/request"
        assert params["session_id"] == "s1"
        assert params["risk_level"] == "WRITE"
        return {"request_id": params["request_id"], "decision": "approved"}

    broker = JsonRpcApproval(send_request, timeout=5.0)
    tokens = bind_prompt_context("s1", None)
    try:
        decision = await broker.request_approval(
            ApprovalRequest(
                tool_name="write_file",
                args_summary={"path": "a.txt"},
                risk=RiskLevel.WRITE,
                approval_id="apr-1",
            )
        )
    finally:
        reset_prompt_context(tokens)
    assert decision.value == "approved"


@pytest.mark.asyncio
async def test_jsonrpc_approval_timeout_rejects():
    async def hang(_method: str, _params: dict) -> dict:
        await asyncio.sleep(0.2)
        return {"decision": "approved"}

    broker = JsonRpcApproval(hang, timeout=0.05)
    decision = await broker.request_approval(
        ApprovalRequest(
            tool_name="write_file",
            args_summary={},
            risk=RiskLevel.WRITE,
        )
    )
    assert decision.value == "rejected"