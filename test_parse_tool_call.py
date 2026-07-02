"""Unit tests for _parse_tool_call (the C-2 / I-3 fix)."""
import sys
sys.path.insert(0, "D:/agent-demo")

# Force fresh import
for m in list(sys.modules.keys()):
    if m.startswith("RxyCode"):
        del sys.modules[m]

from RxyCode.chains.chains import _parse_tool_call

FENCE = chr(96) * 3  # ```

cases = [
    # (name, input, expected_name or None, expected_arg_check)
    (
        "normal fenced JSON block",
        FENCE + "json\n" + '{"name": "read", "arguments": {"filePath": "x.py"}}' + "\n" + FENCE,
        "read",
        lambda r: r["arguments"]["filePath"] == "x.py",
    ),
    (
        "legacy double-brace fenced (the C-2 bug)",
        FENCE + "json\n" + '{{"name": "read", "arguments": {{"filePath": "x.py"}}}}' + "\n" + FENCE,
        "read",
        lambda r: r["arguments"]["filePath"] == "x.py",
    ),
    (
        "bare nested JSON (the I-3 fix - old regex would truncate)",
        'text before {"name": "patch", "arguments": {"diff": {"hunks": [{"a": 1}]}}} after',
        "patch",
        lambda r: r["arguments"]["diff"]["hunks"][0]["a"] == 1,
    ),
    (
        "plain text, no tool call",
        "just chatting, no tool here",
        None,
        lambda r: r is None,
    ),
    (
        "double-brace bare (mixed legacy leak)",
        'see {{ "name": "bash", "arguments": {{"cmd": "echo hi"}} }} ok',
        "bash",
        lambda r: r["arguments"]["cmd"] == "echo hi",
    ),
    (
        "real-world read failure case (from test report)",
        "I'll read the file to get the version information.\n\n" + FENCE + "json\n" + '{{"name": "read", "arguments": {{"filePath": "D:\\\\x\\\\__init__.py", "offset": 0, "limit": 3}}}}' + "\n" + FENCE,
        "read",
        lambda r: r["arguments"]["filePath"] == "D:\\x\\__init__.py" and r["arguments"]["limit"] == 3,
    ),
]

failures = 0
for name, inp, expected_name, check in cases:
    r = _parse_tool_call(inp, ["read", "bash", "patch"])
    if expected_name is None:
        if r is not None:
            print(f"FAIL [{name}]: expected None, got {r}")
            failures += 1
        else:
            print(f"PASS [{name}]")
        continue
    if r is None:
        print(f"FAIL [{name}]: expected {expected_name}, got None")
        failures += 1
        continue
    if r.get("name") != expected_name:
        print(f"FAIL [{name}]: expected name={expected_name}, got {r.get('name')}")
        failures += 1
        continue
    try:
        if not check(r):
            print(f"FAIL [{name}]: arg check failed, got {r}")
            failures += 1
            continue
    except Exception as e:
        print(f"FAIL [{name}]: arg check raised {e}, got {r}")
        failures += 1
        continue
    print(f"PASS [{name}]")

print()
if failures:
    print(f"{failures} TEST(S) FAILED")
    sys.exit(1)
else:
    print(f"ALL {len(cases)} TESTS PASSED")
