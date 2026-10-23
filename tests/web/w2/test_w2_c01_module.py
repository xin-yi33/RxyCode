"""WEB-W2-C01. Tenants stay isolated, and a legacy JSON file is not rewritten."""
from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import venv
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-server" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from appserver.task_store import DesktopTaskStore
from rxycode_server.persistence.migrate import upgrade_head
from rxycode_server.persistence.models import (
    Organization,
    Project,
    Run,
    SessionRow,
    User,
    import_desktop_tasks,
    seed_demo,
)


def test_w2_c01_integration(postgres_url: str, tmp_path: Path):
    """Two tenants may use the same project name, and legacy import does not overwrite."""
    upgrade_head(postgres_url)
    engine = create_engine(postgres_url)
    store_path = tmp_path / "tasks.json"
    store = DesktopTaskStore(store_path, persistent=True)
    store.upsert(session_id="legacy-1", title="old", workspace_root=tmp_path / "workspace")
    before = store_path.read_bytes()
    with Session(engine) as db:
        for tenant_id in ("tenant-a", "tenant-b"):
            db.add(User(id=f"user-{tenant_id}", github_id=f"gh-{tenant_id}", kind="github"))
            db.add(Organization(id=f"org-{tenant_id}", tenant_id=tenant_id))
            db.add(
                Project(
                    id=f"project-{tenant_id}",
                    tenant_id=tenant_id,
                    name="app",
                    repo_config={"remote": tenant_id},
                )
            )
            db.add(
                SessionRow(
                    id=f"session-{tenant_id}",
                    tenant_id=tenant_id,
                    project_id=f"project-{tenant_id}",
                    title="app",
                )
            )
        db.flush()
        seed_demo(db)
        seed_demo(db)
        imported = import_desktop_tasks(
            store, db, tenant_id="demo", project_id="project-demo"
        )
        db.commit()
    assert imported == 1
    assert store_path.read_bytes() == before
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT s.tenant_id, p.tenant_id, p.name "
                "FROM sessions s JOIN projects p ON p.id = s.project_id "
                "WHERE p.name = 'app' ORDER BY s.tenant_id"
            )
        ).all()
        demo = conn.execute(text("SELECT count(*) FROM projects WHERE name = 'demo'")).scalar()
    assert rows == [("tenant-a", "tenant-a", "app"), ("tenant-b", "tenant-b", "app")]
    assert demo == 1
    with Session(engine) as db:
        db.add(
            SessionRow(
                id="cross-session",
                tenant_id="tenant-a",
                project_id="project-tenant-b",
                title="cross",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(
            Run(
                id="cross-run",
                tenant_id="tenant-a",
                session_id="session-tenant-b",
                status="succeeded",
                request_id="cross-req",
                revision=0,
                lease_epoch=0,
                input_digest="",
                target_id="",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def _python(env_dir: Path) -> Path:
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


def test_w2_c01_installed_migration(postgres_url: str, tmp_path: Path):
    """upgrade_head from a wheel of HEAD creates and drops the business tables."""
    archive = tmp_path / "head.tar"
    archived = subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), "HEAD"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
        env=_clean_env(),
    )
    assert archived.returncode == 0, archived.stderr
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    with tarfile.open(archive) as bundle:
        if sys.version_info >= (3, 12):
            bundle.extractall(checkout, filter="data")
        else:
            bundle.extractall(checkout)
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(wheel_dir), str(checkout)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_clean_env(),
    )
    assert build.returncode == 0, build.stderr
    wheels = list(wheel_dir.glob("rxycode-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as bundle:
        metadata_name = next(name for name in bundle.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = bundle.read(metadata_name).decode("utf-8").casefold()
    for requirement in ("sqlalchemy", "alembic", "psycopg"):
        assert f"requires-dist: {requirement}" in metadata
    env_dir = tmp_path / "venv"
    venv.create(env_dir, with_pip=True, system_site_packages=False)
    python = _python(env_dir)
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_clean_env(),
    )
    assert install.returncode == 0, install.stderr
    runtime = subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "sqlalchemy>=2,<2.1",
            "alembic>=1.17,<2",
            "psycopg[binary]>=3.2,<4",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_clean_env(),
    )
    assert runtime.returncode == 0, runtime.stderr
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    probe = (
        "from pathlib import Path\n"
        "from rxycode_server.persistence.migrate import ALEMBIC_DIR, downgrade_base, upgrade_head\n"
        "import os\n"
        "import rxycode_server.persistence.migrate as migrate\n"
        "origin = Path(migrate.__file__).resolve()\n"
        "script = Path(ALEMBIC_DIR).resolve()\n"
        "from sqlalchemy import create_engine, inspect\n"
        "print(origin)\n"
        "print(script)\n"
        "url = os.environ['W2_C01_URL']\n"
        "upgrade_head(url)\n"
        "names = set(inspect(create_engine(url)).get_table_names())\n"
        "assert 'runs' in names and 'organizations' in names\n"
        "downgrade_base(url)\n"
        "assert 'runs' not in set(inspect(create_engine(url)).get_table_names())\n"
        "print('wheel-migrate-ok')\n"
    )
    env = _clean_env()
    env["W2_C01_URL"] = postgres_url
    run = subprocess.run(
        [str(python), "-c", probe],
        cwd=run_dir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert run.returncode == 0, run.stderr
    assert "wheel-migrate-ok" in run.stdout
    venv_root = str(env_dir.resolve()).casefold()
    repo_root = str(REPO.resolve()).casefold()
    origins = [
        line.strip()
        for line in run.stdout.splitlines()
        if line.strip() and line.strip() != "wheel-migrate-ok"
    ]
    assert len(origins) == 2
    for origin in origins:
        folded = origin.casefold()
        assert venv_root in folded
        assert repo_root not in folded
    engine = create_engine(postgres_url)
    assert "runs" not in set(inspect(engine).get_table_names())
