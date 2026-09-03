from __future__ import annotations

from sqlalchemy import select

from domain.robots import RobotRepository
from domain.runs import RunQueueDispatcher, RunService
from infra.db.models import Alert, Artifact, AuditEvent, RobotVersion, Run, RunStep
from infra.db.session import SessionLocal
from infra.time import utc_now
from rpa_core.engine.executor import WorkflowExecutionError
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


def test_secret_can_be_tested_without_exposing_value(client):
    secret = client.post(
        "/secrets",
        json={"name": "teste.conexao", "value": "valor-que-nao-vaza", "description": "Teste"},
    ).json()

    response = client.post(f"/secrets/{secret['id']}/test")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "valor-que-nao-vaza" not in str(response.json())


def test_robot_secret_alias_can_be_swapped_without_editing_workflow(client, monkeypatch, tmp_path):
    captured = []

    class SecretReadingExecutor:
        def __init__(self, *args, secret_resolver=None, **kwargs):
            self.secret_resolver = secret_resolver

        def run(self, workflow, inputs, log, should_cancel=None):
            captured.append(self.secret_resolver("senha.portal"))
            return []

    monkeypatch.setattr("domain.runs.service.WorkflowExecutor", SecretReadingExecutor)

    robot = client.post("/robots", json={"name": "Robo troca credencial"}).json()
    first_secret = client.post("/secrets", json={"name": "portal.antigo", "value": "antiga"}).json()
    second_secret = client.post("/secrets", json={"name": "portal.novo", "value": "nova"}).json()
    linked = client.post(
        f"/robots/{robot['id']}/secrets",
        json={"secret_id": first_secret["id"], "alias": "senha.portal"},
    ).json()

    workflow = {"inputs": {}, "steps": [{"type": "secret_fill", "target": {"label": "Senha"}, "secret": "senha.portal"}]}
    version = client.get(f"/robots/{robot['id']}/versions/latest").json()
    client.put(f"/robot-versions/{version['id']}", json={"workflow": workflow})
    client.post(f"/robots/{robot['id']}/activate")

    with SessionLocal() as session:
        service = RunService(session, tmp_path, tmp_path / "artifacts")
        run = service.create_run(robot["id"], {})
        session.commit()
        service.execute_run(run.id, headless=True)

    response = client.patch(
        f"/robots/{robot['id']}/secrets/{linked['id']}",
        json={"secret_id": second_secret["id"], "alias": "senha.portal"},
    )
    assert response.status_code == 200

    with SessionLocal() as session:
        service = RunService(session, tmp_path, tmp_path / "artifacts")
        run = service.create_run(robot["id"], {})
        session.commit()
        service.execute_run(run.id, headless=True)

    assert captured == ["antiga", "nova"]


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


def test_robot_panel_groups_operational_context(client):
    robot = client.post("/robots", json={"name": "Robo painel", "description": "Operacao central"}).json()
    secret = client.post("/secrets", json={"name": "painel.senha", "value": "valor"}).json()
    client.post(f"/robots/{robot['id']}/secrets", json={"secret_id": secret["id"], "alias": "senha.painel"})
    client.post(
        "/schedules",
        json={"robot_id": robot["id"], "name": "Painel diario", "cron": "0 8 * * *", "inputs": {}, "enabled": True},
    )

    with SessionLocal() as session:
        version = session.scalar(select(RobotVersion).where(RobotVersion.robot_id == robot["id"]))
        run = Run(robot_id=robot["id"], robot_version_id=version.id, status="SUCCESS", inputs={})
        session.add(run)
        session.flush()
        session.add(Artifact(run_id=run.id, path="infra/artifacts/painel/saida.xlsx", kind="xlsx"))
        session.commit()

    response = client.get(f"/robots/{robot['id']}/panel")

    assert response.status_code == 200
    panel = response.json()
    assert panel["robot"]["name"] == "Robo painel"
    assert panel["latest_version"]["robot_id"] == robot["id"]
    assert panel["latest_run"]["status"] == "SUCCESS"
    assert panel["schedules"][0]["name"] == "Painel diario"
    assert panel["secrets"][0]["alias"] == "senha.painel"
    assert panel["artifacts"][0]["path"] == "infra/artifacts/painel/saida.xlsx"


