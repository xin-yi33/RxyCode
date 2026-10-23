"""Worker phase timing + sandbox-probe negative-verdict TTL.

Pure python — no PostgreSQL, no bwrap. ``run.phase`` rows are captured by
stubbing ``append_event``; the userns probes are exercised with
``shutil.which`` stubbed so the verdict is deterministic on any host.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
for _name in (
    "rxycode-server",
    "rxycode-worker",
    "rxycode-runner",
    "rxycode-protocol",
    "rxycode-core",
):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_runner.sandbox import userns  # noqa: E402
from rxycode_worker import drain  # noqa: E402


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Every append_event call lands here instead of the outbox."""
    from rxycode_server.events import store

    calls: list[dict] = []
    monkeypatch.setattr(
        store,
        "append_event",
        lambda database_url, **kw: calls.append(kw) or len(calls),
    )
    return calls


def test_phase_emitter_rows_and_dedupe(captured_events):
    """run.phase rows carry {phase, elapsed_ms} — nothing else — and each
    boundary fires at most once per claim."""
    mark = drain._phase_emitter("sqlite://", "t1", "r1", time.monotonic())
    mark("claimed")
    mark("env_ready")
    mark("claimed")  # re-fire is a no-op: the first emission is the truth
    types = [c["event_type"] for c in captured_events]
    assert types == ["run.phase", "run.phase"]
    phases = [c["payload"]["phase"] for c in captured_events]
    assert phases == ["claimed", "env_ready"]
    for call in captured_events:
        assert call["tenant_id"] == "t1"
        assert call["run_id"] == "r1"
        assert set(call["payload"]) == {"phase", "elapsed_ms"}
        assert isinstance(call["payload"]["elapsed_ms"], int)
        assert call["payload"]["elapsed_ms"] >= 0


def test_phase_emitter_never_raises(monkeypatch):
    """A failed append is logged and forgotten — instrumentation cannot
    break the run, and the phase is not re-fired later (a late row would
    only misreport elapsed_ms)."""
    from rxycode_server.events import store

    def _boom(*_a, **_kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "append_event", _boom)
    mark = drain._phase_emitter("sqlite://", "t1", "r1", time.monotonic())
    mark("claimed")  # does not raise
    mark("claimed")  # still counted as fired — no retry storm


def test_ctl_phase_op_allowlists_and_stamps_parent_side(captured_events):
    """The ctl `phase` op emits run.phase ONLY for the child vocabulary —
    a confined turn can neither mint a run.* row itself nor name an
    arbitrary phase, and elapsed_ms is stamped on the parent's clock."""
    mark = drain._phase_emitter("sqlite://", "t1", "r1", time.monotonic())
    handlers = drain._ctl_handlers(
        drain.WorkerConfig(database_url="sqlite://", worker_id="w"),
        tenant_id="t1",
        run_id="r1",
        epoch=1,
        workdir=Path("."),
        journal_dir=Path("."),
        paused=None,
        paused_info={},
        phase_mark=mark,
    )
    assert handlers["phase"]({"phase": "agent_assembled"}) == {"emitted": True}
    assert handlers["phase"]({"phase": "prompt_dispatched"}) == {"emitted": True}
    # Not in the child vocabulary — refused, no row.
    assert handlers["phase"]({"phase": "final"}) == {"emitted": False}
    assert handlers["phase"]({"phase": "run.error"}) == {"emitted": False}
    assert handlers["phase"]({"phase": ""}) == {"emitted": False}
    phases = [c["payload"]["phase"] for c in captured_events]
    assert phases == ["agent_assembled", "prompt_dispatched"]


