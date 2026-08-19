"""PhaseG-B1 / DR1 baseline freeze. Does not change protocol semantics."""

from __future__ import annotations

from pathlib import Path

from config.model_limits import UNKNOWN_MODEL_FALLBACK
from protocol.schema import export_schema
from protocol.version import PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parents[2]
REUSE_DOC = ROOT / "docs" / "decisions" / "desktop-upstream-reuse.md"
APPSERVER = ROOT / "appserver"
SCHEMA = ROOT / "protocol" / "schema.json"
MAIN = APPSERVER / "__main__.py"
JSONRPC = APPSERVER / "jsonrpc.py"
LIMITS = ROOT / "config" / "model_limits.py"
CODEX_LOCKED = "f5a3dc55404ddc066a4e4a65602fee166ecc46b3"


def test_required_baseline_paths_exist() -> None:
    assert APPSERVER.is_dir(), "appserver/ missing"
    assert SCHEMA.is_file(), "protocol/schema.json missing"
    assert REUSE_DOC.is_file(), "docs/decisions/desktop-upstream-reuse.md missing"
    assert not (APPSERVER / "handlers").exists(), "M2: do not create appserver/handlers/"


def test_protocol_version_is_single_source() -> None:
    schema = export_schema()
    assert PROTOCOL_VERSION == "1.1.0"
    assert schema["protocol_version"] == PROTOCOL_VERSION
    committed = SCHEMA.read_text(encoding="utf-8")
    assert f'"protocol_version": "{PROTOCOL_VERSION}"' in committed


def test_initialize_is_in_schema_but_b1_does_not_widen_it() -> None:
    defs = export_schema()["$defs"]
    init = defs["InitializeRequest"]
    assert init["properties"]["method"]["const"] == "initialize"
    required = set(init.get("required") or [])
    assert {"client_name", "client_version", "protocol_version"} <= required


def test_appserver_logs_to_stderr_and_protocol_to_stdout() -> None:
    main = MAIN.read_text(encoding="utf-8")
    assert "stream=sys.stderr" in main
    assert "from .server import AppServer" in main
    jsonrpc = JSONRPC.read_text(encoding="utf-8")
    assert "sys.stdout.write" in jsonrpc
    assert "separators=(\",\", \":\")" in jsonrpc or 'separators=(",", ":")' in jsonrpc


def test_phase3_fallback_is_not_hardcoded_8192() -> None:
    assert UNKNOWN_MODEL_FALLBACK == 32_768
    assert UNKNOWN_MODEL_FALLBACK != 8192
    assert "UNKNOWN_MODEL_FALLBACK = 32_768" in LIMITS.read_text(encoding="utf-8")


def _first_yaml_block(text: str) -> str:
    marker = "```yaml"
    start = text.find(marker)
    assert start >= 0, "C.5 yaml block missing"
    start = text.find("\n", start) + 1
    end = text.find("```", start)
    assert end > start, "C.5 yaml block unclosed"
    return text[start:end]


def test_reuse_doc_has_dr1_required_fields() -> None:
    text = REUSE_DOC.read_text(encoding="utf-8")
    block = _first_yaml_block(text)
    fields = (
        "decision_id:",
        "status:",
        "upstream:",
        "project:",
        "repository:",
        "reference_url:",
        "commit:",
        "license:",
        "capability:",
        "reuse_mode:",
        "reused:",
        "adapter_files:",
        "adaptation_reason:",
        "preserved_semantics:",
        "rxycode_extensions:",
        "verification:",
        "rollback:",
        "owner:",
        "reviewers:",
    )
    missing = [name for name in fields if name not in block]
    assert not missing, f"C.5 fields missing from yaml: {missing}"
    assert 'decision_id: D-UPSTREAM-001' in block
    assert f'commit: "{CODEX_LOCKED}"' in block
    assert "license: Apache-2.0" in block
    assert "reuse_mode: protocol-alignment" in block
    assert "codex-rs/app-server" in block
    assert f"https://raw.githubusercontent.com/openai/codex/{CODEX_LOCKED}/LICENSE" in text
    assert "不适用后端实现" in text
    assert "DR1 完成判据 4 状态：未完成" in text
    for card in ("B15", "B16", "B17", "B18"):
        assert f"| P3 {card}" in text or f"| {card} " in text or card in text
    assert "tools/registry.py" in text
    assert not (APPSERVER / "handlers").exists()


def test_existing_object_contracts_are_not_mocked_away() -> None:
    existing = (
        ROOT / "tests" / "test_appserver" / "test_session_model.py",
        ROOT / "tests" / "test_appserver" / "test_desktop_task_store.py",
        ROOT / "tests" / "test_appserver" / "test_approval.py",
        ROOT / "tests" / "test_appserver" / "test_protocol_tui_recovery.py",
        ROOT / "tests" / "test_protocol_schema.py",
        ROOT / "protocol" / "notifications.py",
        ROOT / "protocol" / "server_requests.py",
    )
    missing = [str(path) for path in existing if not path.is_file()]
    assert not missing, missing
    threads = ROOT / "tests" / "test_threads"
    if threads.exists():
        assert (threads / "test_b5_threads.py").is_file(), "B5 dir must contain real tests"
        assert (threads / "fixtures" / "h5-success.json").is_file(), "B5 must ship H5 fixtures"
    recovery = ROOT / "tests" / "test_recovery"
    if recovery.exists():
        assert any(recovery.glob("test_*.py")), "B12 dir must contain real tests"