def test_monitoring_alerts_failures_and_resolves_after_success(client, monkeypatch, tmp_path):
    class BrokenWorkflowExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, workflow, inputs, log, should_cancel=None):
            raise RuntimeError("Sistema externo fora do ar")

    monkeypatch.setattr("domain.runs.service.WorkflowExecutor", BrokenWorkflowExecutor)

    with SessionLocal() as session:
        robot = RobotRepository(session).create_robot_with_workflow(
            name="Robo monitorado",
            workflow={"inputs": {}, "steps": [{"type": "goto", "url": "https://example.com"}]},
            publish=True,
        )
        session.commit()
        service = RunService(session, tmp_path, tmp_path / "artifacts")
        failed_run = service.create_run(robot.id, {})
        session.commit()
        failed = service.execute_run(failed_run.id, headless=True)
        robot_id = robot.id

    assert failed.status == "FAILED"

    monitoring = client.get("/monitoring")
    assert monitoring.status_code == 200
    payload = monitoring.json()
    assert payload["runs_24h"]["failed"] >= 1
    assert payload["average_duration_seconds"] is not None
    assert any(alert["robot_id"] == robot_id and alert["notification_status"] == "not_configured" for alert in payload["open_alerts"])
    assert any(item["robot_id"] == robot_id and item["open_alerts"] >= 1 for item in payload["robots_needing_attention"])
    assert "Resumo das ultimas 24h" in payload["daily_summary"]

    class HealthyWorkflowExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, workflow, inputs, log, should_cancel=None):
            log("INFO", "Fluxo recuperado.", {"status": "SUCCESS"})
            return []

    monkeypatch.setattr("domain.runs.service.WorkflowExecutor", HealthyWorkflowExecutor)

    with SessionLocal() as session:
        service = RunService(session, tmp_path, tmp_path / "artifacts")
        recovery_run = service.create_run(robot_id, {})
        session.commit()
        recovered = service.execute_run(recovery_run.id, headless=True)

        open_alert = session.scalar(select(Alert).where(Alert.robot_id == robot_id, Alert.status == "open"))

    assert recovered.status == "SUCCESS"
    assert open_alert is None


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


def test_queue_dispatcher_executes_queued_run(monkeypatch, tmp_path):
    class FakeWorkflowExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, workflow, inputs, log, should_cancel=None):
            log("INFO", "Executado pela fila.", {"status": "SUCCESS"})
            return []

    monkeypatch.setattr("domain.runs.service.WorkflowExecutor", FakeWorkflowExecutor)

    with SessionLocal() as session:
        robot = RobotRepository(session).create_robot_with_workflow(
            name="Robo em fila",
            workflow={"inputs": {}, "steps": [{"type": "screenshot", "name": "fila"}]},
            publish=True,
        )
        run = RunService(session, tmp_path, tmp_path / "artifacts").create_run(robot.id, {}, headless=True)
        session.commit()
        run_id = run.id

    dispatcher = RunQueueDispatcher(tmp_path, tmp_path / "artifacts", max_concurrent_runs=1, poll_interval_seconds=0.05)
    queued = dispatcher._next_queued_run()
    assert queued == (run_id, True)
    dispatcher._execute(run_id, True)

    with SessionLocal() as session:
        result = session.get(Run, run_id)
        assert result.status == "SUCCESS"
        assert result.headless is True
        assert result.worker_name
        assert result.machine_id


