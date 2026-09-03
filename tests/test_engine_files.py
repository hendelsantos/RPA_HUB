from __future__ import annotations

import json
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

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


def test_disabled_steps_are_skipped(tmp_path):
    output = tmp_path / "ok.txt"
    skipped = tmp_path / "skipped.txt"
    logs = []
    workflow = {
        "inputs": {},
        "steps": [
            {"type": "file_write_text", "path": str(output), "value": "ok", "overwrite": True},
            {"type": "file_write_text", "path": str(skipped), "value": "nao roda", "overwrite": True, "meta": {"disabled": True}},
        ],
    }

    WorkflowExecutor(tmp_path / "artifacts", headless=True).run(workflow, log=lambda level, message, data: logs.append((level, message, data)))

    assert output.read_text(encoding="utf-8") == "ok"
    assert not skipped.exists()
    assert any(data and data.get("status") == "SKIPPED" for _, _, data in logs)


def test_validation_ignores_disabled_steps():
    workflow = {
        "inputs": {},
        "steps": [
            {"type": "goto", "meta": {"disabled": True}},
            {"type": "file_write_text", "path": "/tmp/ok.txt", "value": "ok", "overwrite": True},
        ],
    }

    assert validate_workflow(workflow) == []


def test_validation_requires_at_least_one_active_step():
    workflow = {"inputs": {}, "steps": [{"type": "goto", "meta": {"disabled": True}}]}

    assert "O robo nao possui passos ativos." in validate_workflow(workflow)


def test_workflow_validation_warns_about_common_url_typos():
    workflow = {"inputs": {}, "steps": [{"type": "goto", "url": "www.goolge.com"}]}

    errors = validate_workflow(workflow)

    assert "Passo 1 (goto): confira a URL. Voce quis dizer https://www.google.com?" in errors


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


def test_csv_excel_sqlite_folder_and_pdf_connectors(tmp_path):
    csv_path = tmp_path / "dados.csv"
    xlsx_path = tmp_path / "dados.xlsx"
    db_path = tmp_path / "dados.db"
    pdf_path = tmp_path / "evidencia.pdf"
    watched_dir = tmp_path / "entrada"
    watched_dir.mkdir()
    (watched_dir / "relatorio-final.txt").write_text("ok", encoding="utf-8")

    with sqlite3.connect(db_path) as connection:
        connection.execute("create table clientes (nome text, valor integer)")
        connection.execute("insert into clientes values ('HMB', 10)")

    workflow = {
        "inputs": {},
        "steps": [
            {"type": "csv_write", "path": str(csv_path), "value": '[{"nome":"Ana","valor":1}]', "overwrite": True},
            {"type": "csv_read", "path": str(csv_path), "variable": "linhas_csv"},
            {"type": "excel_write", "path": str(xlsx_path), "variable": "linhas_csv", "sheet": "Dados", "overwrite": True},
            {"type": "excel_read", "path": str(xlsx_path), "variable": "linhas_excel", "sheet": "Dados"},
            {"type": "db_query", "path": str(db_path), "query": "select * from clientes", "variable": "clientes", "output_name": "clientes"},
            {"type": "folder_wait_for_file", "path": str(watched_dir), "filename": "*.txt", "variable": "arquivo_encontrado"},
            {"type": "pdf_from_text", "path": str(pdf_path), "value": "Processado {{arquivo_encontrado}}", "overwrite": True},
        ],
    }

    artifacts = WorkflowExecutor(tmp_path / "artifacts", headless=True).run(workflow)

    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == "nome,valor"
    assert xlsx_path.exists()
    assert (tmp_path / "artifacts" / "clientes.csv").read_text(encoding="utf-8").splitlines()[1] == "HMB,10"
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert csv_path in artifacts
    assert xlsx_path in artifacts
    assert pdf_path in artifacts


def test_api_request_connector_stores_response(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length).decode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"received": payload}).encode("utf-8"))

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        workflow = {
            "inputs": {},
            "steps": [
                {
                    "type": "api_request",
                    "url": f"http://127.0.0.1:{server.server_port}/teste",
                    "method": "POST",
                    "headers": {"Content-Type": "text/plain"},
                    "body": "ola",
                    "variable": "api",
                    "output_name": "api-resposta",
                }
            ],
        }
        artifacts = WorkflowExecutor(tmp_path / "artifacts", headless=True).run(workflow)
    finally:
        server.shutdown()

    assert artifacts == [tmp_path / "artifacts" / "api-resposta.json"]
    data = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert data["body"]["received"] == "ola"


def test_email_send_uses_secret_without_logging_value(monkeypatch, tmp_path):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, username, password):
            sent["login"] = (username, password)

        def send_message(self, message):
            sent["to"] = message["To"]
            sent["subject"] = message["Subject"]
            sent["body"] = message.get_content()

    monkeypatch.setattr("rpa_core.engine.executor.smtplib.SMTP", FakeSMTP)

    workflow = {
        "inputs": {},
        "steps": [
            {
                "type": "email_send",
                "host": "smtp.local",
                "port": 2525,
                "username": "bot@empresa.com",
                "password_secret": "smtp.password",
                "to": "destino@empresa.com",
                "subject": "Resumo",
                "value": "Tudo certo",
            }
        ],
    }

    WorkflowExecutor(
        tmp_path / "artifacts",
        headless=True,
        secret_resolver=lambda name: "senha-real" if name == "smtp.password" else None,
    ).run(workflow)

    assert sent["host"] == "smtp.local"
    assert sent["port"] == 2525
    assert sent["login"] == ("bot@empresa.com", "senha-real")
    assert sent["to"] == "destino@empresa.com"
    assert sent["subject"] == "Resumo"
