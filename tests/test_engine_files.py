from __future__ import annotations

import sys

from rpa_core.engine import WorkflowExecutor
from rpa_core.engine.validation import validate_workflow


def test_file_system_workflow_without_browser(tmp_path):
    source = tmp_path / "entrada.txt"
    destination = tmp_path / "saida" / "copia.txt"
    folder = tmp_path / "saida"

    workflow = {
        "inputs": {"texto": "relatorio pronto"},
        "steps": [
            {"type": "file_create_folder", "path": str(folder)},
            {"type": "file_write_text", "path": str(source), "value": "{{texto}}", "overwrite": True},
            {"type": "file_copy", "source": str(source), "destination": str(destination), "overwrite": True},
        ],
    }

    artifacts = WorkflowExecutor(tmp_path / "artifacts", headless=True).run(workflow)

    assert artifacts == []
    assert folder.is_dir()
    assert source.read_text(encoding="utf-8") == "relatorio pronto"
    assert destination.read_text(encoding="utf-8") == "relatorio pronto"


def test_run_inputs_override_workflow_defaults(tmp_path):
    output = tmp_path / "cliente.txt"
    workflow = {
        "inputs": {"cliente": "padrao"},
        "steps": [
            {"type": "file_write_text", "path": str(output), "value": "{{cliente}}", "overwrite": True},
        ],
    }

    WorkflowExecutor(tmp_path / "artifacts", headless=True).run(workflow, inputs={"cliente": "HMB"})

    assert output.read_text(encoding="utf-8") == "HMB"


def test_file_system_workflow_validation_requires_paths():
    workflow = {
        "inputs": {},
        "steps": [
            {"type": "file_create_folder"},
            {"type": "file_copy", "source": "/tmp/origem.txt"},
            {"type": "file_write_text", "path": "/tmp/arquivo.txt"},
        ],
    }

    errors = validate_workflow(workflow)

    assert "Passo 1 (file_create_folder): informe o caminho." in errors
    assert "Passo 2 (file_copy): informe o destino." in errors
    assert "Passo 3 (file_write_text): informe o texto." in errors


def test_file_read_zip_unzip_and_command_steps(tmp_path):
    work_dir = tmp_path / "work"
    source_file = work_dir / "entrada.txt"
    zip_path = tmp_path / "pacote.zip"
    extracted_dir = tmp_path / "extraido"
    copied_text = tmp_path / "copiado.txt"
    artifacts_dir = tmp_path / "artifacts"

    workflow = {
        "inputs": {},
        "steps": [
            {"type": "file_write_text", "path": str(source_file), "value": "conteudo forte", "overwrite": True},
            {"type": "file_read_text", "path": str(source_file), "variable": "texto_lido"},
            {"type": "file_write_text", "path": str(copied_text), "value": "{{texto_lido}}", "overwrite": True},
            {"type": "file_zip", "source": str(work_dir), "destination": str(zip_path), "overwrite": True},
            {"type": "file_unzip", "source": str(zip_path), "destination": str(extracted_dir)},
            {
                "type": "command_run",
                "command": sys.executable,
                "args": ["-c", "print('ok-command')"],
                "output_name": "saida",
            },
        ],
    }

    artifacts = WorkflowExecutor(artifacts_dir, headless=True).run(workflow)

    assert copied_text.read_text(encoding="utf-8") == "conteudo forte"
    assert (extracted_dir / "entrada.txt").read_text(encoding="utf-8") == "conteudo forte"
    assert zip_path in artifacts
    output_artifact = artifacts_dir / "saida.txt"
    assert output_artifact in artifacts
    assert output_artifact.read_text(encoding="utf-8") == "ok-command\n"
