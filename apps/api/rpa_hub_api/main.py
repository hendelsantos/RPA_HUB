from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from hmac import compare_digest
import json
from pathlib import Path
from typing import AsyncIterator

from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from apps.api.rpa_hub_api.auth import require_api_key
from apps.api.rpa_hub_api.schemas import (
    ArtifactOut,
    DashboardOut,
    GuidedRobotCreate,
    RobotCreate,
    RobotDelete,
    RobotImport,
    RobotOut,
    RobotPanelOut,
    RobotSecretAttach,
    RobotSecretOut,
    RobotSecretUpdate,
    RobotUpdate,
    RunCreate,
    RunOut,
    ScheduleCreate,
    ScheduleOut,
    ScheduleToggle,
    SecretCreate,
    SecretOut,
    TeachFinish,
    TeachRecord,
    TeachSessionOut,
    TeachStart,
    VersionOut,
    WorkerHeartbeat,
    WorkerOut,
    WorkerRegister,
    WorkflowUpdate,
    WorkflowValidationOut,
)
from domain.audit import audit
from domain.monitoring import MonitoringService
from domain.robots import RobotRepository
from domain.runs import RunQueueDispatcher, RunService
from domain.schedules import ScheduleRepository
from domain.secrets import SecretStore
from domain.workers import WorkerRepository
from infra.db import SessionLocal, init_db
from infra.db.models import Artifact, AuditEvent, Robot, RobotSecret, RobotVersion, Run, Schedule, Secret, Worker
from infra.scheduler import HubScheduler
from infra.settings import settings
from rpa_core.desktop.controller import desktop_environment_status
from rpa_core.engine.validation import validate_workflow
from rpa_core.recorder import RecorderManager, record_browser_session
from rpa_core.variables import normalize_url


BASE_DIR = Path(__file__).resolve().parents[3]
ARTIFACTS_DIR = BASE_DIR / "infra" / "artifacts"
WEB_INDEX = BASE_DIR / "apps" / "web" / "src" / "index.html"

dispatcher = RunQueueDispatcher(BASE_DIR, ARTIFACTS_DIR)
scheduler = HubScheduler(BASE_DIR, ARTIFACTS_DIR, dispatcher)
recorder_manager = RecorderManager()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    dispatcher.start()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()
        dispatcher.shutdown()


