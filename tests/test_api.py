from __future__ import annotations

from sqlalchemy import select

from domain.robots import RobotRepository
from domain.runs import RunService
from infra.db.models import Artifact, AuditEvent, RobotVersion, Run, RunStep
from infra.db.session import SessionLocal
from rpa_core.variables import normalize_url, suggest_url_correction


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


def test_duplicate_export_and_import_robot(client):
    workflow = {
        "inputs": {"cliente": "HMB"},
        "steps": [{"type": "file_create_folder", "path": "/tmp/{{cliente}}"}],
    }
    robot = client.post("/robots", json={"name": "Robo biblioteca", "description": "Original"}).json()
    version = client.get(f"/robots/{robot['id']}/versions/latest").json()
    client.put(f"/robot-versions/{version['id']}", json={"workflow": workflow})
    client.post(f"/robots/{robot['id']}/activate")

    duplicate = client.post(f"/robots/{robot['id']}/duplicate")
    assert duplicate.status_code == 200
    copied = duplicate.json()
    assert copied["name"] == "Robo biblioteca (copia)"
    assert copied["status"] == "active"

    exported = client.get(f"/robots/{robot['id']}/export")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    payload = exported.json()
    assert payload["name"] == "Robo biblioteca"
    assert payload["workflow"] == workflow

    imported = client.post("/robots/import", json=payload)
    assert imported.status_code == 200
    assert imported.json()["name"] == "Robo biblioteca (importado)"

    imported_again = client.post("/robots/import", json=payload)
    assert imported_again.status_code == 200
    assert imported_again.json()["name"] == "Robo biblioteca (importado 2)"


def test_import_rejects_invalid_workflow(client):
    response = client.post(
        "/robots/import",
        json={"name": "Import invalido", "workflow": {"inputs": {}, "steps": [{"type": "goto"}]}},
    )

    assert response.status_code == 400
    assert "Workflow do robo importado e invalido" in response.json()["detail"]["message"]


def test_runs_can_be_filtered_and_include_artifact_objects(client):
    robot_a = client.post("/robots", json={"name": "Robo filtro A"}).json()
    robot_b = client.post("/robots", json={"name": "Robo filtro B"}).json()

    with SessionLocal() as session:
        version_a = session.scalar(select(RobotVersion).where(RobotVersion.robot_id == robot_a["id"]))
        version_b = session.scalar(select(RobotVersion).where(RobotVersion.robot_id == robot_b["id"]))
        run_a = Run(robot_id=robot_a["id"], robot_version_id=version_a.id, status="SUCCESS", inputs={})
        run_b = Run(robot_id=robot_b["id"], robot_version_id=version_b.id, status="FAILED", inputs={})
        session.add_all([run_a, run_b])
        session.flush()
        session.add(RunStep(run_id=run_a.id, level="INFO", message="ok", data={"status": "SUCCESS"}))
        session.add(Artifact(run_id=run_a.id, path="infra/artifacts/run-filter/saida.txt", kind="txt"))
        session.commit()

    filtered = client.get(f"/runs?robot_id={robot_a['id']}&status=success")

    assert filtered.status_code == 200
    runs = filtered.json()
    assert len(runs) == 1
    assert runs[0]["robot_id"] == robot_a["id"]
    assert runs[0]["status"] == "SUCCESS"
    assert runs[0]["logs"][0]["message"] == "ok"
    assert runs[0]["artifacts"][0]["path"] == "infra/artifacts/run-filter/saida.txt"
    assert "id" in runs[0]["artifacts"][0]


def test_download_artifact_returns_file(client, monkeypatch, tmp_path):
    from apps.api.rpa_hub_api import main as api_main

    artifacts_dir = tmp_path / "artifacts"
    run_dir = artifacts_dir / "run-1"
    run_dir.mkdir(parents=True)
    artifact_file = run_dir / "evidencia.txt"
    artifact_file.write_text("conteudo", encoding="utf-8")

    monkeypatch.setattr(api_main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(api_main, "ARTIFACTS_DIR", artifacts_dir)

    robot = client.post("/robots", json={"name": "Robo artefato"}).json()
    with SessionLocal() as session:
        version = session.scalar(select(RobotVersion).where(RobotVersion.robot_id == robot["id"]))
        run = Run(robot_id=robot["id"], robot_version_id=version.id, status="SUCCESS", inputs={})
        session.add(run)
        session.flush()
        artifact = Artifact(run_id=run.id, path="artifacts/run-1/evidencia.txt", kind="txt")
        session.add(artifact)
        session.commit()
        artifact_id = artifact.id

    response = client.get(f"/artifacts/{artifact_id}")

    assert response.status_code == 200
    assert response.content == b"conteudo"


def test_create_schedule_rejects_invalid_cron(client):
    robot = client.post("/robots", json={"name": "Robo cron invalido"}).json()

    response = client.post(
        "/schedules",
        json={"robot_id": robot["id"], "name": "Cron ruim", "cron": "cron ruim", "inputs": {}, "enabled": True},
    )

    assert response.status_code == 422
    assert "Programacao cron invalida" in response.json()["detail"]


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


def test_desktop_display_error_is_friendly(monkeypatch, tmp_path):
    class BrokenWorkflowExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, workflow, inputs, log):
            raise RuntimeError("Can't connect to display ':0': b'Authorization required'")

    monkeypatch.setattr("domain.runs.service.WorkflowExecutor", BrokenWorkflowExecutor)

    with SessionLocal() as session:
        repo = RobotRepository(session)
        robot = repo.create_robot_with_workflow(
            name="Robo desktop sem display",
            workflow={"inputs": {}, "steps": [{"type": "desktop_hotkey", "keys": ["win", "r"]}]},
            publish=True,
        )
        session.commit()

        service = RunService(session, tmp_path, tmp_path / "artifacts")
        run = service.create_run(robot.id, {})
        session.commit()

        result = service.execute_run(run.id, headless=True)

    assert result.status == "FAILED"
    assert "Controle do PC nao esta disponivel" in result.error


def test_navigation_certificate_error_is_friendly(monkeypatch, tmp_path):
    class BrokenWorkflowExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, workflow, inputs, log):
            raise RuntimeError("Page.goto: net::ERR_CERT_COMMON_NAME_INVALID at https://www.goolge.com/")

    monkeypatch.setattr("domain.runs.service.WorkflowExecutor", BrokenWorkflowExecutor)

    with SessionLocal() as session:
        repo = RobotRepository(session)
        robot = repo.create_robot_with_workflow(
            name="Robo site errado",
            workflow={"inputs": {}, "steps": [{"type": "goto", "url": "https://www.goolge.com/"}]},
            publish=True,
        )
        session.commit()

        service = RunService(session, tmp_path, tmp_path / "artifacts")
        run = service.create_run(robot.id, {})
        session.commit()

        result = service.execute_run(run.id, headless=True)

    assert result.status == "FAILED"
    assert "Confira se o endereco esta correto" in result.error
    assert "google.com" in result.error


def test_normalize_url_adds_https():
    assert normalize_url("www.uol.com.br") == "https://www.uol.com.br"
    assert normalize_url(" www.uol.com.br ") == "https://www.uol.com.br"
    assert normalize_url("https://example.com") == "https://example.com"


def test_suggest_url_correction_for_common_typos():
    assert suggest_url_correction("www.goolge.com") == "https://www.google.com"
    assert suggest_url_correction("https://www.gmial.com/login") == "https://www.gmail.com/login"
    assert suggest_url_correction("https://example.com") is None
