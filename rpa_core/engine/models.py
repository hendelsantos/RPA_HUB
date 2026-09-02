from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


StepType = Literal[
    "goto",
    "click",
    "fill",
    "secret_fill",
    "select",
    "press",
    "wait_for",
    "assert_text",
    "download",
    "screenshot",
    "delay",
    "file_create_folder",
    "file_copy",
    "file_move",
    "file_delete",
    "file_write_text",
    "file_read_text",
    "file_zip",
    "file_unzip",
    "command_run",
    "desktop_move",
    "desktop_click",
    "desktop_double_click",
    "desktop_drag",
    "desktop_type",
    "desktop_press",
    "desktop_hotkey",
    "desktop_screenshot",
    "desktop_wait",
]


class Target(BaseModel):
    role: str | None = None
    name: str | None = None
    label: str | None = None
    text: str | None = None
    css: str | None = None


class WorkflowStep(BaseModel):
    type: StepType
    target: Target | None = None
    url: str | None = None
    value: str | None = None
    filename: str | None = None
    name: str | None = None
    path: str | None = None
    source: str | None = None
    destination: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    output_name: str | None = None
    variable: str | None = None
    secret: str | None = None
    key: str | None = None
    keys: list[str] = Field(default_factory=list)
    x: int | None = None
    y: int | None = None
    button: str = "left"
    duration_ms: int = 0
    interval_ms: int = 0
    overwrite: bool = False
    timeout_ms: int = 30000
    retry: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[WorkflowStep]
