from __future__ import annotations

import asyncio
import base64
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from domain.secrets import SecretStore
from infra import settings as settings_module
from infra.db.models import Secret
from rpa_core.engine.executor import WorkflowExecutor
from rpa_core.engine.sandbox import StepSandbox
from rpa_core.engine.validation import validate_workflow
from sqlalchemy import select


def test_api_rejects_missing_and_wrong_key(anon_client, client):
    assert anon_client.get("/robots").status_code == 401
    assert anon_client.get("/robots", headers={"X-API-Key": "chave-errada"}).status_code == 401
    assert client.get("/robots").status_code == 200


def test_docs_and_schema_are_public_without_key(anon_client):
    assert anon_client.get("/docs").status_code == 200
    assert anon_client.get("/openapi.json").status_code == 200


def test_public_endpoints_do_not_require_key(anon_client):
    health = anon_client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    environment = anon_client.get("/environment")
    assert environment.status_code == 200
    assert "available" in environment.json()["desktop"]

    web = anon_client.get("/")
    assert web.status_code == 200
    assert "HUB RPA" in web.text


def test_remote_access_blocked_without_api_key(anon_client, monkeypatch):
    monkeypatch.setattr(settings_module.settings, "api_key", None)
    response = anon_client.get("/robots")
    assert response.status_code == 401
    assert "RPA_HUB_API_KEY" in response.json()["detail"]


def _make_request(path: str, host: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": (host, 12345),
        "headers": [],
    }
    return Request(scope)


def test_loopback_allowed_without_api_key(monkeypatch):
    from apps.api.rpa_hub_api.auth import require_api_key

    monkeypatch.setattr(settings_module.settings, "api_key", None)
    request = _make_request("/robots", "127.0.0.1")
    assert asyncio.run(require_api_key(request, None)) is None


def test_non_loopback_denied_without_api_key(monkeypatch):
    from apps.api.rpa_hub_api.auth import require_api_key

    monkeypatch.setattr(settings_module.settings, "api_key", None)
    request = _make_request("/robots", "192.168.1.50")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_api_key(request, None))
    assert exc_info.value.status_code == 401


def test_secret_roundtrip_with_random_ciphertext(client, db_session):
    client.post("/secrets", json={"name": "roundtrip.senha", "value": "valor-secreto"})

    store = SecretStore(db_session)
    assert store.resolve("roundtrip.senha") == "valor-secreto"

    first = store._encrypt("mesma-coisa")
    second = store._encrypt("mesma-coisa")
    assert first != second
    assert store.fernet.decrypt(first.encode()) == b"mesma-coisa"
    assert store.fernet.decrypt(second.encode()) == b"mesma-coisa"


def test_legacy_xor_secret_is_migrated_to_fernet(client, db_session):
    client.post("/secrets", json={"name": "legado.senha", "value": "temporaria"})
    secret = db_session.scalar(select(Secret).where(Secret.name == "legado.senha"))

    key = b"dev-local-key"
    plaintext = b"senha-legado-real"
    secret.encrypted_value = base64.urlsafe_b64encode(
        bytes(byte ^ key[index % len(key)] for index, byte in enumerate(plaintext))
    ).decode("ascii")
    db_session.commit()

    store = SecretStore(db_session)
    assert store.resolve("legado.senha") == "senha-legado-real"

    db_session.expire_all()
    secret = db_session.scalar(select(Secret).where(Secret.name == "legado.senha"))
    assert secret.encrypted_value.startswith("gAAAA")
    assert store.resolve("legado.senha") == "senha-legado-real"


def test_unzip_blocks_zip_slip(tmp_path):
    evil_zip = tmp_path / "malicioso.zip"
    with zipfile.ZipFile(evil_zip, "w") as archive:
        archive.writestr("normal.txt", "conteudo")
        archive.writestr("../escaped.txt", "conteudo perigoso")

    workflow = {
        "inputs": {},
        "steps": [
            {"type": "file_unzip", "source": str(evil_zip), "destination": str(tmp_path / "destino")},
        ],
    }

    executor = WorkflowExecutor(tmp_path / "artifacts", headless=True)
    with pytest.raises(ValueError, match="suspeito"):
        executor.run(workflow)

    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path / "destino" / "normal.txt").exists()


def test_allowed_roots_confine_file_steps(tmp_path):
    sandbox = StepSandbox(allowed_roots=(tmp_path,))
    inside = {
        "inputs": {},
        "steps": [{"type": "file_write_text", "path": str(tmp_path / "dentro.txt"), "value": "ok", "overwrite": True}],
    }
    outside = {
        "inputs": {},
        "steps": [{"type": "file_write_text", "path": str(tmp_path.parent / "rpa_fora_teste.txt"), "value": "nok", "overwrite": True}],
    }

    WorkflowExecutor(tmp_path / "artifacts", headless=True, sandbox=sandbox).run(inside)
    assert (tmp_path / "dentro.txt").read_text(encoding="utf-8") == "ok"

    with pytest.raises(ValueError, match="raizes permitidas"):
        WorkflowExecutor(tmp_path / "artifacts", headless=True, sandbox=sandbox).run(outside)
    assert not (tmp_path.parent / "rpa_fora_teste.txt").exists()


def test_allowed_commands_block_unlisted_binaries(tmp_path):
    sandbox = StepSandbox(allowed_commands=frozenset({Path(sys.executable).name}))
    allowed = {
        "inputs": {},
        "steps": [{"type": "command_run", "command": sys.executable, "args": ["-c", "print('permitido')"]}],
    }
    blocked = {
        "inputs": {},
        "steps": [{"type": "command_run", "command": "binario-nao-permitido", "args": []}],
    }

    WorkflowExecutor(tmp_path / "artifacts", headless=True, sandbox=sandbox).run(allowed)

    with pytest.raises(ValueError, match="Comando nao permitido"):
        WorkflowExecutor(tmp_path / "artifacts", headless=True, sandbox=sandbox).run(blocked)


def test_command_run_does_not_leak_server_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("RPA_HUB_TEST_LEAK", "segredo-do-servidor")
    workflow = {
        "inputs": {},
        "steps": [
            {
                "type": "command_run",
                "command": sys.executable,
                "args": ["-c", "import os; print('VAZOU' if 'RPA_HUB_TEST_LEAK' in os.environ else 'LIMPO')"],
                "output_name": "saida",
            },
        ],
    }

    artifacts = WorkflowExecutor(tmp_path / "artifacts", headless=True).run(workflow)

    output = artifacts[0].read_text(encoding="utf-8")
    assert output.strip() == "LIMPO"


def test_step_timeout_and_retry_bounds(tmp_path):
    sandbox = StepSandbox(max_step_timeout_ms=5000)
    workflow = {
        "inputs": {},
        "steps": [{"type": "file_write_text", "path": str(tmp_path / "ok.txt"), "value": "x", "overwrite": True, "timeout_ms": 9_999_999}],
    }

    errors = validate_workflow(workflow, max_step_timeout_ms=5000)
    assert any("limite de 5000" in error for error in errors)

    with pytest.raises(ValueError, match="excede o limite"):
        WorkflowExecutor(tmp_path / "artifacts", headless=True, sandbox=sandbox).run(workflow)

    retry_workflow = {
        "inputs": {},
        "steps": [{"type": "file_write_text", "path": str(tmp_path / "ok.txt"), "value": "x", "overwrite": True, "retry": 9}],
    }
    assert any("retry" in error for error in validate_workflow(retry_workflow))
