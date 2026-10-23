"""A byte-window cut must not move a credential value outside its redaction key."""
from RxyCode.RxyCode1_1_0.core.session_runtime import bind_session, reset_session_binding
from RxyCode.RxyCode1_1_0.utils.output_capture import BoundedOutputCapture, CAPTURE_PREVIEW_BYTES_PER_STREAM
from RxyCode.RxyCode1_1_0.tools.bash import _format_result


def test_secret_crossing_tail_window_is_not_exposed(isolated_runtime):
    half = CAPTURE_PREVIEW_BYTES_PER_STREAM // 2
    secret = b"SENSITIVE_SECRET_VALUE_CANARY"
    raw = b"prefix\n" + b"P" * 50000 + b'\napi_key="' + secret + b'"' + b"T" * (half - len(secret) + 8)
    capture = BoundedOutputCapture()
    token = bind_session("tail-redaction-regression")
    try:
        for offset in range(0, len(raw), 8192):
            capture.feed("stdout", raw[offset:offset + 8192])
        capture.end_stream("stdout")
        capture.end_stream("stderr")
        result = {**capture.finish(), "success": True, "exit_code": 0, "error_type": None}
        preview = _format_result(result)
        assert "SECRET_VALUE_CANARY" not in preview
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
        generic_preview = ToolOrchestrator._clean_tool_output(
            result["stdout"], {"context": {"max_tool_output_chars": 64000}},
        )
        assert "SECRET_VALUE_CANARY" not in generic_preview
        # Complete original bytes remain available only in the local artifact.
        from pathlib import Path
        assert Path(result["stdout_artifact"]).read_bytes() == raw
    finally:
        reset_session_binding(token)
