"""WEB-W3-C03. The shipped reducer orders events once and keeps the final answer clean."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REDUCER = REPO / "apps" / "web" / "src" / "features" / "runs" / "eventReducer.ts"
_BUN = Path(r"D:\nodejs\node_modules\bun\bin\bun.exe")
_SCRATCH = Path(r"C:\Users\Administrator\AppData\Local\Temp\grok-goal-633d8463e340\implementer")


def _bun() -> str:
    found = shutil.which("bun")
    if found:
        return found
    if _BUN.exists():
        return str(_BUN)
    raise FileNotFoundError("bun")


def reduce_events(events: list[dict]) -> dict:
    """Run the shipped reducer. The assertions stay in this test."""
    assert REDUCER.is_file(), "eventReducer.ts is missing"
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    driver = _SCRATCH / "c03-reduce.ts"
    driver.write_text(
        "import { reduceEvents } from "
        + json.dumps(REDUCER.as_posix())
        + "\nconst events = "
        + json.dumps(events)
        + "\nconsole.log(JSON.stringify(reduceEvents(events)))\n",
        encoding="utf-8",
    )
    proc = subprocess.run([_bun(), str(driver)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def test_w3_c03_contract() -> None:
    """Events 1,2,2,4,3 become 1,2,3,4, and seq 2 is kept once."""
    prefix = reduce_events(
        [
            {"seq": 1, "type": "assistant.delta", "payload": {"text": "one"}},
            {"seq": 2, "type": "assistant.delta", "payload": {"text": "two"}},
            {"seq": 2, "type": "assistant.delta", "payload": {"text": "dup"}},
            {"seq": 4, "type": "assistant.final", "payload": {"text": "four"}},
        ]
    )
    assert prefix["order"] == [1, 2]
    assert prefix["order"].count(2) == 1
    assert 4 not in prefix["order"]
    done = reduce_events(
        [
            {"seq": 1, "type": "assistant.delta", "payload": {"text": "one"}},
            {"seq": 2, "type": "assistant.delta", "payload": {"text": "two"}},
            {"seq": 2, "type": "assistant.delta", "payload": {"text": "dup"}},
            {"seq": 4, "type": "assistant.final", "payload": {"text": "four"}},
            {"seq": 3, "type": "assistant.delta", "payload": {"text": "three"}},
        ]
    )
    assert done["order"] == [1, 2, 3, 4]
    assert done["order"].count(2) == 1


def test_w3_c03_negative() -> None:
    """Out-of-order intermediate text stays out of the final answer."""
    done = reduce_events(
        [
            {
                "seq": 2,
                "type": "assistant.delta",
                "payload": {"text": "child thought", "intermediate": True},
            },
            {
                "seq": 1,
                "type": "assistant.delta",
                "payload": {"text": "earlier thought", "intermediate": True},
            },
            {
                "seq": 3,
                "type": "assistant.final",
                "payload": {"text": "final user answer"},
            },
        ]
    )
    assert done["answer"] == "final user answer"
    assert done["answer"].endswith("final user answer")
    assert "thought" not in done["answer"]
    assert done["intermediate"] == ["earlier thought", "child thought"]
