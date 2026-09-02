from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from domain.robots import RobotRepository
from domain.secrets import SecretStore
from infra.db.models import Artifact, RobotVersion, Run, RunStep
from infra.settings import settings
from infra.time import utc_now
from rpa_core.engine import WorkflowExecutor
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

    def create_run(self, robot_id: int, inputs: dict[str, Any]) -> Run:
        version = RobotRepository(self.session).latest_published_version(robot_id)
        if version is None:
            raise ValueError("Robo sem versao ativa. Ative um ensino antes de executar.")
        run = Run(robot_id=robot_id, robot_version_id=version.id, status="QUEUED", inputs=inputs)
        self.session.add(run)
        self.session.flush()
        return run

    def execute_run(self, run_id: int, headless: bool) -> Run:
        run = self.session.get(Run, run_id)
        if run is None:
            raise ValueError("Execucao nao encontrada.")
        version = self.session.get(RobotVersion, run.robot_version_id)
        if version is None:
            raise ValueError("Versao nao encontrada.")

        run.status = "RUNNING"
        run.started_at = utc_now()
        self.session.commit()

        run_dir = self.artifacts_dir / f"run-{run.id}"

        def log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
            self.session.add(RunStep(run_id=run.id, level=level, message=message, data=data))
            self.session.commit()

        try:
            secret_store = SecretStore(self.session)
            sandbox = StepSandbox(
                allowed_roots=settings.allowed_roots,
                allowed_commands=frozenset(settings.allowed_commands),
                max_step_timeout_ms=settings.max_step_timeout_ms,
            )
            artifacts = WorkflowExecutor(
                run_dir,
                headless=headless,
                secret_resolver=secret_store.resolve,
                sandbox=sandbox,
            ).run(
                version.workflow,
                inputs=run.inputs,
                log=log,
            )
            for artifact in artifacts:
                path = str(artifact.relative_to(self.base_dir))
                self.session.add(Artifact(run_id=run.id, path=path, kind=artifact.suffix.lstrip(".") or "file"))
            run.status = "SUCCESS"
        except Exception as exc:
            run.status = "FAILED"
            run.error = self._friendly_error(exc)
            log("ERROR", run.error, None)
        finally:
            run.finished_at = utc_now()
            self.session.commit()
            self.session.refresh(run)

        return run

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
