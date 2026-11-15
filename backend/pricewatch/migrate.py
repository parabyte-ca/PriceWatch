"""Run Alembic migrations programmatically (used at startup and by update.sh)."""

from pathlib import Path

from alembic.config import Config

from alembic import command

from .config import get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url or get_settings().db_url)
    return cfg


def upgrade(url: str | None = None) -> None:
    command.upgrade(alembic_config(url), "head")


if __name__ == "__main__":
    get_settings().data_dir.mkdir(parents=True, exist_ok=True)
    upgrade()
    print("migrations applied")
