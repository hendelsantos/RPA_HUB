from __future__ import annotations

from collections import Counter
from datetime import timedelta
from email.message import EmailMessage
import smtplib
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from domain.secrets import SecretStore
from infra.db.models import Alert, Robot, Run, Worker
from infra.settings import Settings, settings
from infra.time import utc_now


class MonitoringService:
    def __init__(self, session: Session, app_settings: Settings = settings) -> None:
        self.session = session
        self.settings = app_settings

    def create_failure_alert(self, run: Run) -> Alert:
        robot_name = self.session.scalar(select(Robot.name).where(Robot.id == run.robot_id)) or f"Robo {run.robot_id}"
        alert = Alert(
            robot_id=run.robot_id,
            run_id=run.id,
            severity="error",
            status="open",
            title=f"Falha no robo {robot_name}",
            message=run.error or "Execucao falhou sem mensagem detalhada.",
            notification_status="pending",
        )
        self.session.add(alert)
        self.session.flush()
        self._notify_alert(alert)
        return alert

    def resolve_robot_alerts(self, robot_id: int) -> int:
        alerts = list(self.session.scalars(select(Alert).where(Alert.robot_id == robot_id, Alert.status == "open")))
        now = utc_now()
        for alert in alerts:
            alert.status = "resolved"
            alert.resolved_at = now
        self.session.flush()
        return len(alerts)

    def summary(self) -> dict[str, Any]:
        now = utc_now()
        since_24h = now - timedelta(days=1)
        runs_24h = list(self.session.scalars(select(Run).where(Run.created_at >= since_24h).order_by(desc(Run.created_at))))
        counts = Counter(run.status for run in runs_24h)
        finished = [run for run in runs_24h if run.started_at and run.finished_at]
        average_seconds = None
        if finished:
            average_seconds = round(sum((run.finished_at - run.started_at).total_seconds() for run in finished) / len(finished), 1)
        success_rate = None
        complete = counts["SUCCESS"] + counts["FAILED"] + counts["CANCELLED"]
        if complete:
            success_rate = round((counts["SUCCESS"] / complete) * 100, 1)

        open_alerts = list(self.session.scalars(select(Alert).where(Alert.status == "open").order_by(desc(Alert.created_at)).limit(20)))
        recent_failures = list(self.session.scalars(select(Run).where(Run.status == "FAILED").order_by(desc(Run.created_at)).limit(10)))
        workers = list(self.session.scalars(select(Worker).order_by(desc(Worker.last_heartbeat_at))))
        return {
            "generated_at": now,
            "success_rate": success_rate,
            "average_duration_seconds": average_seconds,
            "runs_24h": {
                "total": len(runs_24h),
                "success": counts["SUCCESS"],
                "failed": counts["FAILED"],
                "cancelled": counts["CANCELLED"],
                "running": counts["RUNNING"],
                "queued": counts["QUEUED"],
            },
            "open_alerts": [self._alert_dict(alert) for alert in open_alerts],
            "recent_failures": [self._run_brief(run) for run in recent_failures],
            "robots_needing_attention": self._robots_needing_attention(),
            "workers": [self._worker_dict(worker, now) for worker in workers],
            "daily_summary": self._daily_summary(counts, success_rate, average_seconds, len(open_alerts)),
        }

    def _robots_needing_attention(self) -> list[dict[str, Any]]:
        rows = self.session.execute(
            select(Robot.id, Robot.name, func.count(Alert.id))
            .join(Alert, Alert.robot_id == Robot.id)
            .where(Alert.status == "open")
            .group_by(Robot.id, Robot.name)
            .order_by(desc(func.count(Alert.id)))
            .limit(10)
        )
        return [{"robot_id": robot_id, "name": name, "open_alerts": count} for robot_id, name, count in rows]

    def _notify_alert(self, alert: Alert) -> None:
        if not self.settings.alert_email_host or not self.settings.alert_email_to:
            alert.notification_status = "not_configured"
            return
        try:
            message = EmailMessage()
            message["From"] = self.settings.alert_email_from or self.settings.alert_email_to
            message["To"] = self.settings.alert_email_to
            message["Subject"] = alert.title
            message.set_content(f"{alert.message}\n\nRun: {alert.run_id}\nRobo: {alert.robot_id}")
            password = None
            if self.settings.alert_email_password_secret:
                password = SecretStore(self.session).resolve(self.settings.alert_email_password_secret)
            with smtplib.SMTP(self.settings.alert_email_host, self.settings.alert_email_port, timeout=20) as smtp:
                smtp.starttls()
                if self.settings.alert_email_username and password:
                    smtp.login(self.settings.alert_email_username, password)
                smtp.send_message(message)
            alert.notification_status = "sent"
            alert.notification_error = None
        except Exception as exc:
            alert.notification_status = "failed"
            alert.notification_error = str(exc)

    def _alert_dict(self, alert: Alert) -> dict[str, Any]:
        return {
            "id": alert.id,
            "robot_id": alert.robot_id,
            "run_id": alert.run_id,
            "severity": alert.severity,
            "status": alert.status,
            "title": alert.title,
            "message": alert.message,
            "notification_status": alert.notification_status,
            "notification_error": alert.notification_error,
            "created_at": alert.created_at,
            "resolved_at": alert.resolved_at,
        }

    def _run_brief(self, run: Run) -> dict[str, Any]:
        return {
            "id": run.id,
            "robot_id": run.robot_id,
            "status": run.status,
            "error": run.error,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "worker_name": run.worker_name,
            "machine_id": run.machine_id,
        }

    def _worker_dict(self, worker: Worker, now) -> dict[str, Any]:
        age_seconds = None
        if worker.last_heartbeat_at:
            age_seconds = round((now - worker.last_heartbeat_at).total_seconds())
        return {
            "id": worker.id,
            "name": worker.name,
            "machine_id": worker.machine_id,
            "status": worker.status,
            "last_heartbeat_at": worker.last_heartbeat_at,
            "heartbeat_age_seconds": age_seconds,
        }

    def _daily_summary(self, counts: Counter, success_rate: float | None, average_seconds: float | None, open_alerts: int) -> str:
        success_text = f"{success_rate}%" if success_rate is not None else "-"
        duration_text = f"{average_seconds}s" if average_seconds is not None else "-"
        return (
            f"Resumo das ultimas 24h: {counts['SUCCESS']} sucesso(s), {counts['FAILED']} falha(s), "
            f"{counts['CANCELLED']} cancelada(s), taxa de sucesso {success_text}, tempo medio {duration_text}, "
            f"{open_alerts} alerta(s) aberto(s)."
        )
