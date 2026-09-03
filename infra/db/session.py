from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


DATABASE_URL = os.getenv("RPA_HUB_DATABASE_URL", "sqlite:///./rpa_hub.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine_kwargs = {"connect_args": connect_args}
if DATABASE_URL == "sqlite:///:memory:":
    engine_kwargs["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from infra.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_runs_for_queue()
    _migrate_sqlite_runs_for_retry_and_worker()
    _migrate_sqlite_schedules_for_retry()
    _migrate_sqlite_alerts()
    Base.metadata.create_all(bind=engine)


def _migrate_sqlite_runs_for_queue() -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        sql = connection.scalar(text("select sql from sqlite_master where type='table' and name='runs'"))
        if not sql or "CANCELLED" in sql:
            return
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.execute(text("ALTER TABLE run_steps RENAME TO run_steps_old"))
        connection.execute(text("ALTER TABLE artifacts RENAME TO artifacts_old"))
        connection.execute(text("ALTER TABLE runs RENAME TO runs_old"))
        connection.execute(
            text(
                """
                CREATE TABLE runs (
                    id INTEGER NOT NULL,
                    robot_id INTEGER NOT NULL,
                    robot_version_id INTEGER NOT NULL,
                    status VARCHAR(40) DEFAULT 'QUEUED' NOT NULL,
                    inputs JSON NOT NULL,
                    headless BOOLEAN DEFAULT 0 NOT NULL,
                    worker_id INTEGER,
                    error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    started_at DATETIME,
                    finished_at DATETIME,
                    cancellation_requested_at DATETIME,
                    PRIMARY KEY (id),
                    CONSTRAINT ck_runs_status CHECK (status in ('QUEUED', 'RUNNING', 'SUCCESS', 'FAILED', 'CANCELLED')),
                    FOREIGN KEY(robot_id) REFERENCES robots (id),
                    FOREIGN KEY(robot_version_id) REFERENCES robot_versions (id),
                    FOREIGN KEY(worker_id) REFERENCES workers (id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO runs (
                    id, robot_id, robot_version_id, status, inputs, headless, worker_id,
                    error, created_at, started_at, finished_at, cancellation_requested_at
                )
                SELECT
                    id, robot_id, robot_version_id, status, inputs, 0, NULL,
                    error, created_at, started_at, finished_at, NULL
                FROM runs_old
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE run_steps (
                    id INTEGER NOT NULL,
                    run_id INTEGER NOT NULL,
                    level VARCHAR(20) DEFAULT 'INFO' NOT NULL,
                    message TEXT NOT NULL,
                    data JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    PRIMARY KEY (id),
                    FOREIGN KEY(run_id) REFERENCES runs (id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO run_steps (id, run_id, level, message, data, created_at)
                SELECT id, run_id, level, message, data, created_at FROM run_steps_old
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE artifacts (
                    id INTEGER NOT NULL,
                    run_id INTEGER NOT NULL,
                    path VARCHAR(1000) NOT NULL,
                    kind VARCHAR(80) DEFAULT 'file' NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    PRIMARY KEY (id),
                    FOREIGN KEY(run_id) REFERENCES runs (id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO artifacts (id, run_id, path, kind, created_at)
                SELECT id, run_id, path, kind, created_at FROM artifacts_old
                """
            )
        )
        connection.execute(text("DROP TABLE run_steps_old"))
        connection.execute(text("DROP TABLE artifacts_old"))
        connection.execute(text("DROP TABLE runs_old"))
        connection.execute(text("PRAGMA foreign_keys=ON"))


def _migrate_sqlite_runs_for_retry_and_worker() -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        table_exists = connection.scalar(text("select 1 from sqlite_master where type='table' and name='runs'"))
        if not table_exists:
            return
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(runs)"))}
        if "worker_name" not in columns:
            connection.execute(text("ALTER TABLE runs ADD COLUMN worker_name VARCHAR(160)"))
        if "machine_id" not in columns:
            connection.execute(text("ALTER TABLE runs ADD COLUMN machine_id VARCHAR(220)"))
        if "retry_count" not in columns:
            connection.execute(text("ALTER TABLE runs ADD COLUMN retry_count INTEGER DEFAULT 0 NOT NULL"))
        if "max_retries" not in columns:
            connection.execute(text("ALTER TABLE runs ADD COLUMN max_retries INTEGER DEFAULT 0 NOT NULL"))


def _migrate_sqlite_schedules_for_retry() -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        table_exists = connection.scalar(text("select 1 from sqlite_master where type='table' and name='schedules'"))
        if not table_exists:
            return
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(schedules)"))}
        if "max_retries" not in columns:
            connection.execute(text("ALTER TABLE schedules ADD COLUMN max_retries INTEGER DEFAULT 0 NOT NULL"))


def _migrate_sqlite_alerts() -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        table_exists = connection.scalar(text("select 1 from sqlite_master where type='table' and name='alerts'"))
        if table_exists:
            return
        connection.execute(
            text(
                """
                CREATE TABLE alerts (
                    id INTEGER NOT NULL,
                    robot_id INTEGER NOT NULL,
                    run_id INTEGER,
                    severity VARCHAR(40) DEFAULT 'error' NOT NULL,
                    status VARCHAR(40) DEFAULT 'open' NOT NULL,
                    title VARCHAR(220) NOT NULL,
                    message TEXT NOT NULL,
                    notification_status VARCHAR(40) DEFAULT 'pending' NOT NULL,
                    notification_error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    resolved_at DATETIME,
                    PRIMARY KEY (id),
                    FOREIGN KEY(robot_id) REFERENCES robots (id),
                    FOREIGN KEY(run_id) REFERENCES runs (id)
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX ix_alerts_status_created_at ON alerts (status, created_at)"))
        connection.execute(text("CREATE INDEX ix_alerts_robot_created_at ON alerts (robot_id, created_at)"))
