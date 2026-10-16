"""WEB-W5-C06. An over-quota visitor gets 429 and a failed sandbox is removed."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-server" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO / "packages" / "rxycode-runner" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

COMPOSE = REPO / "infra" / "compose" / "compose.yaml"


class BoomModel:
    """A model client. The quota gate must not call it when admission fails."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        raise AssertionError("model called")


def _inspect(sandbox_id: str) -> subprocess.CompletedProcess[str]:
    from rxycode_runner.sandbox.gvisor import docker_executable

    return subprocess.run(
        [docker_executable(), "inspect", sandbox_id],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


class OkModel:
    """A model client that records a real call."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        return prompt


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    from rxycode_runner.sandbox.gvisor import docker_executable

    return subprocess.run(
        [docker_executable(), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _postgres() -> str:
    _docker("rm", "-f", "rxy-w5c06-pg")
    started = _docker(
        "run",
        "-d",
        "--name",
        "rxy-w5c06-pg",
        "-e",
        "POSTGRES_HOST_AUTH_METHOD=trust",
        "-e",
        "POSTGRES_DB=rxycode",
        "-p",
        "127.0.0.1:55433:5432",
        "postgres:16",
    )
    if started.returncode != 0:
        raise RuntimeError(started.stderr or started.stdout)
    deadline = time.time() + 60
    while time.time() < deadline:
        ready = _docker("exec", "rxy-w5c06-pg", "pg_isready", "-U", "postgres", "-d", "rxycode")
        if ready.returncode == 0:
            return "postgresql+psycopg://postgres@127.0.0.1:55433/rxycode"
        time.sleep(1)
    logs = _docker("logs", "rxy-w5c06-pg")
    raise RuntimeError(logs.stderr or logs.stdout or "postgres did not become ready")


def _stop_postgres() -> None:
    _docker("rm", "-f", "rxy-w5c06-pg")


def test_w5_c06_contract() -> None:
    """A visitor over quota receives 429 and does not occupy a worker."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.persistence.models import Organization, Project, Run, RunEvent, SessionRow, User
    from rxycode_server.quotas.service import Limits, QuotaGate, QuotaRefused, install_gate
    from rxycode_server.runs.service import complete_run, create_run
    from rxycode_worker.scheduler.capacity import Capacity, CapacityFull, TopologyRefused, load_compose

    topo = load_compose(COMPOSE)
    assert {"postgres", "redis", "minio"} <= set(topo)
    for name, spec in topo.items():
        assert spec.image
        assert spec.healthcheck, name
        assert spec.privileged is False
    with tempfile.TemporaryDirectory(prefix="rxy-c06-compose-") as tmp:
        bad = Path(tmp) / "privileged.yaml"
        bad.write_text(
            "\n".join(
                [
                    "services:",
                    "  postgres:",
                    "    image: postgres:16",
                    "    privileged: true",
                    "    healthcheck:",
                    "      test: [\"CMD\", \"true\"]",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(TopologyRefused):
            load_compose(bad)
        missing = Path(tmp) / "nocheck.yaml"
        missing.write_text(
            "\n".join(
                [
                    "services:",
                    "  redis:",
                    "    image: redis:7",
                    "    privileged: false",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(TopologyRefused):
            load_compose(missing)

    headers = {
        "x-quota-limit": "999999",
        "x-tenant-id": "tenant-b",
        "x-user-id": "root",
        "x-budget": "1000000",
        "x-preview-fee": "1000000",
    }
    slot = Capacity()
    held = slot.acquire("tenant-slot", "user-slot", limit=1, held=0)
    with pytest.raises(CapacityFull):
        slot.acquire("tenant-slot", "user-slot", limit=1, held=1)
    slot.release_worker(held)

    def deny(gate: QuotaGate, **kwargs: object) -> QuotaRefused:
        with pytest.raises(QuotaRefused) as caught:
            create_run(
                str(kwargs.pop("database_url")),
                tenant_id=str(kwargs.pop("tenant_id")),
                user_id="visitor-user",
                session_id=str(kwargs.pop("session_id")),
                message=str(kwargs.pop("message")),
                target_id="target-1",
                permission_profile="default",
                request_id=str(kwargs.pop("request_id")),
                headers=headers,
                claimed_tenant_id="tenant-b",
                credentials=kwargs.pop("credentials"),  # type: ignore[arg-type]
                budget=kwargs.pop("budget"),  # type: ignore[arg-type]
                model=kwargs.pop("model"),
                quota=kwargs.pop("quota", gate),
            )
        return caught.value

    cred_model = BoomModel()
    cred_gate = QuotaGate(limits=Limits(tasks=5, tokens=100, concurrency=5, preview_fee=5, sandbox_fee=5), capacity=Capacity())
    cred = deny(
        cred_gate,
        database_url="postgresql://127.0.0.1:1/not-used",
        tenant_id="visitor",
        session_id="sess-visitor",
        message="hello",
        request_id="req-no-cred",
        credentials=None,
        budget=10,
        model=cred_model,
    )
    assert cred.decision.http_status == 429
    assert cred.decision.event["kind"] == "credentials"
    assert cred.decision.event["tenant_id"] == "visitor"
    assert cred.decision.event in cred_gate.events_for("visitor")
    assert cred_model.calls == 0
    assert cred_gate.capacity.workers == []
    assert cred_gate.capacity.live_ids == []

    budget_model = BoomModel()
    budget_gate = QuotaGate(limits=Limits(tasks=5, tokens=100, concurrency=5, preview_fee=5, sandbox_fee=5), capacity=Capacity())
    budget = deny(
        budget_gate,
        database_url="postgresql://127.0.0.1:1/not-used",
        tenant_id="visitor",
        session_id="sess-visitor",
        message="hello",
        request_id="req-no-budget",
        credentials="cred-present",
        budget=0,
        model=budget_model,
    )
    assert budget.decision.event["kind"] == "budget"
    assert budget_model.calls == 0
    assert budget_gate.capacity.workers == []

    token_model = BoomModel()
    token_gate = QuotaGate(limits=Limits(tasks=5, tokens=1, concurrency=5, preview_fee=5, sandbox_fee=5), capacity=Capacity())
    early_token = deny(
        token_gate,
        database_url="postgresql://127.0.0.1:1/not-used",
        tenant_id="visitor",
        session_id="sess-visitor",
        message="hello world",
        request_id="req-token-early",
        credentials="cred-present",
        budget=10,
        model=token_model,
    )
    assert early_token.decision.event["kind"] == "token"
    assert early_token.decision.body["limit"] == 1
    assert token_model.calls == 0
    assert token_gate.capacity.workers == []

    url = _postgres()
    try:
        upgrade_head(url)
        engine = create_engine(url)
        with Session(engine) as db:
            for tenant in (
                "visitor-task",
                "visitor-token",
                "visitor-conc",
                "visitor-preview",
                "visitor-sandbox",
                "visitor-ttl",
                "visitor-overlap",
                "visitor-race",
            ):
                db.add(User(id=f"user-{tenant}", github_id=f"gh-{tenant}", kind="github"))
                db.add(Organization(id=f"org-{tenant}", tenant_id=tenant))
                db.add(Project(id=f"project-{tenant}", tenant_id=tenant, name="app", repo_config={}))
                db.add(SessionRow(id=f"sess-a-{tenant}", tenant_id=tenant, project_id=f"project-{tenant}", title="a"))
                db.add(SessionRow(id=f"sess-b-{tenant}", tenant_id=tenant, project_id=f"project-{tenant}", title="b"))
                db.add(SessionRow(id=f"sess-c-{tenant}", tenant_id=tenant, project_id=f"project-{tenant}", title="c"))
            db.commit()
        engine.dispose()

        def admit(tenant: str, gate: QuotaGate, model: OkModel, request: str, session: str):
            accepted = create_run(
                url,
                tenant_id=tenant,
                user_id="visitor-user",
                session_id=session,
                message="hello",
                target_id="target-1",
                permission_profile="default",
                request_id=request,
                headers=headers,
                claimed_tenant_id="tenant-b",
                credentials="cred-present",
                budget=10,
                model=model,
                quota=gate,
            )
            assert accepted.http_status == 202
            return accepted

        def count(tenant: str) -> int:
            checker = create_engine(url)
            try:
                with Session(checker) as db:
                    return len(db.scalars(select(Run).where(Run.tenant_id == tenant)).all())
            finally:
                checker.dispose()

        token_cap = Capacity()
        token_db = QuotaGate(limits=Limits(tasks=5, tokens=1, concurrency=5, preview_fee=5, sandbox_fee=5), capacity=token_cap)
        token_ok = OkModel()
        admit("visitor-token", token_db, token_ok, "req-token-1", "sess-a-visitor-token")
        assert token_ok.calls == 1
        token_again = BoomModel()
        token_hit = deny(
            token_db,
            database_url=url,
            tenant_id="visitor-token",
            session_id="sess-b-visitor-token",
            message="hello",
            request_id="req-token-2",
            credentials="cred-present",
            budget=10,
            model=token_again,
            quota=token_db,
        )
        assert token_hit.decision.event["kind"] == "token"
        assert token_again.calls == 0
        assert count("visitor-token") == 1

        conc_cap = Capacity()
        conc_gate = QuotaGate(limits=Limits(tasks=5, tokens=100, concurrency=1, preview_fee=5, sandbox_fee=5), capacity=conc_cap)
        conc_ok = OkModel()
        conc_first = admit("visitor-conc", conc_gate, conc_ok, "req-conc-1", "sess-a-visitor-conc")
        conc_boom = BoomModel()
        conc_hit = deny(
            conc_gate,
            database_url=url,
            tenant_id="visitor-conc",
            session_id="sess-b-visitor-conc",
            message="hello",
            request_id="req-conc-2",
            credentials="cred-present",
            budget=10,
            model=conc_boom,
            quota=conc_gate,
        )
        assert conc_hit.decision.event["kind"] == "concurrency"
        assert conc_boom.calls == 0
        assert count("visitor-conc") == 1
        fresh_conc = QuotaGate(
            limits=Limits(tasks=5, tokens=100, concurrency=1, preview_fee=5, sandbox_fee=5),
            capacity=Capacity(),
        )
        fresh_boom = BoomModel()
        fresh_hit = deny(
            fresh_conc,
            database_url=url,
            tenant_id="visitor-conc",
            session_id="sess-b-visitor-conc",
            message="hello",
            request_id="req-conc-fresh",
            credentials="cred-present",
            budget=10,
            model=fresh_boom,
            quota=fresh_conc,
        )
        assert fresh_hit.decision.event["kind"] == "concurrency"
        assert fresh_boom.calls == 0
        assert complete_run(
            url,
            run_id=conc_first.run_id,
            tenant_id="visitor-conc",
            user_id="visitor-user",
            quota=fresh_conc,
        ) == "succeeded"
        conc_again = OkModel()
        admit("visitor-conc", fresh_conc, conc_again, "req-conc-3", "sess-a-visitor-conc")
        assert conc_again.calls == 1

        ttl_gate = QuotaGate(
            limits=Limits(tasks=5, tokens=100, concurrency=1, preview_fee=5, sandbox_fee=5),
            capacity=Capacity(),
            worker_ttl=1,
        )
        ttl_ok = OkModel()
        admit("visitor-ttl", ttl_gate, ttl_ok, "req-ttl-1", "sess-a-visitor-ttl")
        ttl_soon = BoomModel()
        ttl_blocked = deny(
            QuotaGate(
                limits=Limits(tasks=5, tokens=100, concurrency=1, preview_fee=5, sandbox_fee=5),
                capacity=Capacity(),
                worker_ttl=1,
            ),
            database_url=url,
            tenant_id="visitor-ttl",
            session_id="sess-b-visitor-ttl",
            message="hello",
            request_id="req-ttl-blocked",
            credentials="cred-present",
            budget=10,
            model=ttl_soon,
        )
        assert ttl_blocked.decision.event["kind"] == "concurrency"
        assert ttl_soon.calls == 0
        time.sleep(2)
        ttl_next = OkModel()
        admit(
            "visitor-ttl",
            QuotaGate(
                limits=Limits(tasks=5, tokens=100, concurrency=1, preview_fee=5, sandbox_fee=5),
                capacity=Capacity(),
                worker_ttl=1,
            ),
            ttl_next,
            "req-ttl-2",
            "sess-b-visitor-ttl",
        )
        assert ttl_next.calls == 1


        limits = Limits(tasks=5, tokens=100, concurrency=1, preview_fee=5, sandbox_fee=5)
        overlap_gate = QuotaGate(limits=limits, capacity=Capacity())
        left = admit("visitor-overlap", overlap_gate, OkModel(), "req-over-1", "sess-a-visitor-overlap")
        other = QuotaGate(limits=limits, capacity=Capacity())
        blocked = BoomModel()
        blocked_hit = deny(
            other,
            database_url=url,
            tenant_id="visitor-overlap",
            session_id="sess-b-visitor-overlap",
            message="hello",
            request_id="req-over-blocked",
            credentials="cred-present",
            budget=10,
            model=blocked,
            quota=other,
        )
        assert blocked_hit.decision.event["kind"] == "concurrency"
        assert blocked.calls == 0
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import text
        from rxycode_worker.supervisor import commit_terminal

        leaser = create_engine(url)
        with leaser.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status = 'leased',
                        lease_owner = 'worker-c06',
                        lease_epoch = 1,
                        lease_until = :until
                    WHERE id = :id
                    """
                ),
                {
                    "id": left.run_id,
                    "until": datetime.now(timezone.utc) + timedelta(minutes=5),
                },
            )
        leaser.dispose()
        commit_terminal(url, left.run_id, "worker-c06", 1, "succeeded")
        follow = QuotaGate(limits=limits, capacity=Capacity())
        followed = OkModel()
        admit("visitor-overlap", follow, followed, "req-over-2", "sess-b-visitor-overlap")
        assert followed.calls == 1

        import threading

        race_limits = Limits(tasks=5, tokens=100, concurrency=1, preview_fee=5, sandbox_fee=5)
        race_outcomes: list[str] = []
        race_lock = threading.Lock()
        race_start = threading.Barrier(2)

        def race(session: str, request: str) -> None:
            race_start.wait(timeout=10)
            gate = QuotaGate(limits=race_limits, capacity=Capacity())
            try:
                create_run(
                    url,
                    tenant_id="visitor-race",
                    user_id="visitor-user",
                    session_id=session,
                    message="hello",
                    target_id="target-1",
                    permission_profile="default",
                    request_id=request,
                    headers=headers,
                    claimed_tenant_id="tenant-b",
                    credentials="cred-present",
                    budget=10,
                    model=OkModel(),
                    quota=gate,
                )
                with race_lock:
                    race_outcomes.append("ok")
            except QuotaRefused as exc:
                with race_lock:
                    race_outcomes.append(str(exc.decision.event["kind"]))

        racers = [
            threading.Thread(target=race, args=("sess-a-visitor-race", "req-race-1")),
            threading.Thread(target=race, args=("sess-b-visitor-race", "req-race-2")),
        ]
        for racer in racers:
            racer.start()
        for racer in racers:
            racer.join(timeout=30)
        assert sorted(race_outcomes) == ["concurrency", "ok"]
        assert count("visitor-race") == 1

        preview_cap = Capacity()
        preview_gate = QuotaGate(limits=Limits(tasks=5, tokens=100, concurrency=5, preview_fee=1, sandbox_fee=5), capacity=preview_cap)
        preview_ok = OkModel()
        admit("visitor-preview", preview_gate, preview_ok, "req-preview-1", "sess-a-visitor-preview")
        preview_boom = BoomModel()
        preview_hit = deny(
            preview_gate,
            database_url=url,
            tenant_id="visitor-preview",
            session_id="sess-b-visitor-preview",
            message="hello",
            request_id="req-preview-2",
            credentials="cred-present",
            budget=10,
            model=preview_boom,
            quota=preview_gate,
        )
        assert preview_hit.decision.event["kind"] == "preview"
        assert preview_boom.calls == 0
        assert preview_cap.live_ids == []
        assert count("visitor-preview") == 1

        sandbox_cap = Capacity()
        sandbox_gate = QuotaGate(limits=Limits(tasks=5, tokens=100, concurrency=5, preview_fee=5, sandbox_fee=1), capacity=sandbox_cap)
        sandbox_ok = OkModel()
        admit("visitor-sandbox", sandbox_gate, sandbox_ok, "req-sandbox-1", "sess-a-visitor-sandbox")
        sandbox_boom = BoomModel()
        sandbox_hit = deny(
            sandbox_gate,
            database_url=url,
            tenant_id="visitor-sandbox",
            session_id="sess-b-visitor-sandbox",
            message="hello",
            request_id="req-sandbox-2",
            credentials="cred-present",
            budget=10,
            model=sandbox_boom,
            quota=sandbox_gate,
        )
        assert sandbox_hit.decision.event["kind"] == "sandbox"
        assert sandbox_boom.calls == 0
        assert count("visitor-sandbox") == 1

        task_cap = Capacity()
        task_gate = QuotaGate(limits=Limits(tasks=1, tokens=100, concurrency=5, preview_fee=5, sandbox_fee=5), capacity=task_cap)
        install_gate(task_gate)
        try:
            task_ok = OkModel()
            accepted = create_run(
                url,
                tenant_id="visitor-task",
                user_id="visitor-user",
                session_id="sess-a-visitor-task",
                message="hello",
                target_id="target-1",
                permission_profile="default",
                request_id="req-task-1",
                headers=headers,
                claimed_tenant_id="tenant-b",
                credentials="cred-present",
                budget=10,
                model=task_ok,
            )
            assert accepted.http_status == 202
            assert task_ok.calls == 1
            task_boom = BoomModel()
            with pytest.raises(QuotaRefused) as task_caught:
                create_run(
                    url,
                    tenant_id="visitor-task",
                    user_id="visitor-user",
                    session_id="sess-b-visitor-task",
                    message="hello",
                    target_id="target-1",
                    permission_profile="default",
                    request_id="req-task-2",
                    headers=headers,
                    claimed_tenant_id="tenant-b",
                    credentials="cred-present",
                    budget=10,
                    model=task_boom,
                )
            task_decision = task_caught.value.decision
            assert task_decision.http_status == 429
            assert task_decision.body["error"] == "quota.exceeded"
            assert task_decision.body["kind"] == "task"
            assert task_decision.body["limit"] == 1
            assert task_decision.event["type"] == "quota.exceeded"
            assert task_decision.event["tenant_id"] == "visitor-task"
            assert task_decision.event["user_id"] == "visitor-user"
            assert task_decision.event in task_gate.events_for("visitor-task")
            assert task_boom.calls == 0
            assert count("visitor-task") == 1
            checker = create_engine(url)
            try:
                with Session(checker) as db:
                    row = db.scalars(select(Run).where(Run.tenant_id == "visitor-task")).one()
            finally:
                checker.dispose()
            assert row.tenant_id == "visitor-task"
        finally:
            install_gate(None)
    finally:
        _stop_postgres()


def test_w5_c06_negative() -> None:
    """GC removes a sandbox created before an exception and an expired one."""
    from rxycode_worker.scheduler.capacity import Capacity

    capacity = Capacity()
    failed_id = ""
    short_id = ""
    healthy_id = ""
    try:
        healthy = capacity.provision(tenant_id="tenant-ok", workspace_id="ws-ok")
        healthy_id = healthy.sandbox_id
        try:
            with capacity.sandbox(tenant_id="tenant-bad", workspace_id="ws-bad") as failed:
                failed_id = failed.sandbox_id
                assert _inspect(failed_id).returncode == 0
                raise RuntimeError("after sandbox create")
        except RuntimeError as exc:
            assert str(exc) == "after sandbox create"
        assert _inspect(failed_id).returncode != 0
        short = capacity.provision(
            tenant_id="tenant-ttl",
            workspace_id="ws-ttl",
            ttl_seconds=1,
        )
        short_id = short.sandbox_id
        time.sleep(2.5)
        assert _inspect(short_id).returncode != 0
        alive = json.loads(_inspect(healthy_id).stdout)[0]
        assert alive["State"]["Status"] == "running"
        assert alive["Config"]["Labels"]["rxy.tenant"] == "tenant-ok"
        samples = capacity.cold_start_samples()
        assert len(samples) >= 3
        assert all(sample > 0 for sample in samples)
        assert capacity.cold_start_p50() == _nearest_rank(samples, 50)
        assert capacity.cold_start_p95() == _nearest_rank(samples, 95)
    finally:
        capacity.destroy_all()
        for sandbox_id in (failed_id, short_id, healthy_id):
            if sandbox_id:
                assert _inspect(sandbox_id).returncode != 0


def _nearest_rank(samples: list[float], percentile: int) -> float:
    ordered = sorted(samples)
    index = max(0, -(-len(ordered) * percentile // 100) - 1)
    return ordered[min(index, len(ordered) - 1)]
