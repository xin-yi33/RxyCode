"""Persistent local vector memory contracts."""

from __future__ import annotations

from datetime import datetime


def test_feature_hash_vectors_are_stable_and_cosine_ranked(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))

    from RxyCode.RxyCode1_1_0.memory.vector_memory import ExperienceVectorMemory

    first = ExperienceVectorMemory(project="demo", max_entries=20)
    first.add(
        "Use FastAPI dependency injection for the database session",
        kind="execution",
        outcome="success",
        session="session-a",
    )
    first.add(
        "Use CSS grid for the dashboard layout",
        kind="execution",
        outcome="success",
        session="session-b",
    )

    # A fresh instance proves vectors and metadata came back from disk.
    restored = ExperienceVectorMemory(project="demo", max_entries=20)
    results = restored.search("FastAPI database dependency", top_k=50)

    assert len(results) == 2
    assert results[0].text.startswith("Use FastAPI")
    assert results[0].score > results[1].score
    assert results[0].kind == "execution"
    assert results[0].outcome == "success"
    assert results[0].project == "demo"
    assert results[0].session == "session-a"
    datetime.fromisoformat(results[0].timestamp)


def test_vector_memory_filters_projects_and_bounds_output(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))

    from RxyCode.RxyCode1_1_0.memory.vector_memory import ExperienceVectorMemory

    demo = ExperienceVectorMemory(project="demo", max_entries=100)
    other = ExperienceVectorMemory(project="other", max_entries=100)
    for index in range(30):
        demo.add(
            f"database migration lesson {index} " + "x" * 300,
            kind="failure",
            outcome="failed",
            session="s",
        )
    other.add(
        "database migration from another project",
        kind="failure",
        outcome="failed",
        session="other",
    )

    results = demo.search("database migration", top_k=999)
    rendered = demo.retrieve_context(
        "database migration", top_k=999, max_chars=600,
    )

    assert len(results) == demo.MAX_TOP_K
    assert all(item.project == "demo" for item in results)
    assert len(rendered) <= 600
    assert "another project" not in rendered


def test_corrupt_records_are_skipped_during_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))

    from RxyCode.RxyCode1_1_0.memory.vector_memory import ExperienceVectorMemory

    memory = ExperienceVectorMemory(project="demo")
    memory.add(
        "valid recovery lesson",
        kind="execution",
        outcome="success",
        session="s",
    )
    with memory.path.open("a", encoding="utf-8") as stream:
        stream.write("\n{not valid json}\n")

    restored = ExperienceVectorMemory(project="demo")
    results = restored.search("recovery lesson", top_k=3)

    assert len(results) == 1
    assert results[0].text == "valid recovery lesson"