app = FastAPI(
    title="HUB RPA",
    version="0.2.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@app.get("/", response_class=HTMLResponse)
def web_app() -> str:
    return WEB_INDEX.read_text(encoding="utf-8")


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        session.execute(select(1))
    except Exception:
        return {"status": "degraded", "database": "error"}
    return {"status": "ok", "version": app.version}


@app.get("/environment")
def environment() -> dict[str, dict[str, str | bool]]:
    return {"desktop": desktop_environment_status()}


@app.post("/robots", response_model=RobotOut)
def create_robot(payload: RobotCreate, session: Session = Depends(get_session)):
    repo = RobotRepository(session)
    robot = repo.create_robot(payload.name, payload.description, payload.start_url)
    latest = repo.latest_version(robot.id)
    audit(session, "robot.created", "robot", robot.id, {"name": robot.name})
    session.commit()
    return _robot_out(robot, latest.id if latest else None)


@app.post("/robots/demo", response_model=RobotOut)
def create_demo_robot(session: Session = Depends(get_session)):
    workflow = {
        "inputs": {},
        "steps": [
            {"type": "goto", "url": "https://example.com"},
            {"type": "wait_for", "target": {"text": "Example Domain"}, "timeout_ms": 10000},
            {"type": "screenshot", "name": "teste-example-{{run_date}}"},
        ],
    }
    repo = RobotRepository(session)
    robot = repo.create_robot_with_workflow(
        name="Teste automatico - abrir site",
        description="Robo de exemplo que abre um site e tira uma evidencia.",
        start_url="https://example.com",
        workflow=workflow,
        publish=True,
    )
    latest = repo.latest_version(robot.id)
    audit(session, "robot.demo_created", "robot", robot.id, {"name": robot.name})
    session.commit()
    return _robot_out(robot, latest.id if latest else None)


@app.post("/robots/guided", response_model=RobotOut)
def create_guided_robot(payload: GuidedRobotCreate, session: Session = Depends(get_session)):
    workflow = _guided_workflow(payload)
    repo = RobotRepository(session)
    robot = repo.create_robot_with_workflow(
        name=payload.name,
        description=f"Criado pelo modo guiado: {payload.template}",
        start_url=payload.url,
        workflow=workflow,
        publish=False,
    )
    latest = repo.latest_version(robot.id)
    audit(session, "robot.guided_created", "robot", robot.id, {"template": payload.template})
    session.commit()
    return _robot_out(robot, latest.id if latest else None)


@app.get("/robots", response_model=list[RobotOut])
def list_robots(session: Session = Depends(get_session)):
    repo = RobotRepository(session)
    robots = repo.list_robots()
    latest_by_robot = repo.latest_versions()
    return [_robot_out(robot, latest_by_robot[robot.id].id if robot.id in latest_by_robot else None) for robot in robots]


@app.get("/robots/{robot_id}", response_model=RobotOut)
def get_robot(robot_id: int, session: Session = Depends(get_session)):
    repo = RobotRepository(session)
    robot = repo.get_robot(robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    latest = repo.latest_version(robot.id)
    return _robot_out(robot, latest.id if latest else None)


@app.get("/robots/{robot_id}/panel", response_model=RobotPanelOut)
def get_robot_panel(robot_id: int, session: Session = Depends(get_session)):
    repo = RobotRepository(session)
    robot = repo.get_robot(robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    latest = repo.latest_version(robot.id)
    runs = RunService(session, BASE_DIR, ARTIFACTS_DIR).list_runs(8, robot_id=robot.id)
    schedules = ScheduleRepository(session).list_schedules(robot_id=robot.id)
    secret_links = _robot_secret_links(session, robot.id)
    artifacts = list(
        session.scalars(
            select(Artifact)
            .join(Run)
            .where(Run.robot_id == robot.id)
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            .limit(20)
        )
    )
    return RobotPanelOut(
        robot=_robot_out(robot, latest.id if latest else None),
        latest_version=_version_out(latest) if latest else None,
        latest_run=_run_out(runs[0]) if runs else None,
        recent_runs=[_run_out(run) for run in runs],
        schedules=[_schedule_out(schedule) for schedule in schedules],
        secrets=[_robot_secret_out(link) for link in secret_links],
        artifacts=[_panel_artifact_out(artifact) for artifact in artifacts],
    )


@app.patch("/robots/{robot_id}", response_model=RobotOut)
def update_robot(robot_id: int, payload: RobotUpdate, session: Session = Depends(get_session)):
    repo = RobotRepository(session)
    robot = repo.update_robot(
        robot_id,
        name=payload.name,
        description=payload.description,
        start_url=payload.start_url,
        status=payload.status,
    )
    if not robot:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    latest = repo.latest_version(robot.id)
    audit(session, "robot.updated", "robot", robot.id, payload.model_dump(exclude_none=True))
    session.commit()
    return _robot_out(robot, latest.id if latest else None)


@app.post("/robots/{robot_id}/reconfigure", response_model=VersionOut)
def reconfigure_robot(robot_id: int, session: Session = Depends(get_session)):
    repo = RobotRepository(session)
    version = repo.reconfigure_robot(robot_id)
    if not version:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    audit(session, "robot.reconfigured", "robot", robot_id, {"version_id": version.id, "version": version.version})
    session.commit()
    return version


@app.delete("/robots/{robot_id}")
def delete_robot(robot_id: int, payload: RobotDelete | None = None, session: Session = Depends(get_session)):
    if settings.delete_password:
        provided = (payload.password if payload else "") or ""
        if not compare_digest(provided, settings.delete_password):
            raise HTTPException(status_code=403, detail="Senha de confirmacao incorreta para excluir o robo.")
    repo = RobotRepository(session)
    robot = repo.get_robot(robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    audit(session, "robot.deleted", "robot", robot_id, {"name": robot.name})
    repo.delete_robot(robot_id)
    session.commit()
    return {"ok": True}


@app.post("/robots/{robot_id}/versions", response_model=VersionOut)
def create_version(robot_id: int, payload: WorkflowUpdate | None = None, session: Session = Depends(get_session)):
    workflow = payload.workflow if payload else None
    version = RobotRepository(session).create_next_version(robot_id, workflow)
    if not version:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    audit(session, "version.created", "robot_version", version.id, {"robot_id": robot_id, "version": version.version})
    session.commit()
    return version


@app.post("/robots/{robot_id}/duplicate", response_model=RobotOut)
def duplicate_robot(robot_id: int, session: Session = Depends(get_session)):
    repo = RobotRepository(session)
    robot = repo.duplicate_robot(robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    latest = repo.latest_version(robot.id)
    audit(session, "robot.duplicated", "robot", robot.id, {"source_robot_id": robot_id, "name": robot.name})
    session.commit()
    return _robot_out(robot, latest.id if latest else None)


@app.get("/robots/{robot_id}/export")
def export_robot(robot_id: int, session: Session = Depends(get_session)):
    repo = RobotRepository(session)
    robot = repo.get_robot(robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    version = repo.latest_published_version(robot_id) or repo.latest_version(robot_id)
    payload = {
        "name": robot.name,
        "description": robot.description,
        "start_url": robot.start_url,
        "workflow": version.workflow if version else {"inputs": {}, "steps": []},
        "exported_from": f"HUB RPA {app.version}",
    }
    audit(session, "robot.exported", "robot", robot_id, {"version_id": version.id if version else None})
    session.commit()
    safe_name = "".join(char if char.isalnum() or char in "-_" else "-" for char in robot.name.lower()).strip("-")
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="robo-{safe_name or robot_id}.json"'},
    )


@app.post("/robots/import", response_model=RobotOut)
def import_robot(payload: RobotImport, session: Session = Depends(get_session)):
    errors = validate_workflow(payload.workflow, settings.max_step_timeout_ms)
    if errors:
        raise HTTPException(status_code=400, detail={"message": "Workflow do robo importado e invalido.", "errors": errors})
    name = payload.name
    suffix = 1
    if session.scalar(select(Robot.id).where(Robot.name == name)):
        name = f"{name} (importado)"
    while session.scalar(select(Robot.id).where(Robot.name == name)):
        suffix += 1
        name = f"{payload.name} (importado {suffix})"
    repo = RobotRepository(session)
    robot = repo.create_robot_with_workflow(
        name=name,
        workflow=payload.workflow,
        description=payload.description,
        start_url=payload.start_url,
        publish=False,
    )
    latest = repo.latest_version(robot.id)
    audit(session, "robot.imported", "robot", robot.id, {"name": robot.name})
    session.commit()
    return _robot_out(robot, latest.id if latest else None)


@app.get("/robots/{robot_id}/versions/latest", response_model=VersionOut)
def get_latest_version(robot_id: int, session: Session = Depends(get_session)):
    version = RobotRepository(session).latest_version(robot_id)
    if not version:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    return version


@app.put("/robot-versions/{version_id}", response_model=VersionOut)
def update_workflow(version_id: int, payload: WorkflowUpdate, session: Session = Depends(get_session)):
    version = RobotRepository(session).update_workflow(version_id, payload.workflow)
    if not version:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    audit(session, "workflow.updated", "robot_version", version.id, {"robot_id": version.robot_id})
    session.commit()
    return version


@app.get("/robot-versions/{version_id}/validate", response_model=WorkflowValidationOut)
def validate_robot_version(version_id: int, session: Session = Depends(get_session)):
    version = session.get(RobotVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    errors = validate_workflow(version.workflow, settings.max_step_timeout_ms)
    return WorkflowValidationOut(valid=not errors, errors=errors)


@app.post("/robot-versions/{version_id}/publish", response_model=VersionOut)
def publish_version(version_id: int, session: Session = Depends(get_session)):
    existing = session.get(RobotVersion, version_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    errors = validate_workflow(existing.workflow, settings.max_step_timeout_ms)
    if errors:
        raise HTTPException(status_code=400, detail={"message": "Corrija o fluxo antes de publicar.", "errors": errors})
    version = RobotRepository(session).publish_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    audit(session, "version.published", "robot_version", version.id, {"robot_id": version.robot_id})
    session.commit()
    return version


@app.post("/robots/{robot_id}/activate", response_model=VersionOut)
def activate_robot(robot_id: int, session: Session = Depends(get_session)):
    repo = RobotRepository(session)
    robot = repo.get_robot(robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    existing = repo.latest_version(robot_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    errors = validate_workflow(existing.workflow, settings.max_step_timeout_ms)
    if errors:
        raise HTTPException(status_code=400, detail={"message": "Este robo ainda nao tem um ensino valido para ativar.", "errors": errors})
    version = repo.publish_version(existing.id)
    if not version:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    audit(session, "robot.activated", "robot", robot.id, {"version_id": version.id, "version": version.version})
    session.commit()
    return version


@app.post("/robots/{robot_id}/run", response_model=RunOut)
def run_robot(robot_id: int, payload: RunCreate, session: Session = Depends(get_session)):
    service = RunService(session, BASE_DIR, ARTIFACTS_DIR)
    try:
        run = service.create_run(robot_id, payload.inputs, payload.headless, payload.max_retries)
    except ValueError as exc:
        status_code = 400 if "sem versao ativa" in str(exc) else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    audit(session, "run.queued", "run", run.id, {"robot_id": robot_id})
    session.commit()
    dispatcher.wake()
    return _run_out(run)


@app.post("/runs/{run_id}/cancel", response_model=RunOut)
def cancel_run(run_id: int, session: Session = Depends(get_session)):
    service = RunService(session, BASE_DIR, ARTIFACTS_DIR)
    try:
        run = service.cancel_run(run_id)
    except ValueError as exc:
        status_code = 404 if "nao encontrada" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    audit(session, "run.cancelled", "run", run.id, {"status": run.status})
    session.commit()
    dispatcher.wake()
    return _run_out(run)


@app.get("/runs", response_model=list[RunOut])
def list_runs(
    limit: int = 50,
    robot_id: int | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
):
    service = RunService(session, BASE_DIR, ARTIFACTS_DIR)
    return [_run_out(run) for run in service.list_runs(limit, robot_id=robot_id, status=status)]


@app.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id, options=(selectinload(Run.steps), selectinload(Run.artifacts)))
    if not run:
        raise HTTPException(status_code=404, detail="Execucao nao encontrada.")
    return _run_out(run)


@app.get("/artifacts/{artifact_id}")
def download_artifact(artifact_id: int, session: Session = Depends(get_session)) -> FileResponse:
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artefato nao encontrado.")
    path = (BASE_DIR / artifact.path).resolve()
    artifacts_root = ARTIFACTS_DIR.resolve()
    if artifacts_root not in path.parents:
        raise HTTPException(status_code=400, detail="Caminho de artefato invalido.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo de evidencia nao existe mais no disco.")
    return FileResponse(path, filename=path.name)


@app.post("/robots/{robot_id}/teach/finish", response_model=VersionOut)
def finish_teach(robot_id: int, payload: TeachFinish, session: Session = Depends(get_session)):
    steps = []
    for event in payload.events:
        step = event.model_dump(exclude_none=True)
        steps.append(step)
    workflow = {"inputs": {}, "steps": steps}
    version = RobotRepository(session).create_next_version(robot_id, workflow)
    if version is None:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    audit(session, "teach.finished", "robot_version", version.id, {"events": len(steps)})
    session.commit()
    return version


@app.post("/robots/{robot_id}/teach/start", response_model=TeachSessionOut)
def start_teach_session(robot_id: int, payload: TeachStart, session: Session = Depends(get_session)):
    if RobotRepository(session).get_robot(robot_id) is None:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    recording = recorder_manager.start(payload.url)
    audit(session, "teach.started", "robot", robot_id, {"session_id": recording.id, "url": payload.url})
    session.commit()
    return _teach_session_out(recording)


@app.get("/teach-sessions/{session_id}", response_model=TeachSessionOut)
def get_teach_session(session_id: str):
    recording = recorder_manager.get(session_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Sessao de gravacao nao encontrada.")
    return _teach_session_out(recording)


@app.post("/robots/{robot_id}/teach/stop/{session_id}", response_model=VersionOut)
def stop_teach_session(robot_id: int, session_id: str, session: Session = Depends(get_session)):
    recording = recorder_manager.stop(session_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Sessao de gravacao nao encontrada.")
    if recording.status == "failed":
        raise HTTPException(status_code=500, detail=recording.error or "Falha na gravacao.")
    workflow = recording.workflow()
    version = RobotRepository(session).create_next_version(robot_id, workflow)
    if version is None:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    audit(session, "teach.stopped", "robot_version", version.id, {"events": len(recording.events), "session_id": session_id})
    session.commit()
    return version


@app.post("/robots/{robot_id}/teach/record", response_model=VersionOut)
def record_teach_session(robot_id: int, payload: TeachRecord, session: Session = Depends(get_session)):
    if RobotRepository(session).get_robot(robot_id) is None:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    events = record_browser_session(payload.url, seconds=payload.seconds)
    version = RobotRepository(session).create_next_version(robot_id, events)
    if version is None:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    audit(session, "teach.recorded", "robot_version", version.id, {"events": len(events)})
    session.commit()
    return version


@app.get("/dashboard", response_model=DashboardOut)
def dashboard(session: Session = Depends(get_session)):
    runs = RunService(session, BASE_DIR, ARTIFACTS_DIR).list_runs(8)
    return DashboardOut(
        robots_total=session.scalar(select(func.count(Robot.id))) or 0,
        robots_active=session.scalar(select(func.count(Robot.id)).where(Robot.status == "active")) or 0,
        runs_total=session.scalar(select(func.count(Run.id))) or 0,
        runs_success=session.scalar(select(func.count(Run.id)).where(Run.status == "SUCCESS")) or 0,
        runs_failed=session.scalar(select(func.count(Run.id)).where(Run.status == "FAILED")) or 0,
        workers_online=session.scalar(select(func.count(Worker.id)).where(Worker.status == "online")) or 0,
        schedules_enabled=session.scalar(select(func.count(Schedule.id)).where(Schedule.enabled.is_(True))) or 0,
        recent_runs=[_run_out(run) for run in runs],
    )


@app.get("/monitoring")
def monitoring(session: Session = Depends(get_session)):
    return MonitoringService(session).summary()


@app.get("/workers", response_model=list[WorkerOut])
def list_workers(session: Session = Depends(get_session)):
    return WorkerRepository(session).list_workers()


@app.post("/workers/register", response_model=WorkerOut)
def register_worker(payload: WorkerRegister, session: Session = Depends(get_session)):
    worker = WorkerRepository(session).register(payload.name, payload.machine_id, payload.tags, payload.max_concurrent_runs)
    audit(session, "worker.registered", "worker", worker.id, {"machine_id": worker.machine_id})
    session.commit()
    return worker


@app.post("/workers/{worker_id}/heartbeat", response_model=WorkerOut)
def worker_heartbeat(worker_id: int, payload: WorkerHeartbeat, session: Session = Depends(get_session)):
    worker = WorkerRepository(session).heartbeat(worker_id, payload.status)
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker nao encontrado.")
    session.commit()
    return worker


@app.get("/secrets", response_model=list[SecretOut])
def list_secrets(session: Session = Depends(get_session)):
    return SecretStore(session).list()


@app.post("/secrets", response_model=SecretOut)
def create_secret(payload: SecretCreate, session: Session = Depends(get_session)):
    secret = SecretStore(session).create_or_update(payload.name, payload.value, payload.description, payload.secret_type)
    audit(session, "secret.saved", "secret", secret.id, {"name": secret.name})
    session.commit()
    return _secret_out(secret)


@app.post("/secrets/{secret_id}/test")
def test_secret(secret_id: int, session: Session = Depends(get_session)):
    secret = session.get(Secret, secret_id)
    if secret is None:
        raise HTTPException(status_code=404, detail="Credencial nao encontrada.")
    if not SecretStore(session).can_resolve(secret.name):
        raise HTTPException(status_code=400, detail="Nao foi possivel abrir esta credencial. Confira a chave de cifragem do Hub.")
    audit(session, "secret.tested", "secret", secret.id, {"name": secret.name, "ok": True})
    session.commit()
    return {"ok": True, "message": "Credencial pronta para uso."}


@app.get("/robots/{robot_id}/secrets", response_model=list[RobotSecretOut])
def list_robot_secrets(robot_id: int, session: Session = Depends(get_session)):
    if RobotRepository(session).get_robot(robot_id) is None:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    return [_robot_secret_out(link) for link in _robot_secret_links(session, robot_id)]


@app.post("/robots/{robot_id}/secrets", response_model=RobotSecretOut)
def attach_robot_secret(robot_id: int, payload: RobotSecretAttach, session: Session = Depends(get_session)):
    if RobotRepository(session).get_robot(robot_id) is None:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    secret = session.get(Secret, payload.secret_id)
    if secret is None:
        raise HTTPException(status_code=404, detail="Segredo nao encontrado.")
    link = session.scalar(select(RobotSecret).where(RobotSecret.robot_id == robot_id, RobotSecret.secret_id == secret.id))
    if link is None:
        link = RobotSecret(robot_id=robot_id, secret_id=secret.id)
        session.add(link)
    link.alias = payload.alias
    session.flush()
    audit(session, "robot_secret.attached", "robot", robot_id, {"secret_id": secret.id, "secret_name": secret.name})
    session.commit()
    return _robot_secret_out(link)


@app.patch("/robots/{robot_id}/secrets/{link_id}", response_model=RobotSecretOut)
def update_robot_secret(robot_id: int, link_id: int, payload: RobotSecretUpdate, session: Session = Depends(get_session)):
    link = session.get(RobotSecret, link_id)
    if link is None or link.robot_id != robot_id:
        raise HTTPException(status_code=404, detail="Credencial do robo nao encontrada.")
    if payload.secret_id is not None:
        secret = session.get(Secret, payload.secret_id)
        if secret is None:
            raise HTTPException(status_code=404, detail="Segredo nao encontrado.")
        existing = session.scalar(
            select(RobotSecret).where(
                RobotSecret.robot_id == robot_id,
                RobotSecret.secret_id == secret.id,
                RobotSecret.id != link.id,
            )
        )
        if existing is not None:
            session.delete(link)
            existing.alias = payload.alias if payload.alias is not None else existing.alias
            link = existing
        else:
            link.secret_id = secret.id
    if payload.alias is not None:
        link.alias = payload.alias
    session.flush()
    audit(session, "robot_secret.updated", "robot", robot_id, {"link_id": link.id, "secret_id": link.secret_id})
    session.commit()
    return _robot_secret_out(link)


@app.delete("/robots/{robot_id}/secrets/{link_id}")
def detach_robot_secret(robot_id: int, link_id: int, session: Session = Depends(get_session)):
    link = session.get(RobotSecret, link_id)
    if link is None or link.robot_id != robot_id:
        raise HTTPException(status_code=404, detail="Credencial do robo nao encontrada.")
    data = {"secret_id": link.secret_id}
    session.delete(link)
    audit(session, "robot_secret.detached", "robot", robot_id, data)
    session.commit()
    return {"ok": True}


@app.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(session: Session = Depends(get_session)):
    return ScheduleRepository(session).list_schedules()


@app.post("/schedules", response_model=ScheduleOut)
def create_schedule(payload: ScheduleCreate, session: Session = Depends(get_session)):
    if RobotRepository(session).get_robot(payload.robot_id) is None:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    try:
        CronTrigger.from_crontab(payload.cron)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Programacao cron invalida: {exc}") from exc
    schedule = ScheduleRepository(session).create(
        payload.robot_id,
        payload.name,
        payload.cron,
        payload.inputs,
        payload.max_retries,
        payload.enabled,
    )
    audit(session, "schedule.created", "schedule", schedule.id, {"robot_id": schedule.robot_id})
    session.commit()
    scheduler.reload()
    return schedule


@app.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
def toggle_schedule(schedule_id: int, payload: ScheduleToggle, session: Session = Depends(get_session)):
    schedule = ScheduleRepository(session).set_enabled(schedule_id, payload.enabled)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Agenda nao encontrada.")
    session.commit()
    scheduler.reload()
    return schedule


@app.get("/audit-events")
def list_audit_events(limit: int = 80, session: Session = Depends(get_session)):
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    events = session.scalars(stmt)
    return [
        {
            "id": event.id,
            "actor": event.actor,
            "action": event.action,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "data": event.data,
            "created_at": event.created_at,
        }
        for event in events
    ]
def _robot_out(robot, latest_version_id: int | None) -> RobotOut:
    return RobotOut(
        id=robot.id,
        name=robot.name,
        description=robot.description,
        start_url=robot.start_url,
        status=robot.status,
        created_at=robot.created_at,
        latest_version_id=latest_version_id,
    )


def _version_out(version: RobotVersion) -> VersionOut:
    return VersionOut(
        id=version.id,
        robot_id=version.robot_id,
        version=version.version,
        status=version.status,
        workflow=version.workflow,
        created_at=version.created_at,
    )


def _schedule_out(schedule: Schedule) -> ScheduleOut:
    return ScheduleOut(
        id=schedule.id,
        robot_id=schedule.robot_id,
        name=schedule.name,
        cron=schedule.cron,
        inputs=schedule.inputs,
        max_retries=schedule.max_retries,
        enabled=schedule.enabled,
        created_at=schedule.created_at,
    )


def _run_out(run: Run) -> RunOut:
    return RunOut(
        id=run.id,
        robot_id=run.robot_id,
        robot_version_id=run.robot_version_id,
        status=run.status,
        inputs=run.inputs,
        headless=run.headless,
        worker_id=run.worker_id,
        worker_name=run.worker_name,
        machine_id=run.machine_id,
        retry_count=run.retry_count,
        max_retries=run.max_retries,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        logs=[{"level": step.level, "message": step.message, "data": step.data, "created_at": step.created_at.isoformat()} for step in run.steps],
        artifacts=[ArtifactOut(id=artifact.id, path=artifact.path, kind=artifact.kind) for artifact in run.artifacts],
    )


def _panel_artifact_out(artifact: Artifact):
    return {
        "id": artifact.id,
        "path": artifact.path,
        "kind": artifact.kind,
        "run_id": artifact.run_id,
        "created_at": artifact.created_at,
    }


def _robot_secret_links(session: Session, robot_id: int) -> list[RobotSecret]:
    stmt = (
        select(RobotSecret)
        .where(RobotSecret.robot_id == robot_id)
        .join(RobotSecret.secret)
        .order_by(Secret.name)
    )
    return list(session.scalars(stmt))


def _guided_workflow(payload: GuidedRobotCreate) -> dict:
    steps: list[dict] = [{"type": "goto", "url": normalize_url(payload.url), "timeout_ms": 30000}]

    if payload.template in {"login", "download_excel", "dated_report"}:
        if payload.username_label and payload.username_value:
            steps.append(
                {
                    "type": "fill",
                    "target": {"label": payload.username_label},
                    "value": payload.username_value,
                    "timeout_ms": 30000,
                }
            )
        if payload.password_label and payload.password_secret:
            steps.append(
                {
                    "type": "secret_fill",
                    "target": {"label": payload.password_label},
                    "secret": payload.password_secret,
                    "timeout_ms": 30000,
                }
            )
        if payload.login_button_text:
            steps.append(
                {
                    "type": "click",
                    "target": {"role": "button", "name": payload.login_button_text},
                    "timeout_ms": 30000,
                }
            )

    if payload.template in {"download_excel", "dated_report"}:
        if payload.menu_text:
            steps.append({"type": "click", "target": {"text": payload.menu_text}, "timeout_ms": 30000})

    if payload.template == "dated_report":
        if payload.start_date_label:
            steps.append(
                {
                    "type": "fill",
                    "target": {"label": payload.start_date_label},
                    "value": payload.start_date_value or "{{ontem}}",
                    "timeout_ms": 30000,
                }
            )
        if payload.end_date_label:
            steps.append(
                {
                    "type": "fill",
                    "target": {"label": payload.end_date_label},
                    "value": payload.end_date_value or "{{ontem}}",
                    "timeout_ms": 30000,
                }
            )
        if payload.search_button_text:
            steps.append(
                {
                    "type": "click",
                    "target": {"role": "button", "name": payload.search_button_text},
                    "timeout_ms": 30000,
                }
            )

    if payload.template in {"download_excel", "dated_report"} and payload.export_button_text:
        steps.append(
            {
                "type": "download",
                "target": {"text": payload.export_button_text},
                "filename": payload.filename or "relatorio_{{run_date}}.xlsx",
                "timeout_ms": 30000,
            }
        )
    else:
        steps.append({"type": "screenshot", "name": "evidencia-{{run_date}}", "timeout_ms": 30000})

    return {"inputs": {}, "steps": steps}


def _secret_out(secret: Secret) -> SecretOut:
    return SecretOut(
        id=secret.id,
        name=secret.name,
        description=secret.description,
        secret_type=secret.secret_type,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


def _robot_secret_out(link: RobotSecret) -> RobotSecretOut:
    return RobotSecretOut(
        id=link.id,
        robot_id=link.robot_id,
        secret_id=link.secret_id,
        secret_name=link.secret.name,
        alias=link.alias,
        description=link.secret.description,
        secret_type=link.secret.secret_type,
        created_at=link.created_at,
    )


def _teach_session_out(recording) -> TeachSessionOut:
    return TeachSessionOut(
        session_id=recording.id,
        status=recording.status,
        url=recording.url,
        events_count=len(recording.events),
        error=recording.error,
    )
