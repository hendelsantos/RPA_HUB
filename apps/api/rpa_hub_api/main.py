from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.rpa_hub_api.schemas import (
    DashboardOut,
    GuidedRobotCreate,
    RobotCreate,
    RobotOut,
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
from domain.robots import RobotRepository
from domain.runs import RunService
from domain.schedules import ScheduleRepository
from domain.secrets import SecretStore
from domain.workers import WorkerRepository
from infra.db import SessionLocal, init_db
from infra.db.models import AuditEvent, Robot, RobotVersion, Run, Schedule, Secret, Worker
from infra.scheduler import HubScheduler
from rpa_core.engine.validation import validate_workflow
from rpa_core.recorder import RecorderManager, record_browser_session
from rpa_core.variables import normalize_url


BASE_DIR = Path(__file__).resolve().parents[3]
ARTIFACTS_DIR = BASE_DIR / "infra" / "artifacts"
WEB_INDEX = BASE_DIR / "apps" / "web" / "src" / "index.html"

app = FastAPI(title="HUB RPA", version="0.1.0")
scheduler = HubScheduler(BASE_DIR, ARTIFACTS_DIR)
recorder_manager = RecorderManager()


@app.on_event("startup")
def startup() -> None:
    init_db()
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    scheduler.start()


@app.on_event("shutdown")
def shutdown() -> None:
    scheduler.shutdown()


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@app.get("/", response_class=HTMLResponse)
def web_app() -> str:
    return WEB_INDEX.read_text(encoding="utf-8")


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
    output = []
    for robot in robots:
        latest = repo.latest_version(robot.id)
        output.append(_robot_out(robot, latest.id if latest else None))
    return output


@app.get("/robots/{robot_id}", response_model=RobotOut)
def get_robot(robot_id: int, session: Session = Depends(get_session)):
    repo = RobotRepository(session)
    robot = repo.get_robot(robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    latest = repo.latest_version(robot.id)
    return _robot_out(robot, latest.id if latest else None)


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


@app.post("/robots/{robot_id}/versions", response_model=VersionOut)
def create_version(robot_id: int, payload: WorkflowUpdate | None = None, session: Session = Depends(get_session)):
    workflow = payload.workflow if payload else None
    version = RobotRepository(session).create_next_version(robot_id, workflow)
    if not version:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    audit(session, "version.created", "robot_version", version.id, {"robot_id": robot_id, "version": version.version})
    session.commit()
    return version


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
    errors = validate_workflow(version.workflow)
    return WorkflowValidationOut(valid=not errors, errors=errors)


@app.post("/robot-versions/{version_id}/publish", response_model=VersionOut)
def publish_version(version_id: int, session: Session = Depends(get_session)):
    existing = session.get(RobotVersion, version_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    errors = validate_workflow(existing.workflow)
    if errors:
        raise HTTPException(status_code=400, detail={"message": "Corrija o fluxo antes de publicar.", "errors": errors})
    version = RobotRepository(session).publish_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Versao nao encontrada.")
    audit(session, "version.published", "robot_version", version.id, {"robot_id": version.robot_id})
    session.commit()
    return version


@app.post("/robots/{robot_id}/run", response_model=RunOut)
def run_robot(robot_id: int, payload: RunCreate, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    service = RunService(session, BASE_DIR, ARTIFACTS_DIR)
    try:
        run = service.create_run(robot_id, payload.inputs)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit(session, "run.queued", "run", run.id, {"robot_id": robot_id})
    session.commit()
    background_tasks.add_task(_execute_run_background, run.id, payload.headless)
    return _run_out(run)


@app.get("/runs", response_model=list[RunOut])
def list_runs(limit: int = 50, session: Session = Depends(get_session)):
    return [_run_out(run) for run in RunService(session, BASE_DIR, ARTIFACTS_DIR).list_runs(limit)]


@app.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Execucao nao encontrada.")
    return _run_out(run)


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
    workflow = {"inputs": {}, "steps": recording.workflow_steps()}
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
    workflow = {"inputs": {}, "steps": events}
    version = RobotRepository(session).create_next_version(robot_id, workflow)
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


@app.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(session: Session = Depends(get_session)):
    return ScheduleRepository(session).list_schedules()


@app.post("/schedules", response_model=ScheduleOut)
def create_schedule(payload: ScheduleCreate, session: Session = Depends(get_session)):
    if RobotRepository(session).get_robot(payload.robot_id) is None:
        raise HTTPException(status_code=404, detail="Robo nao encontrado.")
    schedule = ScheduleRepository(session).create(payload.robot_id, payload.name, payload.cron, payload.inputs, payload.enabled)
    audit(session, "schedule.created", "schedule", schedule.id, {"robot_id": schedule.robot_id})
    session.commit()
    scheduler.reload()
    return schedule


@app.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
def toggle_schedule(schedule_id: int, payload: ScheduleToggle, session: Session = Depends(get_session)):
    schedule = ScheduleRepository(session).set_enabled(schedule_id, payload.enabled)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Agenda nao encontrada.")
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


def _execute_run_background(run_id: int, headless: bool) -> None:
    session = SessionLocal()
    try:
        RunService(session, BASE_DIR, ARTIFACTS_DIR).execute_run(run_id, headless)
    finally:
        session.close()


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


def _run_out(run: Run) -> RunOut:
    return RunOut(
        id=run.id,
        robot_id=run.robot_id,
        robot_version_id=run.robot_version_id,
        status=run.status,
        inputs=run.inputs,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        logs=[{"level": step.level, "message": step.message, "data": step.data, "created_at": step.created_at.isoformat()} for step in run.steps],
        artifacts=[artifact.path for artifact in run.artifacts],
    )


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


def _teach_session_out(recording) -> TeachSessionOut:
    return TeachSessionOut(
        session_id=recording.id,
        status=recording.status,
        url=recording.url,
        events_count=len(recording.events),
        error=recording.error,
    )
