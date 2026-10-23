"""WEB-W5-C06. Two tenants running together keep separate workspaces and events."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-server" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO / "packages" / "rxycode-runner" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    from rxycode_runner.sandbox.gvisor import docker_executable

    return subprocess.run(
        [docker_executable(), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_w5_c06_integration() -> None:
    """Tenants A and B keep isolated workspace files, labels, and events."""
    from rxycode_runner.sandbox.provider import AttachRefused
    from rxycode_worker.scheduler.capacity import Capacity

    capacity = Capacity()
    nonce_a = "a1b2c3d4e5f60718"
    nonce_b = "b9c8d7e6f5041320"
    results: dict[str, object] = {}
    errors: list[BaseException] = []
    ready = threading.Barrier(2)

    def work(tenant: str, workspace: str, nonce: str) -> None:
        try:
            handle = capacity.provision(tenant_id=tenant, workspace_id=workspace)
            capacity.write_marker(handle, nonce)
            capacity.publish_event(
                handle,
                {"type": "workspace.ready", "tenant_id": tenant, "nonce": nonce},
            )
            ready.wait(timeout=90)
            results[tenant] = handle
        except BaseException as exc:
            errors.append(exc)
            try:
                ready.abort()
            except threading.BrokenBarrierError:
                pass

    threads = [
        threading.Thread(target=work, args=("tenant-a", "ws-tenant-a", nonce_a)),
        threading.Thread(target=work, args=("tenant-b", "ws-tenant-b", nonce_b)),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert errors == []
        assert set(results) == {"tenant-a", "tenant-b"}
        handle_a = results["tenant-a"]
        handle_b = results["tenant-b"]
        assert handle_a.sandbox_id != handle_b.sandbox_id
        assert handle_a.workspace_id != handle_b.workspace_id
        assert capacity.read_marker(handle_a) == nonce_a
        assert capacity.read_marker(handle_b) == nonce_b
        assert capacity.read_events(handle_a)["nonce"] == nonce_a
        assert capacity.read_events(handle_b)["tenant_id"] == "tenant-b"
        try:
            capacity.read_marker(handle_b, tenant_id="tenant-a")
        except AttachRefused:
            pass
        else:
            raise AssertionError("tenant A read tenant B marker")
        for handle, tenant, nonce, other in (
            (handle_a, "tenant-a", nonce_a, nonce_b),
            (handle_b, "tenant-b", nonce_b, nonce_a),
        ):
            info = json.loads(_docker("inspect", handle.sandbox_id).stdout)[0]
            labels = info["Config"]["Labels"]
            assert labels["rxy.tenant"] == tenant
            assert labels["rxy.workspace"] == handle.workspace_id
            assert info["HostConfig"]["NetworkMode"] == "none"
            assert info["State"]["Status"] == "running"
            marker = _docker(
                "exec",
                handle.sandbox_id,
                "python",
                "-c",
                "print(open('/tmp/tenant-marker').read())",
            )
            assert marker.returncode == 0
            assert marker.stdout.strip() == nonce
            assert other not in marker.stdout
            raw_events = _docker(
                "exec",
                handle.sandbox_id,
                "python",
                "-c",
                "print(open('/tmp/events.json').read())",
            )
            assert raw_events.returncode == 0
            assert other not in raw_events.stdout
            assert nonce in raw_events.stdout
        samples = capacity.cold_start_samples()
        assert len(samples) >= 2
        assert capacity.cold_start_p50() == _nearest_rank(samples, 50)
        assert capacity.cold_start_p95() >= capacity.cold_start_p50()
    finally:
        capacity.destroy_all()


def _nearest_rank(samples: list[float], percentile: int) -> float:
    ordered = sorted(samples)
    index = max(0, -(-len(ordered) * percentile // 100) - 1)
    return ordered[min(index, len(ordered) - 1)]
