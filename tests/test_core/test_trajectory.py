"""Contract tests for the durable trajectory event log."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from datetime import datetime

import pytest

from RxyCode.RxyCode1_1_0.core.trajectory import (
    MAX_COLLECTION_ITEMS,
    MAX_EVENT_BYTES,
    MAX_STRING_CHARS,
    REDACTED,
    TrajectoryLogger,
    read_trajectory,
    replay_trajectory,
)


@pytest.fixture
def trajectory_dir(tmp_path):
    return tmp_path / "logs" / "trajectories"


def test_record_uses_default_data_dir_and_writes_utc_jsonl(tmp_path, monkeypatch):
    import RxyCode.RxyCode1_1_0.core.trajectory as trajectory

    monkeypatch.setattr(trajectory, "get_data_dir", lambda: tmp_path)
    logger = TrajectoryLogger("run-123")

    recorded = logger.record("plan.created", {"tasks": 3})

    assert logger.path == tmp_path / "logs" / "trajectories" / "run-123.jsonl"
    assert recorded is not None
    line = logger.path.read_text(encoding="utf-8").strip()
    event = json.loads(line)
    assert event == recorded
    assert event["run_id"] == "run-123"
    assert event["event_type"] == "plan.created"
    assert event["payload"] == {"tasks": 3}
    parsed = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
    assert parsed.utcoffset().total_seconds() == 0


def test_retention_keeps_newest_runs_and_never_deletes_current(trajectory_dir):
    trajectory_dir.mkdir(parents=True, exist_ok=True)
    for index in range(4):
        (trajectory_dir / f"old-{index}.jsonl").write_text(
            "{}\n",
            encoding="utf-8",
        )

    logger = TrajectoryLogger(
        "current",
        directory=trajectory_dir,
        retention_runs=2,
    )
    logger.record("run.started", {})

    names = {path.name for path in trajectory_dir.glob("*.jsonl")}
    assert "current.jsonl" in names
    assert len(names) == 2


def test_recursive_redaction_covers_keys_headers_bearer_and_api_keys(
    trajectory_dir,
):
    logger = TrajectoryLogger("redaction", directory=trajectory_dir)
    secrets = {
        "by_key": "key-secret-value",
        "bearer": "bearer-secret-value",
        "authorization": "authorization-secret-value",
        "assignment": "assignment-secret-value",
        "openai": "OpenAISecret123456",
        "github": "GithubSecret123456789",
    }

    logger.record(
        "tool.after",
        {
            "api_key": secrets["by_key"],
            "headers": {
                "Authorization": f"Bearer {secrets['authorization']}",
            },
            "message": (
                f"upstream said Bearer {secrets['bearer']}; "
                f"api_key={secrets['assignment']}; "
                f"sk-{secrets['openai']}; ghp_{secrets['github']}"
            ),
            "nested": [{"refresh_token": "refresh-secret-value"}],
            "token_usage": {"prompt_tokens": 12, "completion_tokens": 4},
        },
    )

    raw = logger.path.read_text(encoding="utf-8")
    event = json.loads(raw)
    for secret in (*secrets.values(), "refresh-secret-value"):
        assert secret not in raw
    assert event["payload"]["api_key"] == REDACTED
    assert event["payload"]["headers"]["Authorization"] == REDACTED
    assert event["payload"]["nested"][0]["refresh_token"] == REDACTED
    assert event["payload"]["token_usage"]["prompt_tokens"] == 12
    assert event["payload"]["token_usage"]["completion_tokens"] == 4


def test_payload_normalization_has_hard_limits_and_never_uses_object_repr(
    trajectory_dir,
):
    class UnsafeObject:
        def __repr__(self):
            return "sk-fake-repr-secret-must-never-be-read"

    cyclic = []
    cyclic.append(cyclic)
    logger = TrajectoryLogger("bounded", directory=trajectory_dir)

    logger.record(
        "context.assembled",
        {
            "long": "x" * (MAX_STRING_CHARS + 500),
            "many": list(range(MAX_COLLECTION_ITEMS + 20)),
            "deep": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": 1}}}}}}}},
            "cyclic": cyclic,
            "bytes": b"binary-secret-is-not-decoded",
            "unknown": UnsafeObject(),
            "set": {3, 1, 2},
        },
    )

    raw = logger.path.read_text(encoding="utf-8")
    event = json.loads(raw)
    payload = event["payload"]
    assert len(payload["long"]) <= MAX_STRING_CHARS + 40
    assert len(payload["many"]) == MAX_COLLECTION_ITEMS + 1
    assert payload["many"][-1]["_truncated_items"] == 20
    assert "MAX_DEPTH" in json.dumps(payload["deep"])
    assert payload["cyclic"] == ["[CYCLE]"]
    assert payload["bytes"] == "<bytes:28>"
    assert payload["unknown"] == "<unserializable:UnsafeObject>"
    assert payload["set"] == [1, 2, 3]
    assert "repr-secret" not in raw
    assert "binary-secret" not in raw


def test_single_event_has_a_strict_serialized_byte_limit(trajectory_dir):
    logger = TrajectoryLogger("large-event", directory=trajectory_dir)

    event = logger.record(
        "executor.result",
        {f"field-{index}": "value-" * 1000 for index in range(100)},
    )

    line = logger.path.read_bytes().splitlines()[0]
    assert len(line) + 1 <= MAX_EVENT_BYTES
    persisted = json.loads(line)
    assert persisted == event
    assert persisted["payload"]["_event_truncated"] is True
    assert persisted["payload"]["original_size_bytes"] > MAX_EVENT_BYTES


def test_concurrent_records_are_complete_json_lines(trajectory_dir):
    logger = TrajectoryLogger("threads", directory=trajectory_dir)

    def worker(worker_id):
        for index in range(40):
            logger.record("tool.call", {"worker": worker_id, "index": index})

    threads = [threading.Thread(target=worker, args=(worker_id,)) for worker_id in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = logger.path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    assert len(events) == 320
    assert len({(event["payload"]["worker"], event["payload"]["index"]) for event in events}) == 320
    assert all(event["run_id"] == "threads" for event in events)


def test_read_skips_malformed_oversized_and_wrong_run_records(trajectory_dir):
    logger = TrajectoryLogger("readable", directory=trajectory_dir)
    logger.record("one", {"index": 1})
    with logger.path.open("ab") as stream:
        stream.write(b"not-json\n")
        stream.write(json.dumps(["not", "an", "event"]).encode() + b"\n")
        stream.write(
            json.dumps(
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "run_id": "another-run",
                    "event_type": "foreign",
                    "payload": {},
                }
            ).encode()
            + b"\n"
        )
        stream.write(b"x" * (MAX_EVENT_BYTES + 20) + b"\n")
    logger.record("two", {"index": 2})

    assert [event["event_type"] for event in logger.read_events()] == ["one", "two"]
    assert [event["payload"]["index"] for event in read_trajectory(
        "readable", directory=trajectory_dir
    )] == [1, 2]


def test_replay_preserves_order_supports_filter_and_invokes_handler(trajectory_dir):
    logger = TrajectoryLogger("replayable", directory=trajectory_dir)
    logger.record("node.start", {"index": 1})
    logger.record("tool.call", {"index": 2})
    logger.record("node.start", {"index": 3})
    observed = []

    replayed = replay_trajectory(
        "replayable",
        observed.append,
        event_type="node.start",
        directory=trajectory_dir,
    )

    assert [event["payload"]["index"] for event in replayed] == [1, 3]
    assert observed == replayed


@pytest.mark.parametrize(
    "run_id",
    ["", ".", "..", "../escape", "folder/run", r"folder\run", "sk-SecretKey123456"],
)
def test_run_id_cannot_escape_the_directory_or_embed_a_secret(trajectory_dir, run_id):
    with pytest.raises(ValueError):
        TrajectoryLogger(run_id, directory=trajectory_dir)


def test_write_failure_is_best_effort_and_does_not_break_execution(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    logger = TrajectoryLogger("resilient", directory=blocked / "trajectories")

    assert logger.record("run.error", {"message": "still continue"}) is None


def test_hostile_mapping_cannot_break_record_or_leak_exception_text(trajectory_dir):
    class BrokenMapping(Mapping):
        def __getitem__(self, key):
            raise RuntimeError("sk-fake-exception-secret-value")

        def __iter__(self):
            raise RuntimeError("sk-fake-exception-secret-value")

        def __len__(self):
            raise RuntimeError("sk-fake-exception-secret-value")

    logger = TrajectoryLogger("hostile-payload", directory=trajectory_dir)

    recorded = logger.record("payload.received", BrokenMapping())

    assert recorded is not None
    assert recorded["payload"] == "<unserializable:BrokenMapping>"
    assert "exception-secret" not in logger.path.read_text(encoding="utf-8")
