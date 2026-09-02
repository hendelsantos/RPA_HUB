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
    secret: str | None = None
    key: str | None = None
    timeout_ms: int = 30000
    retry: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[WorkflowStep]
