import os
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="pricewatch-test-")
os.environ.update({
    "PRICEWATCH_DATA_DIR": _TMP,
    "PRICEWATCH_AUTH_MODE": "none",
    "PRICEWATCH_SCHEDULER_ENABLED": "false",
    "PRICEWATCH_MIN_DOMAIN_INTERVAL": "0",
    "PRICEWATCH_DOMAIN_JITTER": "0",
    "PRICEWATCH_NOTIFY_URLS": "",
})

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    from pricewatch import db as dbmod
    from pricewatch.migrate import upgrade
    from pricewatch.services.retailers import seed_retailers

    url = f"sqlite:///{tmp_path / 'test.db'}"
    upgrade(url)
    dbmod.init_engine(url)
    session = dbmod.session_scope()
    seed_retailers(session)
    yield session
    session.close()


@pytest.fixture
def client(db_session, monkeypatch):
    from fastapi.testclient import TestClient

    from pricewatch import db as dbmod
    from pricewatch import main

    url = str(dbmod.get_engine().url)
    monkeypatch.setattr(main, "upgrade", lambda *a, **k: None)
    monkeypatch.setattr(main, "init_engine", lambda *a, **k: dbmod.init_engine(url))
    with TestClient(main.create_app()) as c:
        yield c
