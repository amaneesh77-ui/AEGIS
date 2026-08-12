"""Shared pytest fixtures for the AEGIS backend test suite."""

import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def tmp_data_dir(tmp_path_factory):
    """Redirect all data dirs to a temp location for tests."""
    base = tmp_path_factory.mktemp("aegis_test_data")
    import config
    config.DATA_DIR    = base
    config.DB_PATH      = base / "aegis_test.db"
    config.CHROMA_DIR   = base / "chroma"
    config.WHOOSH_DIR   = base / "whoosh"
    config.UPLOADS_DIR  = base / "uploads"
    config.MODELS_DIR   = base / "models"
    config.TRANSLATE_MODELS_DIR = config.MODELS_DIR / "translate"
    for d in [config.CHROMA_DIR, config.WHOOSH_DIR, config.UPLOADS_DIR, config.TRANSLATE_MODELS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    yield base
    shutil.rmtree(str(base), ignore_errors=True)


@pytest.fixture(scope="session")
def client(tmp_data_dir):
    from main import app
    from database import init_db
    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def collection_id(client):
    r = client.post("/api/collections", json={"name": "Test Collection", "description": "pytest"})
    assert r.status_code == 201
    return r.json()["id"]
