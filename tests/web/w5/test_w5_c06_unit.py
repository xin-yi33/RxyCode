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


def test_w5_c06_contract() -> None:
    """A visitor over quota receives 429 and does not occupy a worker."""
    from rxycode_server.quotas.service import Limits, QuotaGate
    from rxycode_worker.scheduler.capacity import Capacity, TopologyRefused, load_compose

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
    model = BoomModel()
    capacity = Capacity()
    gate = QuotaGate(
        limits=Limits(tasks=1, tokens=100, concurrency=1, preview_fee=1, sandbox_fee=1),
        capacity=capacity,
    )
    gate.seed_usage(tenant_id="visitor", user_id="visitor-user", tasks=1)
    refused = gate.create_run(
        database_url="postgresql://127.0.0.1:1/not-used",
        tenant_id="visitor",
        user_id="visitor-user",
        session_id="sess-visitor",
        message="hello",
        target_id="target-1",
        permission_profile="default",
        request_id="req-over-task",
        headers=headers,
        credentials="cred-present",
        budget=10,
        model=model,
    )
    assert refused.http_status == 429
    assert refused.body["error"] == "quota.exceeded"
    assert refused.body["kind"] == "task"
    assert refused.body["tenant_id"] == "visitor"
    assert refused.body["user_id"] == "visitor-user"
    assert refused.body["limit"] == 1
    assert refused.event["type"] == "quota.exceeded"
    assert refused.event["kind"] == "task"
    assert refused.event["tenant_id"] == "visitor"
    assert refused.event in gate.events_for("visitor")
    assert model.calls == 0
    assert capacity.workers == []
    assert capacity.live_ids == []

    bare = QuotaGate(
        limits=Limits(tasks=5, tokens=100, concurrency=1, preview_fee=1, sandbox_fee=1),
        capacity=Capacity(),
    )
    no_cred = bare.create_run(
        database_url="postgresql://127.0.0.1:1/not-used",
        tenant_id="visitor",
        user_id="visitor-user",
        session_id="sess-visitor",
        message="hello",
        target_id="target-1",
        permission_profile="default",
        request_id="req-no-cred",
        headers=headers,
        credentials=None,
        budget=10,
        model=model,
    )
    assert no_cred.http_status == 429
    assert no_cred.event["kind"] == "credentials"
    assert no_cred.event["tenant_id"] == "visitor"
    assert model.calls == 0
    assert bare.capacity.workers == []

    no_budget = bare.create_run(
        database_url="postgresql://127.0.0.1:1/not-used",
        tenant_id="visitor",
        user_id="visitor-user",
        session_id="sess-visitor",
        message="hello",
        target_id="target-1",
        permission_profile="default",
        request_id="req-no-budget",
        headers=headers,
        credentials="cred-present",
        budget=0,
        model=model,
    )
    assert no_budget.http_status == 429
    assert no_budget.event["kind"] == "budget"
    assert model.calls == 0
    assert bare.capacity.workers == []

    preview = QuotaGate(
        limits=Limits(tasks=5, tokens=100, concurrency=1, preview_fee=1, sandbox_fee=5),
        capacity=Capacity(),
    )
    preview.seed_usage(tenant_id="visitor", user_id="visitor-user", preview_fee=1)
    preview_refused = preview.create_run(
        database_url="postgresql://127.0.0.1:1/not-used",
        tenant_id="visitor",
        user_id="visitor-user",
        session_id="sess-visitor",
        message="hello",
        target_id="target-1",
        permission_profile="default",
        request_id="req-preview",
        headers=headers,
        credentials="cred-present",
        budget=10,
        model=model,
    )
    assert preview_refused.http_status == 429
    assert preview_refused.event["kind"] == "preview"
    assert model.calls == 0
    assert preview.capacity.live_ids == []

    sandbox_gate = QuotaGate(
        limits=Limits(tasks=5, tokens=100, concurrency=1, preview_fee=5, sandbox_fee=1),
        capacity=Capacity(),
    )
    sandbox_gate.seed_usage(tenant_id="visitor", user_id="visitor-user", sandbox_fee=1)
    sandbox_refused = sandbox_gate.create_run(
        database_url="postgresql://127.0.0.1:1/not-used",
        tenant_id="visitor",
        user_id="visitor-user",
        session_id="sess-visitor",
        message="hello",
        target_id="target-1",
        permission_profile="default",
        request_id="req-sandbox-fee",
        headers=headers,
        credentials="cred-present",
        budget=10,
        model=model,
    )
    assert sandbox_refused.http_status == 429
    assert sandbox_refused.event["kind"] == "sandbox"
    assert model.calls == 0
    assert sandbox_gate.capacity.workers == []
    assert sandbox_gate.capacity.live_ids == []


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
        short = capacity.provision(
            tenant_id="tenant-ttl",
            workspace_id="ws-ttl",
            ttl_seconds=1,
        )
        short_id = short.sandbox_id
        time.sleep(1.5)
        removed = set(capacity.gc())
        assert failed_id in removed
        assert short_id in removed
        assert healthy_id not in removed
        assert _inspect(failed_id).returncode != 0
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
