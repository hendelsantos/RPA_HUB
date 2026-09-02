from __future__ import annotations

from sqlalchemy import select

from domain.robots import RobotRepository
from domain.runs import RunService
from infra.db.models import AuditEvent
from infra.db.session import SessionLocal
from rpa_core.variables import normalize_url


def test_create_robot_and_update_workflow(client):
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

    with SessionLocal() as session:
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "robot.created",
                AuditEvent.entity_type == "robot",
                AuditEvent.entity_id == str(robot["id"]),
            )
        )
        assert event is not None


def test_operational_hub_endpoints(client):
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


def test_robot_secret_links_hide_values_and_reference_secret_name(client):
    robot = client.post("/robots", json={"name": "Robo com login"}).json()
    secret = client.post(
        "/secrets",
        json={"name": "portal_hmb.senha", "value": "senha-real", "description": "Senha do portal"},
    ).json()

    attach_response = client.post(
        f"/robots/{robot['id']}/secrets",
        json={"secret_id": secret["id"], "alias": "Senha principal"},
    )

    assert attach_response.status_code == 200
    linked = attach_response.json()
    assert linked["secret_name"] == "portal_hmb.senha"
    assert linked["alias"] == "Senha principal"
    assert "value" not in linked
    assert "encrypted_value" not in linked

    list_response = client.get(f"/robots/{robot['id']}/secrets")
    assert list_response.status_code == 200
    assert list_response.json()[0]["secret_name"] == "portal_hmb.senha"

    delete_response = client.delete(f"/robots/{robot['id']}/secrets/{linked['id']}")
    assert delete_response.status_code == 200
    assert client.get(f"/robots/{robot['id']}/secrets").json() == []


def test_reconfigure_robot_creates_new_draft_version(client):
    robot = client.post("/robots/demo").json()
    latest = client.get(f"/robots/{robot['id']}/versions/latest").json()

    response = client.post(f"/robots/{robot['id']}/reconfigure")

    assert response.status_code == 200
    reconfigured = response.json()
    assert reconfigured["version"] == latest["version"] + 1
    assert reconfigured["status"] == "draft"
    assert client.get(f"/robots/{robot['id']}").json()["status"] == "draft"


def test_delete_robot_without_optional_password(client, monkeypatch):
    from infra import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "delete_password", None)
    robot = client.post("/robots", json={"name": "Robo para excluir"}).json()

    deleted = client.request("DELETE", f"/robots/{robot['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert client.get(f"/robots/{robot['id']}").status_code == 404


def test_delete_robot_with_optional_password(client, monkeypatch):
    from infra import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "delete_password", "confirmar#123")
    robot = client.post("/robots", json={"name": "Robo protegido"}).json()

    forbidden = client.request("DELETE", f"/robots/{robot['id']}")
    assert forbidden.status_code == 403
    assert client.get(f"/robots/{robot['id']}").status_code == 200

    deleted = client.request("DELETE", f"/robots/{robot['id']}", json={"password": "confirmar#123"})
    assert deleted.status_code == 200
    assert client.get(f"/robots/{robot['id']}").status_code == 404


def test_publish_requires_valid_workflow(client):
    robot = client.post("/robots", json={"name": "Robo Incompleto"}).json()
    version = client.get(f"/robots/{robot['id']}/versions/latest").json()

    validation = client.get(f"/robot-versions/{version['id']}/validate")
    assert validation.status_code == 200
    assert validation.json()["valid"] is False

    publish = client.post(f"/robot-versions/{version['id']}/publish")
    assert publish.status_code == 400


def test_activate_robot_publishes_latest_valid_training(client):
    workflow = {
        "inputs": {},
        "steps": [
            {"type": "goto", "url": "https://example.com"},
            {"type": "screenshot", "name": "ativado"},
        ],
    }

    robot = client.post("/robots", json={"name": "Robo para ativar", "start_url": "https://example.com"}).json()
    version = client.post(f"/robots/{robot['id']}/versions", json={"workflow": workflow}).json()

    activate = client.post(f"/robots/{robot['id']}/activate")

    assert activate.status_code == 200
    assert activate.json()["id"] == version["id"]
    assert activate.json()["status"] == "published"
    assert client.get(f"/robots/{robot['id']}").json()["status"] == "active"


def test_local_automation_robot_does_not_require_start_url(client):
    workflow = {
        "inputs": {},
        "steps": [
            {"type": "file_create_folder", "path": "/tmp/rpa-hub-teste"},
            {"type": "file_write_text", "path": "/tmp/rpa-hub-teste/status.txt", "value": "ok", "overwrite": True},
        ],
    }

    robot_response = client.post("/robots", json={"name": "Robo local", "description": "Automacao sem site"})

    assert robot_response.status_code == 200
    robot = robot_response.json()
    assert robot["start_url"] is None

    version_response = client.post(f"/robots/{robot['id']}/versions", json={"workflow": workflow})
    assert version_response.status_code == 200

    activate = client.post(f"/robots/{robot['id']}/activate")
    assert activate.status_code == 200
    assert activate.json()["status"] == "published"


def test_run_executes_the_version_that_was_queued(monkeypatch, tmp_path):
    captured_workflows = []

    class FakeWorkflowExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, workflow, inputs, log):
            captured_workflows.append(workflow)
            log("INFO", "Fluxo fake executado.")
            return []

    monkeypatch.setattr("domain.runs.service.WorkflowExecutor", FakeWorkflowExecutor)

    with SessionLocal() as session:
        repo = RobotRepository(session)
        robot = repo.create_robot_with_workflow(
            name="Robo versionado",
            workflow={"inputs": {}, "steps": [{"type": "screenshot", "name": "v1"}]},
            publish=True,
        )
        session.commit()

        service = RunService(session, tmp_path, tmp_path / "artifacts")
        repo.create_next_version(robot.id, {"inputs": {}, "steps": [{"type": "screenshot", "name": "v2"}]})
        session.commit()

        run = service.create_run(robot.id, {})
        session.commit()

        service.execute_run(run.id, headless=True)

    assert captured_workflows == [{"inputs": {}, "steps": [{"type": "screenshot", "name": "v1"}]}]


def test_normalize_url_adds_https():
    assert normalize_url("www.uol.com.br") == "https://www.uol.com.br"
    assert normalize_url("https://example.com") == "https://example.com"
