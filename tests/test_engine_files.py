from __future__ import annotations

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
