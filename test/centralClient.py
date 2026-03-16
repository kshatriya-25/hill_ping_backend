#OM VIGHNHARTAYE NAMO NAMAH:

from main import app
from app.database.session import getdb
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(db):
    app.dependency_overrides[getdb] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()