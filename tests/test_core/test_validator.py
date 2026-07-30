"""
Tests for validation/validator.py - Result validation.

Covers: ValidationResult model, Validator.validate with mock LLM, JSON parsing.
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock


class TestValidationResult:
    def test_default_values(self):
        from RxyCode.RxyCode1_1_0.validation.validator import ValidationResult
        vr = ValidationResult()
        assert vr.passed is False
        assert vr.completeness_score == 0
        assert vr.relevance_score == 0
        assert vr.format_score == 0
        assert vr.issues == []
        assert vr.suggestion == ""

    def test_custom_values(self):
        from RxyCode.RxyCode1_1_0.validation.validator import ValidationResult
        vr = ValidationResult(
            passed=True,
            completeness_score=0.9,
            relevance_score=0.8,
            format_score=0.85,
            issues=["minor issue"],
            suggestion="fix the issue",
        )
        assert vr.passed is True
        assert vr.completeness_score == 0.9
        assert vr.relevance_score == 0.8
        assert vr.format_score == 0.85
        assert vr.issues == ["minor issue"]
        assert vr.suggestion == "fix the issue"

    def test_score_bounds(self):
        from RxyCode.RxyCode1_1_0.validation.validator import ValidationResult
        vr = ValidationResult(completeness_score=1.0)
        assert vr.completeness_score == 1.0
        vr2 = ValidationResult(completeness_score=0.0)
        assert vr2.completeness_score == 0.0

    def test_score_out_of_bounds_raises(self):
        from RxyCode.RxyCode1_1_0.validation.validator import ValidationResult
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ValidationResult(completeness_score=1.5)
        with pytest.raises(ValidationError):
            ValidationResult(completeness_score=-0.1)


class TestValidator:
    def _make(self, pass_threshold=0.7):
        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        mock_llm = MagicMock()
        return Validator(mock_llm, pass_threshold=pass_threshold)

    def test_init(self):
        v = self._make()
        assert v._llm is not None
        assert v._pass_threshold == 0.7

    def test_custom_threshold(self):
        v = self._make(pass_threshold=0.8)
        assert v._pass_threshold == 0.8

    def test_deterministic_evidence_failure_bypasses_llm(self):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock()
        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        validator = Validator(mock_llm)

        result = asyncio.run(validator.validate(
            "write file",
            "create output",
            "file exists",
            "Done",
            evidence=[{
                "tool": "write",
                "status": "rejected",
                "executed": False,
                "approval": "rejected",
                "artifacts": [],
                "detail": "[rejected by user: write]",
            }],
        ))

        assert result.passed is False
        assert "rejected" in result.issues[0]
        mock_llm.ainvoke.assert_not_called()

    def test_nonzero_command_evidence_fails_validation(self):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock()
        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        validator = Validator(mock_llm)

        result = asyncio.run(validator.validate(
            "run tests",
            "execute suite",
            "exit code zero",
            "Tests completed",
            evidence=[{
                "tool": "bash",
                "status": "failed",
                "executed": True,
                "exit_code": 1,
                "artifacts": [],
                "detail": "failed\n[exit code: 1]",
            }],
        ))

        assert result.passed is False
        mock_llm.ainvoke.assert_not_called()

    def test_side_effect_claim_without_write_evidence_bypasses_llm(self):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock()
        from RxyCode.RxyCode1_1_0.validation.validator import Validator

        result = asyncio.run(Validator(mock_llm).validate(
            "Create output file",
            "Write the requested result to output.txt",
            "output.txt exists",
            "Created output.txt",
            evidence=[],
            tools_hint=["write"],
        ))

        assert result.passed is False
        assert any("prose alone" in issue for issue in result.issues)
        mock_llm.ainvoke.assert_not_called()

    @pytest.mark.parametrize(
        ("title", "claimed_result"),
        [
            ("Implement authentication", "Implemented authentication"),
            ("Fix the login bug", "Fixed the login bug"),
            ("Add a submit button", "Added a submit button"),
            ("Build a web app", "Built a web app"),
            ("Refactor the API", "Refactored the API"),
            ("Test the login flow", "Tested the login flow"),
            ("实现登录功能", "已实现登录功能"),
            ("修复登录问题", "已修复登录问题"),
            ("新增提交按钮", "已新增提交按钮"),
            ("构建网页应用", "已构建网页应用"),
        ],
    )
    def test_common_mutating_tasks_require_verified_evidence(
        self,
        title,
        claimed_result,
    ):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock()
        from RxyCode.RxyCode1_1_0.validation.validator import Validator

        result = asyncio.run(Validator(mock_llm).validate(
            title,
            "",
            "",
            claimed_result,
            evidence=[],
        ))

        assert result.passed is False
        assert any("prose alone" in issue for issue in result.issues)
        mock_llm.ainvoke.assert_not_called()

    def test_explicit_write_effect_rejects_vague_zero_evidence_result(self):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock()
        from RxyCode.RxyCode1_1_0.validation.validator import Validator

        result = asyncio.run(Validator(mock_llm).validate(
            "Do the requested work",
            "",
            "",
            "Done",
            evidence=[],
            effect="write",
        ))

        assert result.passed is False
        mock_llm.ainvoke.assert_not_called()

    def test_explanatory_past_tense_result_does_not_require_write_evidence(self):
        mock_llm = MagicMock()
        response = MagicMock()
        response.content = (
            '{"passed":true,"completeness_score":1,"relevance_score":1,'
            '"format_score":1}'
        )
        mock_llm.ainvoke = AsyncMock(return_value=response)
        from RxyCode.RxyCode1_1_0.validation.validator import Validator

        result = asyncio.run(Validator(mock_llm).validate(
            "Explain the package history",
            "Describe prior releases",
            "Accurate chronology",
            "The package was updated in 2025.",
            evidence=[],
            effect="read",
        ))

        assert result.passed is True
        mock_llm.ainvoke.assert_awaited_once()

    def test_html_open_requirement_needs_verified_open_action(self):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock()
        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        validator = Validator(mock_llm)

        result = asyncio.run(validator.validate(
            "Create calculator HTML",
            "Write the page and open it in the browser",
            "HTML exists and is opened",
            "Created and opened",
            evidence=[{
                "tool": "write",
                "status": "succeeded",
                "executed": True,
                "artifacts": [{
                    "path": "calculator.html",
                    "exists": True,
                    "size": 100,
                    "sha256": "a" * 64,
                    "media_type": "text/html",
                    "valid": True,
                }],
                "detail": "written",
            }],
        ))

        assert result.passed is False
        assert any("open" in issue.lower() for issue in result.issues)
        mock_llm.ainvoke.assert_not_called()

    def test_validate_passes(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = '{"passed": true, "completeness_score": 0.9, "relevance_score": 0.8, "format_score": 0.85, "issues": [], "suggestion": ""}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        v = Validator(mock_llm)
        result = asyncio.run(v.validate("title", "desc", "req", "result"))
        assert result.passed is True

    def test_validate_fails_low_score(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = '{"passed": true, "completeness_score": 0.5, "relevance_score": 0.6, "format_score": 0.8, "issues": [], "suggestion": ""}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        v = Validator(mock_llm)
        result = asyncio.run(v.validate("title", "desc", "req", "result"))
        # passed should be False because not all scores >= threshold
        assert result.passed is False

    def test_validate_with_invalid_json(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = 'not json at all'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        v = Validator(mock_llm)
        result = asyncio.run(v.validate("title", "desc", "req", "result"))
        assert result.passed is False
        assert any("parse" in issue.lower() or "no json" in issue.lower() for issue in result.issues)

    def test_validate_with_partial_json(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = 'some text {"passed": true, "completeness_score": 0.9, "relevance_score": 0.9, "format_score": 0.9} more text'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        v = Validator(mock_llm)
        result = asyncio.run(v.validate("title", "desc", "req", "result"))
        assert result.passed is True

    def test_validate_nested_json_and_repairs_schema_error_once(self):
        mock_llm = MagicMock()
        bad = MagicMock()
        bad.content = '{"passed": true, "completeness_score": "bad"}'
        fixed = MagicMock()
        fixed.content = (
            '```json\n{"passed": true, "completeness_score": 0.9, '
            '"relevance_score": 0.9, "format_score": 0.9, '
            '"issues": [], "suggestion": "Use {verified} output"}\n```'
        )
        mock_llm.ainvoke = AsyncMock(side_effect=[bad, fixed])

        from RxyCode.RxyCode1_1_0.validation.validator import Validator

        result = asyncio.run(Validator(mock_llm).validate("title", "desc", "req", "result"))

        assert result.passed is True
        assert result.suggestion == "Use {verified} output"
        assert mock_llm.ainvoke.await_count == 2

    def test_validate_no_json_in_response(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = 'I cannot evaluate this'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        v = Validator(mock_llm)
        result = asyncio.run(v.validate("title", "desc", "req", "result"))
        assert result.passed is False
        assert any("no json" in issue.lower() for issue in result.issues)

    def test_validate_empty_result(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = '{"passed": false, "completeness_score": 0, "relevance_score": 0, "format_score": 0, "issues": ["empty result"], "suggestion": "provide a result"}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        v = Validator(mock_llm)
        result = asyncio.run(v.validate("title", "desc", "req", ""))
        assert result.passed is False

    def test_validate_threshold_check(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        # All scores at exactly threshold
        mock_resp.content = '{"passed": true, "completeness_score": 0.7, "relevance_score": 0.7, "format_score": 0.7}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        v = Validator(mock_llm, pass_threshold=0.7)
        result = asyncio.run(v.validate("title", "desc", "req", "result"))
        assert result.passed is True

    def test_validate_calls_llm(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = '{"passed": true, "completeness_score": 0.9, "relevance_score": 0.9, "format_score": 0.9}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        v = Validator(mock_llm)
        asyncio.run(v.validate("title", "desc", "req", "result"))
        mock_llm.ainvoke.assert_called_once()

    def test_validate_includes_task_info(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = '{"passed": true, "completeness_score": 0.9, "relevance_score": 0.9, "format_score": 0.9}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        v = Validator(mock_llm)
        asyncio.run(v.validate("my task", "my description", "my criteria", "my result"))
        call_args = mock_llm.ainvoke.call_args
        messages = call_args[0][0]
        user_msg = messages[1].content
        assert "my task" in user_msg
        assert "my description" in user_msg
        assert "my criteria" in user_msg
        assert "my result" in user_msg

    def test_validate_handles_missing_fields(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        # Missing some fields - pydantic should use defaults
        mock_resp.content = '{"passed": true, "completeness_score": 0.9}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        from RxyCode.RxyCode1_1_0.validation.validator import Validator
        v = Validator(mock_llm)
        result = asyncio.run(v.validate("title", "desc", "req", "result"))
        assert result.completeness_score == 0.9
        assert result.relevance_score == 0  # Default
        assert result.format_score == 0  # Default
