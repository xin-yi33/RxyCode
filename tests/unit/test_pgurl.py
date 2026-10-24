from __future__ import annotations

import subprocess

from sqlalchemy.exc import OperationalError

from tests.support import pgurl


def _ok(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, 0, "", "")


def test_unix_socket_probe_does_not_bypass_host_tcp_readiness(monkeypatch):
    monkeypatch.delenv("RXYCODE_PGURL", raising=False)
    calls: list[tuple[str, ...]] = []
    sleeps: list[float] = []
    attempts = 0

    def fake_docker(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return _ok(*args)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def execute(self, _statement):
            return None

    class Engine:
        def connect(self):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OperationalError(
                    "SELECT 1",
                    {},
                    RuntimeError("host TCP is still in the container init window"),
                )
            return Connection()

        def dispose(self):
            return None

    monkeypatch.setattr(pgurl, "docker", fake_docker)
    monkeypatch.setattr(pgurl, "create_engine", lambda *args, **kwargs: Engine())
    monkeypatch.setattr(pgurl.time, "sleep", sleeps.append)

    pgurl.ensure_container("rxy-test-pg", 55441)

    assert [call[0] for call in calls[:2]] == ["inspect", "start"]
    assert [call[0] for call in calls].count("exec") == 2
    assert attempts == 2
    assert sleeps == [1]
