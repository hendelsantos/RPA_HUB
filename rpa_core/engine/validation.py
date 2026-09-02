from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rpa_core.engine.models import WorkflowDefinition


TARGET_STEPS = {"click", "fill", "secret_fill", "select", "press", "wait_for", "assert_text", "download"}
PATH_STEPS = {"file_create_folder", "file_delete", "file_write_text"}
SOURCE_DESTINATION_STEPS = {"file_copy", "file_move"}


def validate_workflow(workflow_data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        workflow = WorkflowDefinition.model_validate(workflow_data)
    except ValidationError as exc:
        return [f"Workflow invalido: {error['msg']}" for error in exc.errors()]

    if not workflow.steps:
        errors.append("O robo nao possui passos.")

    for index, step in enumerate(workflow.steps, start=1):
        prefix = f"Passo {index} ({step.type})"
        if step.type == "goto" and not step.url:
            errors.append(f"{prefix}: informe a URL.")
        if step.type in TARGET_STEPS and step.target is None:
            errors.append(f"{prefix}: informe como encontrar o elemento.")
        if step.type == "fill" and step.value is None:
            errors.append(f"{prefix}: informe o valor a preencher.")
        if step.type == "secret_fill" and not step.secret:
            errors.append(f"{prefix}: informe o segredo.")
        if step.type == "press" and not step.key:
            errors.append(f"{prefix}: informe a tecla.")
        if step.type == "download" and not step.filename:
            errors.append(f"{prefix}: informe o nome do arquivo.")
        if step.type in PATH_STEPS and not step.path:
            errors.append(f"{prefix}: informe o caminho.")
        if step.type in SOURCE_DESTINATION_STEPS and not step.source:
            errors.append(f"{prefix}: informe a origem.")
        if step.type in SOURCE_DESTINATION_STEPS and not step.destination:
            errors.append(f"{prefix}: informe o destino.")
        if step.type == "file_write_text" and step.value is None:
            errors.append(f"{prefix}: informe o texto.")

    return errors