def test_failed_run_is_requeued_until_retry_limit(monkeypatch, tmp_path):
    attempts = {"count": 0}

    class FlakyWorkflowExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, workflow, inputs, log, should_cancel=None):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("Falha temporaria")
            log("INFO", "Tentativa recuperada.", {"status": "SUCCESS"})
            return []

    monkeypatch.setattr("domain.runs.service.WorkflowExecutor", FlakyWorkflowExecutor)

    with SessionLocal() as session:
        robot = RobotRepository(session).create_robot_with_workflow(
            name="Robo com retry",
            workflow={"inputs": {}, "steps": [{"type": "screenshot", "name": "retry"}]},
            publish=True,
        )
        run = RunService(session, tmp_path, tmp_path / "artifacts").create_run(robot.id, {}, max_retries=1)
        session.commit()
        run_id = run.id

        service = RunService(session, tmp_path, tmp_path / "artifacts")
        first = service.execute_run(run_id, headless=True)
        assert first.status == "QUEUED"
        assert first.retry_count == 1

        second = service.execute_run(run_id, headless=True)
        assert second.status == "SUCCESS"
        assert second.retry_count == 1

    assert attempts["count"] == 2


def test_queued_run_can_be_cancelled(tmp_path):
    with SessionLocal() as session:
        robot = RobotRepository(session).create_robot_with_workflow(
            name="Robo cancelavel",
            workflow={"inputs": {}, "steps": [{"type": "screenshot", "name": "cancelar"}]},
            publish=True,
        )
        service = RunService(session, tmp_path, tmp_path / "artifacts")
        run = service.create_run(robot.id, {})
        session.commit()

        result = service.cancel_run(run.id)

    assert result.status == "CANCELLED"
    assert result.finished_at is not None
    assert "cancelada" in result.error


def test_running_run_cancel_request_stops_before_next_step(tmp_path):
    with SessionLocal() as session:
        robot = RobotRepository(session).create_robot_with_workflow(
            name="Robo cancelado em execucao",
            workflow={"inputs": {}, "steps": [{"type": "file_write_text", "path": str(tmp_path / "nao.txt"), "value": "nao"}]},
            publish=True,
        )
        service = RunService(session, tmp_path, tmp_path / "artifacts")
        run = service.create_run(robot.id, {})
        run.cancellation_requested_at = utc_now()
        session.commit()

        result = service.execute_run(run.id, headless=True)

    assert result.status == "CANCELLED"
    assert not (tmp_path / "nao.txt").exists()


def test_recover_interrupted_running_runs(tmp_path):
    with SessionLocal() as session:
        robot = RobotRepository(session).create_robot_with_workflow(
            name="Robo travado",
            workflow={"inputs": {}, "steps": [{"type": "screenshot", "name": "travado"}]},
            publish=True,
        )
        run = Run(robot_id=robot.id, robot_version_id=robot.versions[0].id, status="RUNNING", inputs={})
        session.add(run)
        session.commit()

        recovered = RunService(session, tmp_path, tmp_path / "artifacts").recover_interrupted_runs()
        session.refresh(run)

    assert recovered == 1
    assert run.status == "FAILED"
    assert "recuperada" in run.error


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


def test_failed_workflow_persists_failure_evidence(monkeypatch, tmp_path):
    class BrokenWorkflowExecutor:
        def __init__(self, artifacts_dir, *args, **kwargs):
            self.artifacts_dir = artifacts_dir

        def run(self, workflow, inputs, log):
            evidence = self.artifacts_dir / "falha-passo-5.png"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text("print fake", encoding="utf-8")
            raise WorkflowExecutionError(
                "Passo 5 nao encontrou o texto 'Relatorios'. Troque o texto esperado pelo nome real da aba.",
                [evidence],
            )

    monkeypatch.setattr("domain.runs.service.WorkflowExecutor", BrokenWorkflowExecutor)

    with SessionLocal() as session:
        repo = RobotRepository(session)
        robot = repo.create_robot_with_workflow(
            name="Robo com evidencia de falha",
            workflow={"inputs": {}, "steps": [{"type": "wait_for", "target": {"text": "Relatorios"}}]},
            publish=True,
        )
        session.commit()

        service = RunService(session, tmp_path, tmp_path / "artifacts")
        run = service.create_run(robot.id, {})
        session.commit()

        result = service.execute_run(run.id, headless=True)

    assert result.status == "FAILED"
    assert "Passo 5 nao encontrou" in result.error

    with SessionLocal() as session:
        artifact = session.scalar(select(Artifact).where(Artifact.run_id == result.id))
        assert artifact is not None
        assert artifact.path.endswith("falha-passo-5.png")


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
