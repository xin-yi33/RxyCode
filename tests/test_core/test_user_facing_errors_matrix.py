"""Table-driven user-facing error mapping matrices (E2/E3/E8)."""

from __future__ import annotations

import itertools
import re

import pytest

from RxyCode.RxyCode1_1_0.utils import user_facing_errors as ufe

_FORBIDDEN = re.compile(
    r"synthesizer|claim\s*manifest|grounded\s*claims?",
    re.IGNORECASE,
)

_BUILD_SUFFIXES = (
    "Task not verified: deploy (failed)",
    "Synthesizer produced no grounded claims",
    "Synthesis answer contains text outside its claim manifest",
    "Synthesizer output was not valid grounded JSON.",
    "Final response differs from the verified synthesis manifest",
    "Passed leaf has no grounded final claim: t1",
    "Synthesizer produced no final response",
    "Missing side-effect evidence for write task",
)

_EVIDENCE_SUFFIXES = (
    "Tool bash did not complete: failed",
    "Tool read did not complete: cancelled",
    "Tool write did not complete: timeout",
    "Tool patch did not complete: error",
    "Tool grep did not complete: failed",
)

_GROUNDING_MARKERS = ufe._GROUNDING_MARKERS

_TIMEOUT_VARIANTS = (
    "TimeoutError: operation timed out after 600s",
    "Request timed out waiting for synthesizer",
    "connection timeout after 30s",
    "TIMEOUT: executor stalled",
    # 2026-09-23: 内部时钟文案不含 "timeout" 字样，曾漏映射成 MSG_DEFAULT，
    # 造成「报错不固定」（用户报告）。三条时钟文案统一进 MSG_TIMEOUT。
    "provider produced no first response event before the deadline",
    "provider stopped producing stream events before the idle deadline",
    "provider connect handshake exceeded the connect deadline",
)

_CANCEL_VARIANTS = (
    "Cancelled",
    "cancelled",
    "CancelledError: user cancelled",
    "cancel requested by client",
)

_BUILD_CASES = [f"[Build incomplete: {suffix}]" for suffix in _BUILD_SUFFIXES]
_EVIDENCE_CASES = [f"[evidence failed: {suffix}]" for suffix in _EVIDENCE_SUFFIXES]
_GROUNDING_CASES = [
    f"Internal: {marker} detected in pipeline stage {idx}"
    for marker, idx in itertools.product(_GROUNDING_MARKERS, range(1, 4))
]
_DEFAULT_CASES = [
    f"unexpected internal failure code {code}"
    for code in range(100, 160)
]


def _map(raw: str) -> str:
    return ufe.to_user_facing_error(raw)


def _assert_friendly(raw: str, friendly: str) -> None:
    assert friendly
    assert not _FORBIDDEN.search(friendly), friendly
    assert "manifest" not in friendly.lower()
    assert "grounded" not in friendly.lower()
    # 2026-09-23：消息可以带「\n原因：...」后缀（原始错误关键信息），
    # 不再要求精确匹配。
    known = (
        ufe.MSG_BUILD_INCOMPLETE,
        ufe.MSG_GROUNDING,
        ufe.MSG_TOOL_INTERRUPTED,
        ufe.MSG_TIMEOUT,
        ufe.MSG_CANCELLED,
        ufe.MSG_DEFAULT,
        ufe.MSG_MODEL_PAUSED,
        ufe.MSG_TOOL_REJECTED,
        # 模型停用文案的两种开头（带/不带模型名）。
        "模型 ",
        "当前模型",
    )
    assert any(friendly.startswith(msg) for msg in known), (
        f"消息不以任何已知模板开头: {friendly!r}"
    )


