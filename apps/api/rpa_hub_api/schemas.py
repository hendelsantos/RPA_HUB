from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RobotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    start_url: str | None = None


class GuidedRobotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    template: str = "open_site"
    url: str
    username_label: str | None = None
    username_value: str | None = None
    password_label: str | None = None
    password_secret: str | None = None
    login_button_text: str | None = None
    menu_text: str | None = None
    start_date_label: str | None = None
    start_date_value: str | None = "{{ontem}}"
    end_date_label: str | None = None
    end_date_value: str | None = "{{ontem}}"
    search_button_text: str | None = None
    export_button_text: str | None = None
    filename: str | None = "relatorio_{{run_date}}.xlsx"


class RobotOut(BaseModel):
    id: int
    name: str
    description: str
    start_url: str | None
    status: str
    created_at: datetime
    latest_version_id: int | None = None


class RobotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    start_url: str | None = None
    status: str | None = None


class RobotImport(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    start_url: str | None = None
    workflow: dict[str, Any]


class RobotDelete(BaseModel):
    password: str = ""


class VersionOut(BaseModel):
    id: int
    robot_id: int
    version: int
    status: str
    workflow: dict[str, Any]
    created_at: datetime


class WorkflowUpdate(BaseModel):
    workflow: dict[str, Any]


class WorkflowValidationOut(BaseModel):
    valid: bool
    errors: list[str]


class RunCreate(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    headless: bool = False


class ArtifactOut(BaseModel):
    id: int
    path: str
    kind: str


class RunOut(BaseModel):
    id: int
    robot_id: int
    robot_version_id: int
    status: str
    inputs: dict[str, Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    logs: list[dict[str, Any]]
    artifacts: list[ArtifactOut]


class DashboardOut(BaseModel):
    robots_total: int
    robots_active: int
    runs_total: int
    runs_success: int
    runs_failed: int
    workers_online: int
    schedules_enabled: int
    recent_runs: list[RunOut]


class WorkerRegister(BaseModel):
    name: str
    machine_id: str
    tags: list[str] = Field(default_factory=list)
    max_concurrent_runs: int = 1


class WorkerHeartbeat(BaseModel):
    status: str = "online"


class WorkerOut(BaseModel):
    id: int
    name: str
    machine_id: str
    status: str
    tags: list[str]
    max_concurrent_runs: int
    last_heartbeat_at: datetime | None
    created_at: datetime


class SecretCreate(BaseModel):
    name: str
    value: str
    description: str = ""
    secret_type: str = "credential"


class SecretOut(BaseModel):
    id: int
    name: str
    description: str
    secret_type: str
    created_at: datetime
    updated_at: datetime | None


class RobotSecretAttach(BaseModel):
    secret_id: int
    alias: str = ""


class RobotSecretOut(BaseModel):
    id: int
    robot_id: int
    secret_id: int
    secret_name: str
    alias: str
    description: str
    secret_type: str
    created_at: datetime


class ScheduleCreate(BaseModel):
    robot_id: int
    name: str
    cron: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ScheduleToggle(BaseModel):
    enabled: bool


class ScheduleOut(BaseModel):
    id: int
    robot_id: int
    name: str
    cron: str
    inputs: dict[str, Any]
    enabled: bool
    created_at: datetime


class TeachEvent(BaseModel):
    type: str
    target: dict[str, Any] | None = None
    url: str | None = None
    value: str | None = None
    filename: str | None = None
    timeout_ms: int = 30000


class TeachFinish(BaseModel):
    events: list[TeachEvent]


class TeachRecord(BaseModel):
    url: str
    seconds: int = Field(default=60, ge=1, le=300)


class TeachStart(BaseModel):
    url: str


class TeachSessionOut(BaseModel):
    session_id: str
    status: str
    url: str
    events_count: int
    error: str | None = None
