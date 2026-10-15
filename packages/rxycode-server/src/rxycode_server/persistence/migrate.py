"""Run the web Alembic revision against a caller-supplied database URL."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


def _alembic_dir() -> Path:
    """Find env.py in the source tree or in the installed package."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "alembic"
        revision = candidate / "versions" / "001_web_base.py"
        if (candidate / "env.py").is_file() and revision.is_file():
            return candidate
    raise FileNotFoundError("web alembic directory is not next to rxycode_server")


ALEMBIC_DIR = _alembic_dir()


def _config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def upgrade_head(url: str) -> None:
    command.upgrade(_config(url), "head")


def downgrade_base(url: str) -> None:
    command.downgrade(_config(url), "base")