@pytest.mark.parametrize("raw", _BUILD_CASES)
def test_build_incomplete_matrix(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    lowered = raw.lower()
    # 2026-09-23：消息可以带「\n原因：...」后缀，用 startswith 判断。
    if any(marker in lowered for marker in ufe._GROUNDING_MARKERS):
        assert friendly.startswith(ufe.MSG_GROUNDING)
    else:
        assert friendly.startswith(ufe.MSG_BUILD_INCOMPLETE)


@pytest.mark.parametrize("raw", _EVIDENCE_CASES)
def test_evidence_failed_matrix(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    if "timeout" in raw.lower():
        assert friendly.startswith(ufe.MSG_TIMEOUT)
    else:
        assert friendly.startswith(ufe.MSG_TOOL_INTERRUPTED)


@pytest.mark.parametrize("raw", _GROUNDING_CASES)
def test_grounding_marker_matrix(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    assert friendly.startswith(ufe.MSG_GROUNDING)


@pytest.mark.parametrize("raw", _TIMEOUT_VARIANTS)
def test_timeout_matrix(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    assert friendly.startswith(ufe.MSG_TIMEOUT)


@pytest.mark.parametrize("raw", _CANCEL_VARIANTS)
def test_cancelled_matrix(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    assert friendly.startswith(ufe.MSG_CANCELLED)


@pytest.mark.parametrize("raw", _DEFAULT_CASES)
def test_unknown_errors_map_to_default(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    assert friendly.startswith(ufe.MSG_DEFAULT)


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_empty_input_matrix(raw):
    assert _map(raw) == ufe.MSG_DEFAULT


def test_upstream_403_without_credits_is_the_only_quota_sentence():
    raw = "Error code: 403 - {'error': {'code': 'insufficient_quota', 'message': 'billing hard limit'}}"
    assert ufe.to_user_facing_error(raw) == "您没有额度了"
    assert ufe.to_user_facing_error("Error code: 403 - invalid api key") != "您没有额度了"


# ---- 模型下线（MODEL_UNAVAILABLE, 2026-10-28 现场） ---------------------------

_MODEL_GONE_RAWS = (
    "APIStatusError: Error code: 410 - {'type': 'error', 'error': "
    "{'type': 'ModelDeprecated', 'message': 'Model deepseek-flash is deprecated'}}",
    "NotFoundError: Error code: 404 - {'error': {'type': 'model_not_found', "
    "'message': \"The model `deepseek-flash` does not exist\"}}",
    "openai.NotFoundError: model deepseek-flash does not exist",
)


@pytest.mark.parametrize("raw", _MODEL_GONE_RAWS)
def test_model_gone_maps_to_model_unavailable_message(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    # 文案可读、提到模型与切换路径，不把原始报文内联进正文。
    assert "停用" in friendly
    assert "换一个模型" in friendly or "换一个模型后重试" in friendly
    assert "410" not in friendly and "APIStatusError" not in friendly


def test_upstream_400_model_is_unavailable_maps_to_model_unavailable():
    """HTTP 400 server_error 包装的「Model is unavailable」（上游网关形态）
    同样是模型停用 —— 必须落 MODEL_UNAVAILABLE，不能漏成普通 400。"""
    raw = (
        "Error code: 400 - {'error': {'type': 'server_error', 'message': "
        "'Upstream request failed: Model is unavailable.'}}"
    )
    assert ufe.is_model_unavailable(raw)
    info = ufe.classify_user_error(raw, provider_name="OpenCode Go")
    assert info is not None
    assert info["code"] == ufe.MODEL_UNAVAILABLE
    friendly = ufe.to_user_facing_error(raw, provider_name="OpenCode Go")
    _assert_friendly(raw, friendly)
    assert "停用" in friendly
    assert "换一个模型" in friendly
    # 终态：映射出的用户文案必须判 failed（run 不可写成「已完成」）。
    assert ufe.user_facing_kind(friendly) == "failed"


@pytest.mark.parametrize("phrase", [
    "model is unavailable",
    "model unavailable",
    "no such model",
    "MODEL IS UNAVAILABLE",
])
def test_model_unavailable_phrases_are_case_insensitive(phrase: str):
    assert ufe.is_model_unavailable(f"Upstream request failed: {phrase}")


def test_generic_400_without_model_context_is_not_model_unavailable():
    """保守边界：与模型无关的普通 400（参数校验等）不得误判 MODEL_UNAVAILABLE。"""
    raw = (
        "Error code: 400 - {'error': {'type': 'invalid_request_error', "
        "'message': 'temperature must be between 0 and 2'}}"
    )
    assert not ufe.is_model_unavailable(raw)
    assert ufe.classify_user_error(raw) is None


def test_model_gone_message_names_model_and_provider():
    raw = _MODEL_GONE_RAWS[0]
    friendly = ufe.to_user_facing_error(
        raw, model_name="deepseek-flash", provider_name="OpenCode Go"
    )
    assert friendly == (
        "模型 deepseek-flash 已被服务商（OpenCode Go）停用，"
        "请在模型选择中换一个模型后重试。"
    )


def test_classify_user_error_extracts_model_from_raw():
    info = ufe.classify_user_error(
        _MODEL_GONE_RAWS[0], provider_name="OpenCode Go"
    )
    assert info is not None
    assert info["code"] == ufe.MODEL_UNAVAILABLE
    assert info["model"] == "deepseek-flash"
    assert info["provider"] == "OpenCode Go"
    assert "ModelDeprecated" in info["raw"]


def test_classify_user_error_recognizes_own_message():
    """ swallow 路径只回了文案时，终态化仍能从我们自己的文案里拿回 code。"""
    message = ufe.model_unavailable_message("deepseek-flash", "OpenCode Go")
    info = ufe.classify_user_error(message)
    assert info is not None
    assert info["code"] == ufe.MODEL_UNAVAILABLE
    assert info["model"] == "deepseek-flash"
    assert info["provider"] == "OpenCode Go"


def test_classify_user_error_ignores_unrelated_failures():
    assert ufe.classify_user_error("构建未完成，请重试。") is None
    assert ufe.classify_user_error("internal failure code 109") is None
    assert ufe.classify_user_error("") is None


def test_model_gone_markers_require_model_context():
    """Codex P2：「Expected artifact does not exist」和裸 404/410 没有模型
    语境时绝不能误判 MODEL_UNAVAILABLE。"""
    assert not ufe.is_model_unavailable(
        "Expected artifact does not exist: artifacts/report.txt"
    )
    assert not ufe.is_model_unavailable(
        "HTTPError 404 - route /files/report.txt not found"
    )
    assert ufe.classify_user_error(
        "Expected artifact does not exist: artifacts/report.txt"
    ) is None
    # 同样的标记带上模型语境就要认。
    assert ufe.is_model_unavailable("the requested model does not exist")
    assert ufe.is_model_unavailable("Error code: 404 - model_not_found")


@pytest.mark.parametrize("friendly", [
    ufe.MSG_DEFAULT + "\n原因：APIStatusError: Error code: 410 - ModelDeprecated",
    ufe.MSG_BUILD_INCOMPLETE,
    ufe.MSG_TIMEOUT,
    ufe.MSG_MODEL_PAUSED,
])
def test_to_user_facing_error_is_idempotent(friendly: str):
    """已经是用户可读文案时不再套「处理未完成，请重试。」。"""
    assert ufe.to_user_facing_error(friendly) == friendly


def test_user_facing_kind_marks_cancelled():
    assert ufe.user_facing_kind(ufe.MSG_CANCELLED) == "cancelled"
    assert ufe.user_facing_kind("模型 x 已被服务商停用，请换模型。") == "failed"
    assert ufe.user_facing_kind("这是一个正常回答。") is None
