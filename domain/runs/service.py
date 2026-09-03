from __future__ import annotations

import inspect
import platform
from pathlib import Path
import socket
from typing import Any

from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session, selectinload

from domain.monitoring import MonitoringService
from domain.robots import RobotRepository
from domain.secrets import SecretStore
from domain.workers import WorkerRepository
from infra.db.models import Artifact, RobotSecret, RobotVersion, Run, RunStep, Worker
from infra.settings import settings
from infra.time import utc_now
from rpa_core.engine import WorkflowExecutor
from rpa_core.engine.executor import WorkflowCancelledError, WorkflowExecutionError
from rpa_core.engine.sandbox import StepSandbox


class RunService:
    def __init__(self, session: Session, base_dir: Path, artifacts_dir: Path) -> None:
        self.session = session
        self.base_dir = base_dir
        self.artifacts_dir = artifacts_dir

    def list_runs(self, limit: int = 50, robot_id: int | None = None, status: str | None = None) -> list[Run]:
        stmt = select(Run).options(selectinload(Run.steps), selectinload(Run.artifacts))
        if robot_id is not None:
            stmt = stmt.where(Run.robot_id == robot_id)
        if status:
            stmt = stmt.where(Run.status == status.upper())
        stmt = stmt.order_by(desc(Run.created_at)).limit(limit)
        return list(self.session.scalars(stmt))

    def create_run(self, robot_id: int, inputs: dict[str, Any], headless: bool = False, max_retries: int = 0) -> Run:
        version = RobotRepository(self.session).latest_published_version(robot_id)
        if version is None:
            raise ValueError("Robo sem versao ativa. Ative um ensino antes de executar.")
        run = Run(
            robot_id=robot_id,
            robot_version_id=version.id,
            status="QUEUED",
            inputs=inputs,
            headless=headless,
            max_retries=min(max(max_retries, 0), 5),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def claim_next_queued_run(self, worker: Worker | None = None) -> Run | None:
        run = self.session.scalar(
            select(Run)
            .where(Run.status == "QUEUED", Run.cancellation_requested_at.is_(None))
            .order_by(asc(Run.created_at), asc(Run.id))
            .limit(1)
        )
        if run is None:
            return None
        run.status = "RUNNING"
        run.started_at = utc_now()
        run.error = None
        if worker is not None:
            run.worker_id = worker.id
            run.worker_name = worker.name
            run.machine_id = worker.machine_id
        self.session.commit()
        self.session.refresh(run)
        return run

    def cancel_run(self, run_id: int) -> Run:
        run = self.session.get(Run, run_id)
        if run is None:
            raise ValueError("Execucao nao encontrada.")
        if run.status in {"SUCCESS", "FAILED", "CANCELLED"}:
            raise ValueError("Esta execucao ja foi finalizada.")
        now = utc_now()
        run.cancellation_requested_at = now
        if run.status == "QUEUED":
            run.status = "CANCELLED"
            run.error = "Execucao cancelada antes de iniciar."
            run.finished_at = now
            self.session.add(RunStep(run_id=run.id, level="WARN", message=run.error, data={"status": "CANCELLED"}))
        else:
            run.error = "Cancelamento solicitado. O robo vai parar ao finalizar o passo atual."
            self.session.add(RunStep(run_id=run.id, level="WARN", message=run.error, data={"status": "CANCEL_REQUESTED"}))
        self.session.commit()
        self.session.refresh(run)
        return run

    def recover_interrupted_runs(self) -> int:
        runs = list(self.session.scalars(select(Run).where(Run.status == "RUNNING")))
        for run in runs:
            run.status = "FAILED"
            run.error = "Execucao interrompida antes de terminar. Ela foi recuperada na inicializacao do Hub."
            run.finished_at = utc_now()
            self.session.add(RunStep(run_id=run.id, level="ERROR", message=run.error, data={"status": "RECOVERED"}))
        self.session.commit()
        return len(runs)

    def queued_count(self) -> int:
        return self.session.scalar(select(func.count(Run.id)).where(Run.status == "QUEUED")) or 0

    def running_count(self) -> int:
        return self.session.scalar(select(func.count(Run.id)).where(Run.status == "RUNNING")) or 0

    def execute_run(self, run_id: int, headless: bool) -> Run:
        run = self.session.get(Run, run_id)
        if run is None:
            raise ValueError("Execucao nao encontrada.")
        if run.status == "CANCELLED":
            return run
        if run.status not in {"QUEUED", "RUNNING"}:
            return run
        version = self.session.get(RobotVersion, run.robot_version_id)
        if version is None:
            raise ValueError("Versao nao encontrada.")

        if run.cancellation_requested_at is not None:
            run.status = "CANCELLED"
            run.error = "Execucao cancelada antes de iniciar."
            run.finished_at = utc_now()
            self.session.commit()
            self.session.refresh(run)
            return run

        run.status = "RUNNING"
        run.started_at = run.started_at or utc_now()
        if run.worker_id is None:
            worker = self._local_worker()
            run.worker_id = worker.id
            run.worker_name = worker.name
            run.machine_id = worker.machine_id
        self.session.commit()

        run_dir = self.artifacts_dir / f"run-{run.id}"

        def log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
            self.session.add(RunStep(run_id=run.id, level=level, message=message, data=data))
            self.session.commit()

        def should_cancel() -> bool:
            return (
                self.session.scalar(select(Run.cancellation_requested_at).where(Run.id == run.id))
                is not None
            )

        try:
            secret_resolver = self._secret_resolver_for(run.robot_id)
            sandbox = StepSandbox(
                allowed_roots=settings.allowed_roots,
                allowed_commands=frozenset(settings.allowed_commands),
                max_step_timeout_ms=settings.max_step_timeout_ms,
            )
            executor = WorkflowExecutor(
                run_dir,
                headless=headless,
                secret_resolver=secret_resolver,
                sandbox=sandbox,
            )
            run_parameters = inspect.signature(executor.run).parameters
            run_kwargs = {"workflow": version.workflow, "inputs": run.inputs, "log": log}
            if "should_cancel" in run_parameters:
                run_kwargs["should_cancel"] = should_cancel
            artifacts = executor.run(**run_kwargs)
            for artifact in artifacts:
                path = str(artifact.relative_to(self.base_dir))
                self.session.add(Artifact(run_id=run.id, path=path, kind=artifact.suffix.lstrip(".") or "file"))
            run.status = "SUCCESS"
            MonitoringService(self.session).resolve_robot_alerts(run.robot_id)
        except WorkflowCancelledError as exc:
            run.status = "CANCELLED"
            run.error = str(exc)
            log("WARN", run.error, {"status": "CANCELLED"})
        except Exception as exc:
            run.status = "FAILED"
            run.error = self._friendly_error(exc)
            if isinstance(exc, WorkflowExecutionError):
                self._persist_artifacts(run.id, exc.artifacts)
            log("ERROR", run.error, None)
        finally:
            if run.status == "FAILED" and run.retry_count < run.max_retries and run.cancellation_requested_at is None:
                run.retry_count += 1
                run.status = "QUEUED"
                run.finished_at = None
                log(
                    "WARN",
                    f"Falha detectada. Reenfileirando tentativa {run.retry_count + 1} de {run.max_retries + 1}.",
                    {"status": "REQUEUED", "retry_count": run.retry_count, "max_retries": run.max_retries},
                )
            else:
                run.finished_at = utc_now()
                if run.status == "FAILED":
                    MonitoringService(self.session).create_failure_alert(run)
            self.session.commit()
            self.session.refresh(run)

        return run

    def _persist_artifacts(self, run_id: int, artifacts: list[Path]) -> None:
        for artifact in artifacts:
            if not artifact.exists():
                continue
            path = str(artifact.relative_to(self.base_dir))
            self.session.add(Artifact(run_id=run_id, path=path, kind=artifact.suffix.lstrip(".") or "file"))

    def _local_worker(self) -> Worker:
        hostname = socket.gethostname()
        return WorkerRepository(self.session).register(
            f"{hostname} (Hub local)",
            f"{hostname}-{platform.system()}-hub-local",
            [platform.system().lower(), "local", "hub"],
            1,
        )

    def _secret_resolver_for(self, robot_id: int):
        secret_store = SecretStore(self.session)
        links = list(
            self.session.scalars(
                select(RobotSecret)
                .where(RobotSecret.robot_id == robot_id)
                .join(RobotSecret.secret)
            )
        )
        aliases: dict[str, str] = {}
        for link in links:
            if link.alias:
                aliases[link.alias] = link.secret.name
            aliases[link.secret.name] = link.secret.name

        def resolve(name: str) -> str | None:
            linked_name = aliases.get(name, name)
            return secret_store.resolve(linked_name)

        return resolve

    def _friendly_error(self, exc: Exception) -> str:
        message = str(exc)
        if "Executable doesn't exist" in message and "playwright install" in message:
            return "Navegador do Playwright nao instalado. Rode no terminal: playwright install chromium"
        if "ERR_CERT_COMMON_NAME_INVALID" in message:
            return "O site abriu com certificado invalido. Confira se o endereco esta correto; por exemplo, google.com e diferente de goolge.com."
        if "net::ERR_NAME_NOT_RESOLVED" in message or "net::ERR_CONNECTION" in message:
            return "Nao foi possivel abrir o site. Confira o endereco e a conexao antes de executar novamente."
        if "Can't connect to display" in message or "Authorization required" in message:
            return (
                "Controle do PC nao esta disponivel nesta sessao. Abra o Hub pela mesma tela grafica do usuario "
                "ou configure DISPLAY/XAUTHORITY. Para sites, use os passos de navegador."
            )
        return message
