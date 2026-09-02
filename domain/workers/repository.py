from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from infra.db.models import Worker
from infra.time import utc_now


class WorkerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_workers(self) -> list[Worker]:
        return list(self.session.scalars(select(Worker).order_by(Worker.name)))

    def register(self, name: str, machine_id: str, tags: list[str], max_concurrent_runs: int = 1) -> Worker:
        worker = self.session.scalar(select(Worker).where(Worker.machine_id == machine_id))
        if worker is None:
            worker = Worker(name=name, machine_id=machine_id)
            self.session.add(worker)
        worker.name = name
        worker.tags = tags
        worker.max_concurrent_runs = max_concurrent_runs
        worker.status = "online"
        worker.last_heartbeat_at = utc_now()
        self.session.flush()
        return worker

    def heartbeat(self, worker_id: int, status: str = "online") -> Worker | None:
        worker = self.session.get(Worker, worker_id)
        if worker is None:
            return None
        worker.status = status
        worker.last_heartbeat_at = utc_now()
        self.session.flush()
        return worker
