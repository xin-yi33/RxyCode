import json
from pathlib import Path


def test_recorded_session_round_trips_through_real_storage(isolated_runtime):
    from RxyCode.RxyCode1_1_0.memory.chat_storage import ChatStorage

    fixture = json.loads(
        (
            Path(__file__).parents[1]
            / "fixtures"
            / "sessions"
            / "resume_session.json"
        ).read_text(encoding="utf-8")
    )
    storage = ChatStorage()

    assert storage.save(fixture["name"], fixture["messages"]) is True
    assert storage.load(fixture["name"]) == fixture["messages"]

