from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from domain.runs import RunService
from infra.db.models import Schedule
from infra.db.session import SessionLocal

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
except ModuleNotFoundError:
    BackgroundScheduler = None
    CronTrigger = None


class HubScheduler:
    def __init__(self, base_dir: Path, artifacts_dir: Path) -> None:
        self.base_dir = base_dir
        self.artifacts_dir = artifacts_dir
        self.scheduler = BackgroundScheduler(timezone="America/Sao_Paulo") if BackgroundScheduler else None

    def start(self) -> None:
        if self.scheduler is None:
            return
        if not self.scheduler.running:
            self.scheduler.start()
        self.reload()

    def shutdown(self) -> None:
        if self.scheduler is not None and self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def reload(self) -> None:
        if self.scheduler is None:
            return
        self.scheduler.remove_all_jobs()
        session = SessionLocal()
        try:
            schedules = session.scalars(select(Schedule).where(Schedule.enabled.is_(True)))
            for schedule in schedules:
                self.add_schedule(schedule.id, schedule.robot_id, schedule.cron, schedule.inputs)
        finally:
            session.close()

    def add_schedule(self, schedule_id: int, robot_id: int, cron: str, inputs: dict) -> None:
        if self.scheduler is None or CronTrigger is None:
            return
        trigger = CronTrigger.from_crontab(cron)
        self.scheduler.add_job(
            self._run_robot,
            trigger=trigger,
            id=f"schedule-{schedule_id}",
            replace_existing=True,
            kwargs={"robot_id": robot_id, "inputs": inputs},
        )

    def _run_robot(self, robot_id: int, inputs: dict) -> None:
        session = SessionLocal()
        try:
            service = RunService(session, self.base_dir, self.artifacts_dir)
            run = service.create_run(robot_id, inputs)
            service.execute_run(run.id, headless=True)
        finally:
            session.close()