def test_ctl_emit_stamps_first_event_once(captured_events):
    """The first successful child emit also lands run.phase{first_event};
    reserved-namespace forgeries are denied before any stamp."""
    mark = drain._phase_emitter("sqlite://", "t1", "r1", time.monotonic())
    handlers = drain._ctl_handlers(
        drain.WorkerConfig(database_url="sqlite://", worker_id="w"),
        tenant_id="t1",
        run_id="r1",
        epoch=1,
        workdir=Path("."),
        journal_dir=Path("."),
        paused=None,
        paused_info={},
        phase_mark=mark,
    )
    # A forged reserved row is denied and must not count as first_event.
    assert handlers["emit"]({"type": "run.error", "payload": {}})["denied"]
    assert not captured_events
    handlers["emit"]({"type": "event/agent_started", "payload": {}})
    handlers["emit"]({"type": "usage.delta", "payload": {}})
    types = [c["event_type"] for c in captured_events]
    assert types == ["event/agent_started", "run.phase", "usage.delta"]
    assert captured_events[1]["payload"]["phase"] == "first_event"


@pytest.fixture
def userns_cache_state():
    """Fresh probe caches per test — the module globals are process state."""
    saved = (
        dict(userns._OVERLAY_DESTS),
        dict(userns._OVERLAY_DESTS_FAILED_AT),
        userns._AVAILABLE,
        userns._AVAILABLE_FAILED_AT,
    )
    userns._OVERLAY_DESTS.clear()
    userns._OVERLAY_DESTS_FAILED_AT.clear()
    userns._AVAILABLE = None
    userns._AVAILABLE_FAILED_AT = 0.0
    yield
    userns._OVERLAY_DESTS.clear()
    userns._OVERLAY_DESTS.update(saved[0])
    userns._OVERLAY_DESTS_FAILED_AT.clear()
    userns._OVERLAY_DESTS_FAILED_AT.update(saved[1])
    userns._AVAILABLE = saved[2]
    userns._AVAILABLE_FAILED_AT = saved[3]


def test_overlay_dests_negative_verdict_memoized_then_expires(
    tmp_path, monkeypatch, userns_cache_state
):
    """A failed overlay probe is memoized inside the TTL — no re-paying the
    multi-second probe per run — then re-probed after expiry so a repaired
    host picks overlayfs up without a restart. The {} verdict semantics
    are untouched: dests that fail simply stay read-only."""
    which_calls = []

    def _which(name):
        which_calls.append(name)
        return None  # no bwrap on this host -> the honest {} verdict

    monkeypatch.setattr(userns.shutil, "which", _which)
    monkeypatch.setenv("RXYCODE_SANDBOX_PROBE_TTL_SECONDS", "300")

    assert userns.overlay_dests(tmp_path) == {}
    assert len(which_calls) == 1
    # Inside the TTL the verdict is served from the memo — no re-probe.
    assert userns.overlay_dests(tmp_path) == {}
    assert len(which_calls) == 1

    # Expire the verdict: the next call re-probes the real environment.
    key = str(tmp_path)
    userns._OVERLAY_DESTS_FAILED_AT[key] = time.monotonic() - 400.0
    assert userns.overlay_dests(tmp_path) == {}
    assert len(which_calls) == 2


def test_userns_available_negative_verdict_expires(
    monkeypatch, userns_cache_state
):
    """Same TTL for the unshare probe: False stays memoized in the window,
    then re-probes — and a probe that now succeeds is honoured."""
    calls = []

    def _which(name):
        calls.append(name)
        return None

    monkeypatch.setattr(userns.shutil, "which", _which)
    monkeypatch.setenv("RXYCODE_SANDBOX_PROBE_TTL_SECONDS", "300")

    assert userns.userns_available() is False
    assert userns.userns_available() is False
    assert len(calls) == 1  # memoized inside the TTL

    userns._AVAILABLE_FAILED_AT = time.monotonic() - 400.0
    assert userns.userns_available() is False
    assert len(calls) == 2  # re-probed after expiry

    # A repaired host: the very next re-probe returns True and stays True.
    monkeypatch.setattr(userns.shutil, "which", lambda name: "/usr/bin/bwrap")

    class _Done:
        returncode = 0

    monkeypatch.setattr(
        userns.subprocess, "run", lambda *a, **kw: _Done()
    )
    userns._AVAILABLE_FAILED_AT = time.monotonic() - 400.0
    assert userns.userns_available() is True
    assert userns.userns_available() is True  # True is process-lifetime
