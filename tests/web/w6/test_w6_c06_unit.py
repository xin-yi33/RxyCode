"""WEB-W6-C06. A new user can finish a real run and download its artifact."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from tests.support.pgurl import ensure_container, worker_url

_PG_BASE = "postgresql+psycopg://postgres@127.0.0.1:55432/rxycode"
ensure_container("rxy-w2c01-pg", 55432)
DATABASE = worker_url(_PG_BASE)
SECRET = "local-web-secret-value-32bytes!!"

# Every xdist worker gets a fresh database — nothing else migrates it, and the
# release journey below writes oauth_states/users directly.
from rxycode_server.persistence.migrate import upgrade_head

upgrade_head(DATABASE)


def test_w6_c06_contract() -> None:
    """Login starts, a real pytest runs, and the artifact download matches that output."""
    from rxycode_server.release.journey import cloud_release_journey

    work = REPO / "tests" / "web" / "w6" / "_release_c06"
    work.mkdir(parents=True, exist_ok=True)
    try:
        result = cloud_release_journey(DATABASE, work_dir=work, secret=SECRET)
    finally:
        for child in sorted(work.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        work.rmdir()
    assert result["authorization_url"].startswith("https://github.com/login/oauth/authorize")
    assert result["callback_completed"] is False
    assert result["pytest_exit"] == 0
    assert b"1 passed" in result["artifact"]
    assert result["recovered_event"] == "artifact.created"
    if result["import"]["status"] == "imported":
        assert result["import"]["workspace_id"]
    else:
        assert result["import"]["status"] == "blocked"
        assert result["import"]["reason"]


def test_w6_c06_negative(tmp_path: Path) -> None:
    """An unpaired device cannot run Remote Full in the cloud."""
    from rxycode_server.release.journey import remote_full_unpaired

    result = remote_full_unpaired(SECRET, "desk-none", tmp_path)
    assert result["executed"] is False
    assert result["permission"] in {None, ""}
    assert result["target"] == "remote"
    assert result["http_status"] == 404
    assert not (tmp_path / "remote-full.txt").exists()
