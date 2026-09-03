from __future__ import annotations

import threading
import platform
import socket
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from time import sleep

from domain.runs.service import RunService
from domain.workers import WorkerRepository
from infra.db.session import SessionLocal


class RunQueueDispatcher:
    def __init__(
        self,
        base_dir: Path,
        artifacts_dir: Path,
        max_concurrent_runs: int = 1,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.base_dir = base_dir
        self.artifacts_dir = artifacts_dir
        self.max_concurrent_runs = max(1, max_concurrent_runs)
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._active: dict[int, Future] = {}
        self._lock = threading.Lock()
        hostname = socket.gethostname()
        self.worker_name = f"{hostname} (Hub local)"
        self.machine_id = f"{hostname}-{platform.system()}-hub-local"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._executor = ThreadPoolExecutor(max_workers=self.max_concurrent_runs, thread_name_prefix="rpa-run")
        self._recover_interrupted_runs()
        self.dispatch_once()
        self._thread = threading.Thread(target=self._loop, name="rpa-run-dispatcher", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        with self._lock:
            self._active.clear()

    def wake(self) -> None:
        self._stop_event.wait(0.01)

    def active_count(self) -> int:
        with self._lock:
            self._cleanup_finished_locked()
            return len(self._active)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self.dispatch_once()
            sleep(self.poll_interval_seconds)

    def dispatch_once(self) -> None:
        if self._executor is None:
            return
        with self._lock:
            self._cleanup_finished_locked()
            available = self.max_concurrent_runs - len(self._active)
        for _ in range(available):
            queued = self._next_queued_run()
            if queued is None:
                return
            run_id, headless = queued
            future = self._executor.submit(self._execute, run_id, headless)
            with self._lock:
                self._active[run_id] = future

    def _next_queued_run(self) -> tuple[int, bool] | None:
        session = SessionLocal()
        try:
            worker = WorkerRepository(session).register(
                self.worker_name,
                self.machine_id,
                [platform.system().lower(), "local", "hub"],
                self.max_concurrent_runs,
            )
            run = RunService(session, self.base_dir, self.artifacts_dir).claim_next_queued_run(worker)
            if run is None:
                session.commit()
                return None
            return run.id, run.headless
        finally:
            session.close()

    def _execute(self, run_id: int, headless: bool) -> None:
        session = SessionLocal()
        try:
            RunService(session, self.base_dir, self.artifacts_dir).execute_run(run_id, headless)
        finally:
            session.close()

    def _recover_interrupted_runs(self) -> None:
        session = SessionLocal()
        try:
            RunService(session, self.base_dir, self.artifacts_dir).recover_interrupted_runs()
        finally:
            session.close()

    def _cleanup_finished_locked(self) -> None:
        finished = [run_id for run_id, future in self._active.items() if future.done()]
        for run_id in finished:
            self._active.pop(run_id, None)
