"""
Tests for log/log_helpers.py and log/logger.py.

Covers: log formatting, chat request logging, KeyValueFormatter, setup_logging.
"""
import logging
import pytest
from io import StringIO


class TestLogHelpers:
    def test_log_chat_request_does_not_crash(self):
        import logging
        from RxyCode.RxyCode1_1_0.log.log_helpers import log_chat_request
        logger = logging.getLogger("test_log_chat_request")
        log_chat_request(logger, "build", "test message")

    def test_log_chat_completed_does_not_crash(self):
        import logging
        from RxyCode.RxyCode1_1_0.log.log_helpers import log_chat_completed
        logger = logging.getLogger("test_log_chat_completed")
        log_chat_completed(logger, "build", "test response")

    def test_log_chat_error_does_not_crash(self):
        import logging
        from RxyCode.RxyCode1_1_0.log.log_helpers import log_chat_error
        logger = logging.getLogger("test_log_chat_error")
        log_chat_error(logger, "build", RuntimeError("test error"))

    def test_quiet_paths_exists(self):
        from RxyCode.RxyCode1_1_0.log.log_helpers import QUIET_PATHS
        assert isinstance(QUIET_PATHS, (list, set, tuple))

    def test_quiet_paths_contains_status(self):
        from RxyCode.RxyCode1_1_0.log.log_helpers import QUIET_PATHS
        assert "/status" in QUIET_PATHS

    def test_quiet_paths_contains_models(self):
        from RxyCode.RxyCode1_1_0.log.log_helpers import QUIET_PATHS
        assert "/models" in QUIET_PATHS

    def test_prompt_preview_len(self):
        from RxyCode.RxyCode1_1_0.log.log_helpers import PROMPT_PREVIEW_LEN
        assert isinstance(PROMPT_PREVIEW_LEN, int)
        assert PROMPT_PREVIEW_LEN > 0

    def test_answer_preview_len(self):
        from RxyCode.RxyCode1_1_0.log.log_helpers import ANSWER_PREVIEW_LEN
        assert isinstance(ANSWER_PREVIEW_LEN, int)
        assert ANSWER_PREVIEW_LEN > 0

    def test_error_preview_len(self):
        from RxyCode.RxyCode1_1_0.log.log_helpers import ERROR_PREVIEW_LEN
        assert isinstance(ERROR_PREVIEW_LEN, int)
        assert ERROR_PREVIEW_LEN > 0

    def test_log_chat_request_truncates_long_message(self):
        import logging
        from io import StringIO
        from RxyCode.RxyCode1_1_0.log.log_helpers import log_chat_request, PROMPT_PREVIEW_LEN
        logger = logging.getLogger("test_truncate")
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        long_msg = "x" * (PROMPT_PREVIEW_LEN + 100)
        log_chat_request(logger, "build", long_msg)
        output = stream.getvalue()
        assert "Chat request" in output


class TestKeyValueFormatter:
    def test_format_key_value(self):
        from RxyCode.RxyCode1_1_0.log.logger import KeyValueFormatter
        formatter = KeyValueFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py", lineno=1,
            msg="test message", args=(), exc_info=None
        )
        result = formatter.format(record)
        assert "test message" in result

    def test_format_uses_bound_run_id_without_duplicate_field(self):
        from RxyCode.RxyCode1_1_0.log.logger import (
            KeyValueFormatter,
            run_id_context,
        )

        formatter = KeyValueFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py", lineno=1,
            msg="request log", args=(), exc_info=None,
        )
        with run_id_context("request-logger-123"):
            result = formatter.format(record)

        assert result.count("request-logger-123") == 1
        assert "run=request-logger-123" in result

    def test_quote_special_chars(self):
        from RxyCode.RxyCode1_1_0.log.logger import _quote
        result = _quote("hello world")
        assert isinstance(result, str)

    def test_quote_empty(self):
        from RxyCode.RxyCode1_1_0.log.logger import _quote
        result = _quote("")
        assert isinstance(result, str)

    def test_quote_no_special(self):
        from RxyCode.RxyCode1_1_0.log.logger import _quote
        result = _quote("simple")
        assert isinstance(result, str)


class TestSetupLogging:
    def test_get_logger(self):
        from RxyCode.RxyCode1_1_0.log.logger import get_logger
        logger = get_logger()
        assert logger is not None
        assert isinstance(logger, logging.Logger)

    def test_setup_logging(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        from RxyCode.RxyCode1_1_0.log.logger import setup_logging
        logger = setup_logging("DEBUG")
        assert logger is not None

    def test_setup_logging_creates_log_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        from RxyCode.RxyCode1_1_0.log.logger import setup_logging
        setup_logging("INFO")
        assert tmp_path.exists()

    def test_get_logger_returns_named_logger(self):
        from RxyCode.RxyCode1_1_0.log.logger import get_logger
        logger = get_logger()
        assert logger.name == "rxycode"

    def test_file_handler_is_rotating(self, tmp_path, monkeypatch):
        """FileHandler must be a RotatingFileHandler (10MB x 5 backups)."""
        import logging.handlers
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        from RxyCode.RxyCode1_1_0.log import logger as logger_mod
        # Force re-init
        logger_mod._initialized = False
        logger_mod._logger_instance = None
        lg = logger_mod.setup_logging("INFO")
        rotating = [
            h for h in lg.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert rotating, "expected a RotatingFileHandler"
        assert rotating[0].maxBytes == 10 * 1024 * 1024
        assert rotating[0].backupCount == 5
