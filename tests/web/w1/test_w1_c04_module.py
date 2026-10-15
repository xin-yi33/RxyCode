"""WEB-W1-C04. The TypeScript client is compiled from the Python schema."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO / "protocol" / "schema.json"
CLIENT = REPO / "frontend" / "protocol-client"


def _bun() -> str:
    exe = shutil.which("bun")
    if exe:
        return exe
    fallback = Path(r"D:\nodejs\node_modules\bun\bin\bun.exe")
    if fallback.is_file():
        return str(fallback)
    raise FileNotFoundError("bun")


def test_w1_c04_integration(tmp_path: Path):
    """Export the schema, generate TS, and typecheck the real client."""
    from protocol.schema import export_schema, schema_digest

    schema = export_schema()
    digest = schema_digest(schema)
    assert schema["schema_digest"] == digest
    assert schema["protocol_version"] == "1.1.0"
    rendered = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    assert SCHEMA_PATH.read_text(encoding="utf-8") == rendered
    generated = tmp_path / "types.ts"
    bun = _bun()
    gen = subprocess.run(
        [
            bun,
            "x",
            "json2ts",
            "-i",
            str(SCHEMA_PATH),
            "-o",
            str(generated),
            "--unreachableDefinitions",
        ],
        cwd=CLIENT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert gen.returncode == 0, gen.stderr
    text = generated.read_text(encoding="utf-8")
    for name in ("RunRecord", "WebEvent", "DeviceRecord", "WebDiagnostic"):
        assert f"export interface {name}" in text
    committed = (CLIENT / "src" / "generated" / "types.ts").read_text(encoding="utf-8")
    for name in ("RunRecord", "WebEvent", "DeviceRecord", "WebDiagnostic"):
        assert f"export interface {name}" in committed
    digest_ts = (CLIENT / "src" / "generated" / "web_digest.ts").read_text(encoding="utf-8")
    assert digest in digest_ts
    check = subprocess.run(
        [bun, "x", "tsc", "--noEmit"],
        cwd=CLIENT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr
