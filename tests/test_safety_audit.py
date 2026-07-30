"""Tests for core/safety/audit.py — audit log writing and sensitive-key
redaction."""
import json
import asyncio
import pytest

from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
from RxyCode.RxyCode1_1_0.core.safety.audit import (
    AuditLogger,
    sanitize_args,
)


@pytest.fixture
def audit_file(tmp_path):
    return tmp_path / "logs" / "audit.jsonl"


class TestSanitizeArgs:
    def test_redacts_sensitive_keys(self):
        args = {
            "command": "echo hi",
            "api_key": "sk-secret-123",
            "password": "hunter2",
            "access_token": "tok_abc",
            "Authorization": "Bearer xyz",
        }
        out = sanitize_args(args)
        assert out["command"] == "echo hi"
        assert out["api_key"] == "***"
        assert out["password"] == "***"
        assert out["access_token"] == "***"
        assert out["Authorization"] == "***"

    def test_truncates_long_values(self):
        args = {"content": "y" * 1000}
        out = sanitize_args(args)
        assert len(str(out["content"])) <= 220

    def test_nested_dict_sanitized(self):
        args = {"opts": {"secret_key": "abc", "path": "/tmp/x"}}
        out = sanitize_args(args)
        assert out["opts"]["secret_key"] == "***"
        assert out["opts"]["path"] == "/tmp/x"

    def test_non_dict_input(self):
        assert sanitize_args("plain string") == "plain string"

    def test_redacts_inline_credentials_inside_ordinary_fields(self):
        secrets = {
            "bearer": "bearer-command-secret",
            "api_key": "inline-api-key-secret",
            "openai": "sk-fake-abcdefghijklmnop123456",
        }
        args = {
            "command": (
                "curl -H 'Authorization: Bearer "
                f"{secrets['bearer']}' https://example.test "
                f"--data api_key={secrets['api_key']}"
            ),
            "query": [f"Bearer {secrets['bearer']}", secrets["openai"]],
        }

        serialized = json.dumps(sanitize_args(args))

        assert all(secret not in serialized for secret in secrets.values())
        assert "[REDACTED]" in serialized


