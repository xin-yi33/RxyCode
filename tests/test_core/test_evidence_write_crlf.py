"""Artifact write validation should tolerate CRLF / BOM."""
from RxyCode.RxyCode1_1_0.execution.evidence import build_tool_evidence


def test_write_artifact_valid_with_crlf(tmp_path):
    path = tmp_path / "simple_script.py"
    content = "print('hello')\nprint(2+2)\n"
    path.write_bytes(b"\xef\xbb\xbf" + content.replace("\n", "\r\n").encode("utf-8"))
    ev = build_tool_evidence(
        "write",
        {"filePath": str(path), "content": content},
        "wrote file",
        executed=True,
    )
    assert ev.status == "succeeded"
    assert ev.artifacts
    assert ev.artifacts[0].valid is True
