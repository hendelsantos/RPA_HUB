from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from infra.db.models import Schedule


class ScheduleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_schedules(self) -> list[Schedule]:
        return list(self.session.scalars(select(Schedule).order_by(Schedule.name)))

    def create(self, robot_id: int, name: str, cron: str, inputs: dict[str, Any], enabled: bool = True) -> Schedule:
        schedule = Schedule(robot_id=robot_id, name=name, cron=cron, inputs=inputs, enabled=enabled)
        self.session.add(schedule)
        self.session.commit()
        self.session.refresh(schedule)
        return schedule

    def set_enabled(self, schedule_id: int, enabled: bool) -> Schedule | None:
        schedule = self.session.get(Schedule, schedule_id)
        if schedule is None:
            return None
        schedule.enabled = enabled
        self.session.commit()
        self.session.refresh(schedule)
        return schedule