class TestAuditLogger:
    def test_writes_jsonl_record(self, audit_file):
        logger = AuditLogger(path=audit_file)
        logger.log(
            tool="bash",
            risk=RiskLevel.WRITE,
            args={"command": "echo hi"},
            approval="approved",
            result="hi",
        )
        lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["tool"] == "bash"
        assert rec["risk"] == "WRITE"
        assert rec["approval"] == "approved"
        assert "ts" in rec
        from RxyCode.RxyCode1_1_0.log.logger import RUN_ID
        assert rec["run_id"] == RUN_ID
        assert rec["args"]["command"] == "echo hi"

    def test_appends_multiple_records(self, audit_file):
        logger = AuditLogger(path=audit_file)
        for i in range(3):
            logger.log(tool="write", risk=RiskLevel.WRITE, args={"i": i},
                       approval="auto", result="ok")
        lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3

    def test_rotates_audit_log_before_size_budget_is_exceeded(self, audit_file):
        logger = AuditLogger(path=audit_file, max_bytes=300, backup_count=2)
        for i in range(8):
            logger.log(
                tool="write",
                risk=RiskLevel.WRITE,
                args={"i": i},
                approval="auto",
                result="x" * 120,
            )

        assert audit_file.exists()
        assert audit_file.with_name("audit.jsonl.1").exists()
        assert not audit_file.with_name("audit.jsonl.3").exists()

    def test_result_credentials_are_redacted(self, audit_file):
        logger = AuditLogger(path=audit_file)
        logger.log(
            tool="read",
            risk=RiskLevel.READ,
            args={},
            approval="auto",
            result="Authorization: Bearer secret-token-value",
        )

        assert "secret-token-value" not in audit_file.read_text(encoding="utf-8")

    def test_sensitive_keys_never_logged(self, audit_file):
        logger = AuditLogger(path=audit_file)
        logger.log(
            tool="bash",
            risk=RiskLevel.DANGER,
            args={"command": "deploy", "api_key": "sk-LEAKME"},
            approval="rejected",
            result="",
        )
        raw = audit_file.read_text(encoding="utf-8")
        assert "sk-LEAKME" not in raw

    def test_inline_command_credentials_never_reach_audit_file(self, audit_file):
        logger = AuditLogger(path=audit_file)
        secrets = (
            "command-bearer-secret",
            "command-api-key-secret",
            "sk-fake-abcdefghijklmnop123456",
        )
        logger.log(
            tool="bash",
            risk=RiskLevel.DANGER,
            args={
                "command": (
                    f"curl -H 'Authorization: Bearer {secrets[0]}' "
                    f"--data api_key={secrets[1]} https://example.test"
                ),
                "query": [f"Bearer {secrets[0]}", secrets[2]],
            },
            approval="approved",
            result="ok",
        )

        raw = audit_file.read_text(encoding="utf-8")
        assert all(secret not in raw for secret in secrets)
        assert "[REDACTED]" in raw

    def test_result_summary_truncated(self, audit_file):
        logger = AuditLogger(path=audit_file)
        logger.log(tool="read", risk=RiskLevel.READ, args={},
                   approval="auto", result="z" * 1000)
        rec = json.loads(audit_file.read_text(encoding="utf-8").strip())
        assert len(rec["result"]) <= 220

    def test_concurrent_writes_safe(self, audit_file):
        """Thread lock: concurrent log() calls must not interleave lines."""
        import threading
        logger = AuditLogger(path=audit_file)
        def worker(n):
            for i in range(20):
                logger.log(tool="t", risk=RiskLevel.READ, args={"n": n, "i": i},
                           approval="auto", result="ok")
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 80
        for line in lines:
            json.loads(line)  # every line is valid JSON

    def test_write_failure_never_raises(self, tmp_path):
        bad = tmp_path / "nonexistent-deep" / "x" / "audit.jsonl"
        logger = AuditLogger(path=bad)
        # Force an unwritable path scenario by making parent a file
        (tmp_path / "nonexistent-deep").write_text("block")
        logger.log(tool="t", risk=RiskLevel.READ, args={}, approval="auto", result="")

    @pytest.mark.asyncio
    async def test_concurrent_tool_calls_keep_request_run_ids(self, audit_file):
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
        from RxyCode.RxyCode1_1_0.log.logger import (
            RUN_ID,
            get_current_run_id,
            run_id_context,
        )

        release = asyncio.Event()

        class AsyncReadTool:
            name = "read"

            async def coroutine(self, **kwargs):
                return kwargs["marker"]

            async def ainvoke(self, payload):
                await release.wait()
                await asyncio.sleep(0)
                return payload["marker"]

        logger = AuditLogger(path=audit_file)
        orchestrator = ToolOrchestrator()
        orchestrator.register("read", AsyncReadTool())
        orchestrator.set_audit_logger(logger)

        async def execute(run_id, marker):
            with run_id_context(run_id):
                return await orchestrator.execute_tool(
                    "read",
                    {"marker": marker},
                    config={"safety": {"enabled": True}},
                )

        tasks = [
            asyncio.create_task(execute("request-alpha", "alpha")),
            asyncio.create_task(execute("request-beta", "beta")),
        ]
        await asyncio.sleep(0)
        release.set()
        assert await asyncio.gather(*tasks) == ["alpha", "beta"]

        records = [
            json.loads(line)
            for line in audit_file.read_text(encoding="utf-8").splitlines()
        ]
        assert {record["args"]["marker"]: record["run_id"] for record in records} == {
            "alpha": "request-alpha",
            "beta": "request-beta",
        }
        assert get_current_run_id() == RUN_ID
