from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from infra.db.session import Base


class Robot(Base):
    __tablename__ = "robots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    start_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    versions: Mapped[list[RobotVersion]] = relationship(back_populates="robot", cascade="all, delete-orphan")


class RobotVersion(Base):
    __tablename__ = "robot_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int] = mapped_column(ForeignKey("robots.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    workflow: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    robot: Mapped[Robot] = relationship(back_populates="versions")


class Run(Base):
    __tablename__ = "runs"

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    level: Mapped[str] = mapped_column(String(20), default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped[Run] = relationship(back_populates="steps")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), default="file")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped[Run] = relationship(back_populates="artifacts")


class Worker(Base):
    __tablename__ = "workers"

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


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int] = mapped_column(ForeignKey("robots.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    cron: Mapped[str] = mapped_column(String(120), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(160), default="system")
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
