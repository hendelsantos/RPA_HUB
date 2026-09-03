from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rpa_core.engine.models import WorkflowDefinition
from rpa_core.engine.sandbox import DEFAULT_MAX_STEP_TIMEOUT_MS
from rpa_core.variables import suggest_url_correction


TARGET_STEPS = {"click", "fill", "secret_fill", "select", "press", "wait_for", "assert_text", "download"}
PATH_STEPS = {
    "file_create_folder",
    "file_delete",
    "file_write_text",
    "file_read_text",
    "csv_read",
    "csv_write",
    "excel_read",
    "excel_write",
    "db_query",
    "folder_wait_for_file",
    "pdf_from_text",
}
SOURCE_DESTINATION_STEPS = {"file_copy", "file_move", "file_zip", "file_unzip"}
DESKTOP_XY_STEPS = {"desktop_move", "desktop_drag"}
MAX_RETRY = 5
SENSITIVE_WORDS = {"senha", "password", "pass", "token", "secret", "segredo"}


def validate_workflow(
    workflow_data: dict[str, Any],
    max_step_timeout_ms: int = DEFAULT_MAX_STEP_TIMEOUT_MS,
) -> list[str]:
    errors: list[str] = []
    try:
        workflow = WorkflowDefinition.model_validate(workflow_data)
    except ValidationError as exc:
        return [f"Workflow invalido: {error['msg']}" for error in exc.errors()]

    if not workflow.steps:
        errors.append("O robo nao possui passos.")
    elif not any(not step.meta.get("disabled") for step in workflow.steps):
        errors.append("O robo nao possui passos ativos.")

    for index, step in enumerate(workflow.steps, start=1):
        if step.meta.get("disabled"):
            continue
        prefix = f"Passo {index} ({step.type})"
        if step.timeout_ms is not None and step.timeout_ms <= 0:
            errors.append(f"{prefix}: timeout_ms deve ser positivo.")
        if step.timeout_ms is not None and step.timeout_ms > max_step_timeout_ms:
            errors.append(f"{prefix}: timeout_ms excede o limite de {max_step_timeout_ms} ms.")
        if step.retry is not None and step.retry > MAX_RETRY:
            errors.append(f"{prefix}: retry deve ser no maximo {MAX_RETRY}.")
        if step.type == "goto" and not step.url:
            errors.append(f"{prefix}: informe a URL.")
        if step.type == "api_request" and not step.url:
            errors.append(f"{prefix}: informe a URL da API.")
        if step.type in {"goto", "api_request"} and step.url:
            suggestion = suggest_url_correction(step.url)
            if suggestion:
                errors.append(f"{prefix}: confira a URL. Voce quis dizer {suggestion}?")
        if step.type in TARGET_STEPS and step.target is None:
            errors.append(f"{prefix}: informe como encontrar o elemento.")
        if step.type == "fill" and step.value is None:
            errors.append(f"{prefix}: informe o valor a preencher.")
        if step.type == "fill" and _looks_sensitive(step.target) and step.value and "{{" not in step.value:
            errors.append(f"{prefix}: este campo parece senha/token. Use o passo Preencher credencial para nao salvar valor sensivel no workflow.")
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
        if step.type == "file_read_text" and not step.variable:
            errors.append(f"{prefix}: informe a variavel de destino.")
        if step.type in {"csv_read", "excel_read"} and not step.variable:
            errors.append(f"{prefix}: informe a variavel de destino.")
        if step.type == "db_query" and not step.query:
            errors.append(f"{prefix}: informe a consulta SQL.")
        if step.type == "folder_wait_for_file" and not step.filename:
            errors.append(f"{prefix}: informe o nome ou padrao do arquivo.")
        if step.type == "email_send":
            if not step.host:
                errors.append(f"{prefix}: informe o servidor SMTP.")
            if not step.to:
                errors.append(f"{prefix}: informe o destinatario.")
            if not step.subject:
                errors.append(f"{prefix}: informe o assunto.")
        if step.type == "pdf_from_text" and step.value is None:
            errors.append(f"{prefix}: informe o texto do PDF.")
        if step.type == "command_run" and not step.command:
            errors.append(f"{prefix}: informe o comando.")
        if step.type in DESKTOP_XY_STEPS and (step.x is None or step.y is None):
            errors.append(f"{prefix}: informe as coordenadas x e y.")
        if step.type == "desktop_type" and step.value is None:
            errors.append(f"{prefix}: informe o texto.")
        if step.type == "desktop_press" and not step.key:
            errors.append(f"{prefix}: informe a tecla.")
        if step.type == "desktop_hotkey" and not step.keys:
            errors.append(f"{prefix}: informe as teclas do atalho.")
        if step.type == "desktop_screenshot" and not step.name:
            errors.append(f"{prefix}: informe o nome da evidencia.")

    return errors


def _looks_sensitive(target) -> bool:
    if target is None:
        return False
    values = [
        target.label,
        target.text,
        target.name,
        target.css,
    ]
    haystack = " ".join(value.lower() for value in values if value)
    return any(word in haystack for word in SENSITIVE_WORDS)
