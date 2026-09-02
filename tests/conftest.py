from __future__ import annotations

import base64
import os


TEST_API_KEY = "test-api-key"
TEST_SECRET_KEY = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")

os.environ["RPA_HUB_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["RPA_HUB_API_KEY"] = TEST_API_KEY
os.environ["RPA_HUB_SECRET_KEY"] = TEST_SECRET_KEY

import pytest
from fastapi.testclient import TestClient

from apps.api.rpa_hub_api.main import app
from infra.db.session import SessionLocal


@pytest.fixture()
def client():
    with TestClient(app, headers={"X-API-Key": TEST_API_KEY}) as test_client:
        yield test_client


@pytest.fixture()
def anon_client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session():
    with SessionLocal() as session:
        yield session
        session.rollback()
