from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from infra.db.session import Base


class Robot(Base):
    __tablename__ = "robots"
    __table_args__ = (
        Index("ix_robots_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    start_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    versions: Mapped[list[RobotVersion]] = relationship(back_populates="robot", cascade="all, delete-orphan")
    secret_links: Mapped[list[RobotSecret]] = relationship(back_populates="robot", cascade="all, delete-orphan")


class RobotVersion(Base):
    __tablename__ = "robot_versions"
    __table_args__ = (
        UniqueConstraint("robot_id", "version", name="uq_robot_versions_robot_version"),
        CheckConstraint("status in ('draft', 'published', 'archived')", name="ck_robot_versions_status"),
        Index("ix_robot_versions_robot_status", "robot_id", "status"),
        Index("ix_robot_versions_robot_version", "robot_id", "version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int] = mapped_column(ForeignKey("robots.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    workflow: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    robot: Mapped[Robot] = relationship(back_populates="versions")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint("status in ('QUEUED', 'RUNNING', 'SUCCESS', 'FAILED')", name="ck_runs_status"),
        Index("ix_runs_created_at", "created_at"),
        Index("ix_runs_status_created_at", "status", "created_at"),
        Index("ix_runs_robot_created_at", "robot_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int] = mapped_column(ForeignKey("robots.id"), nullable=False)
    robot_version_id: Mapped[int] = mapped_column(ForeignKey("robot_versions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="QUEUED")
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    steps: Mapped[list[RunStep]] = relationship(back_populates="run", cascade="all, delete-orphan")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="run", cascade="all, delete-orphan")


class RunStep(Base):
    __tablename__ = "run_steps"
    __table_args__ = (
        Index("ix_run_steps_run_created_at", "run_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    level: Mapped[str] = mapped_column(String(20), default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped[Run] = relationship(back_populates="steps")


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), default="file")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped[Run] = relationship(back_populates="artifacts")


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (
        CheckConstraint("max_concurrent_runs > 0", name="ck_workers_max_concurrent_runs_positive"),
        Index("ix_workers_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    machine_id: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(40), default="online")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_concurrent_runs: Mapped[int] = mapped_column(Integer, default=1)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Secret(Base):
    __tablename__ = "secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    secret_type: Mapped[str] = mapped_column(String(60), default="credential")
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    robot_links: Mapped[list[RobotSecret]] = relationship(back_populates="secret", cascade="all, delete-orphan")


class RobotSecret(Base):
    __tablename__ = "robot_secrets"
    __table_args__ = (
        UniqueConstraint("robot_id", "secret_id", name="uq_robot_secrets_robot_secret"),
        Index("ix_robot_secrets_robot_id", "robot_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int] = mapped_column(ForeignKey("robots.id"), nullable=False)
    secret_id: Mapped[int] = mapped_column(ForeignKey("secrets.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    robot: Mapped[Robot] = relationship(back_populates="secret_links")
    secret: Mapped[Secret] = relationship(back_populates="robot_links")


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        Index("ix_schedules_enabled", "enabled"),
        Index("ix_schedules_robot_id", "robot_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int] = mapped_column(ForeignKey("robots.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    cron: Mapped[str] = mapped_column(String(120), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(160), default="system")
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
