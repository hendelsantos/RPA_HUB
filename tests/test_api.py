from __future__ import annotations

import os

os.environ["RPA_HUB_DATABASE_URL"] = "sqlite:///:memory:"

from fastapi.testclient import TestClient

from apps.api.rpa_hub_api.main import app
from rpa_core.variables import normalize_url


def test_create_robot_and_update_workflow():
    with TestClient(app) as client:
        create_response = client.post(
            "/robots",
            json={"name": "Robo Teste", "description": "Fluxo simples", "start_url": "https://example.com"},
        )

        assert create_response.status_code == 200
        robot = create_response.json()
        assert robot["name"] == "Robo Teste"
        assert robot["latest_version_id"]

        version_response = client.get(f"/robots/{robot['id']}/versions/latest")
        assert version_response.status_code == 200
        version = version_response.json()

        workflow = {
            "inputs": {},
            "steps": [
                {"type": "goto", "url": "https://example.com"},
                {"type": "screenshot", "name": "home"},
            ],
        }

        update_response = client.put(f"/robot-versions/{version['id']}", json={"workflow": workflow})

        assert update_response.status_code == 200
        assert update_response.json()["workflow"] == workflow


def test_operational_hub_endpoints():
    with TestClient(app) as client:
        robot = client.post("/robots", json={"name": "Robo Operacional"}).json()

        worker_response = client.post(
            "/workers/register",
            json={"name": "AUTO-01", "machine_id": "machine-01", "tags": ["windows", "excel"], "max_concurrent_runs": 1},
        )
        assert worker_response.status_code == 200
        assert worker_response.json()["status"] == "online"

        secret_response = client.post(
            "/secrets",
            json={"name": "portal.password", "value": "senha-super-secreta", "description": "Senha teste"},
        )
        assert secret_response.status_code == 200
        assert "value" not in secret_response.json()
        assert "encrypted_value" not in secret_response.json()

        schedule_response = client.post(
            "/schedules",
            json={"robot_id": robot["id"], "name": "Teste diario", "cron": "0 7 * * 1-5", "inputs": {}, "enabled": True},
        )
        assert schedule_response.status_code == 200
        assert schedule_response.json()["enabled"] is True

        dashboard_response = client.get("/dashboard")
        assert dashboard_response.status_code == 200
        dashboard = dashboard_response.json()
        assert dashboard["robots_total"] >= 1
        assert dashboard["workers_online"] >= 1
        assert dashboard["schedules_enabled"] >= 1


def test_publish_requires_valid_workflow():
    with TestClient(app) as client:
        robot = client.post("/robots", json={"name": "Robo Incompleto"}).json()
        version = client.get(f"/robots/{robot['id']}/versions/latest").json()

        validation = client.get(f"/robot-versions/{version['id']}/validate")
        assert validation.status_code == 200
        assert validation.json()["valid"] is False

        publish = client.post(f"/robot-versions/{version['id']}/publish")
        assert publish.status_code == 400


def test_normalize_url_adds_https():
    assert normalize_url("www.uol.com.br") == "https://www.uol.com.br"
    assert normalize_url("https://example.com") == "https://example.com"
