from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domain.secrets import SecretStore
from infra.db.models import Alert, Artifact, Robot, RobotSecret, RobotVersion, Run, Schedule
from infra.settings import settings
from rpa_core.engine.validation import validate_workflow


class RobotReadinessService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def build(self, robot: Robot, latest_version: RobotVersion | None) -> dict[str, Any]:
        workflow = latest_version.workflow if latest_version else {"inputs": {}, "steps": []}
        steps = workflow.get("steps") or []
        active_steps = [step for step in steps if not (step.get("meta") or {}).get("disabled")]
        validation_errors = validate_workflow(workflow, settings.max_step_timeout_ms) if latest_version else ["Robo sem versao."]
        required_secrets = self._required_secrets(active_steps)
        missing_secrets = self._missing_secrets(robot.id, required_secrets)
        success_runs = self.session.scalar(select(func.count(Run.id)).where(Run.robot_id == robot.id, Run.status == "SUCCESS")) or 0
        failed_runs = self.session.scalar(select(func.count(Run.id)).where(Run.robot_id == robot.id, Run.status == "FAILED")) or 0
        enabled_schedules = (
            self.session.scalar(select(func.count(Schedule.id)).where(Schedule.robot_id == robot.id, Schedule.enabled.is_(True))) or 0
        )
        artifacts = (
            self.session.scalar(select(func.count(Artifact.id)).join(Run).where(Run.robot_id == robot.id)) or 0
        )
        open_alerts = self.session.scalar(select(func.count(Alert.id)).where(Alert.robot_id == robot.id, Alert.status == "open")) or 0

        checks = [
            self._check("workflow", "Passos ativos", bool(active_steps), "Adicionar ou gravar os passos do robo."),
            self._check("validation", "Passos validos", not validation_errors, "Abrir o editor e corrigir os campos marcados."),
            self._check("published", "Versao ativa", robot.status == "active" or (latest_version is not None and latest_version.status == "published"), "Publicar a versao antes de operar."),
            self._check("credentials", "Credenciais seguras", not missing_secrets, self._credential_action(missing_secrets)),
            self._check("tested", "Teste com sucesso", success_runs > 0, "Executar um teste e confirmar sucesso nos logs."),
            self._check("evidence", "Evidencias geradas", artifacts > 0, "Adicionar print, download ou PDF de evidencia no fluxo."),
            self._check("schedule", "Agenda configurada", enabled_schedules > 0, "Criar uma agenda para rodar sem acompanhamento manual."),
            self._check("alerts", "Sem alerta aberto", open_alerts == 0, "Abrir Monitoramento e corrigir as falhas pendentes."),
        ]
        passed = sum(1 for check in checks if check["ok"])
        return {
            "score": round((passed / len(checks)) * 100),
            "ready": passed == len(checks),
            "checks": checks,
            "missing_secrets": missing_secrets,
            "validation_errors": validation_errors,
            "stats": {
                "active_steps": len(active_steps),
                "success_runs": success_runs,
                "failed_runs": failed_runs,
                "enabled_schedules": enabled_schedules,
                "artifacts": artifacts,
                "open_alerts": open_alerts,
            },
        }

    def _required_secrets(self, steps: list[dict[str, Any]]) -> list[str]:
        secrets: list[str] = []
        for step in steps:
            for key in ("secret", "password_secret"):
                value = step.get(key)
                if value and value not in secrets:
                    secrets.append(value)
        return secrets

    def _missing_secrets(self, robot_id: int, names: list[str]) -> list[str]:
        if not names:
            return []
        links = list(
            self.session.scalars(
                select(RobotSecret)
                .where(RobotSecret.robot_id == robot_id)
                .join(RobotSecret.secret)
            )
        )
        linked_names: set[str] = set()
        for link in links:
            if link.alias:
                linked_names.add(link.alias)
            linked_names.add(link.secret.name)
        secret_store = SecretStore(self.session)
        return [name for name in names if name not in linked_names and not secret_store.can_resolve(name)]

    def _check(self, code: str, label: str, ok: bool, action: str) -> dict[str, Any]:
        return {"code": code, "label": label, "ok": ok, "action": "" if ok else action}

    def _credential_action(self, missing_secrets: list[str]) -> str:
        if not missing_secrets:
            return ""
        return f"Cadastrar ou vincular credencial: {', '.join(missing_secrets)}."
