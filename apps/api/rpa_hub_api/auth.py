from __future__ import annotations

from hmac import compare_digest

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from infra.settings import settings


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
PUBLIC_PATHS = {"/", "/health", "/environment", "/docs", "/redoc", "/openapi.json"}

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Chave de acesso da API (variavel RPA_HUB_API_KEY do servidor).",
)


async def require_api_key(request: Request, api_key: str | None = Security(api_key_header)) -> None:
    if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
        return

    expected = settings.api_key
    if expected:
        if api_key and compare_digest(api_key.encode("utf-8"), expected.encode("utf-8")):
            return
        raise HTTPException(
            status_code=401,
            detail="Acesso nao autorizado. Informe a chave da API no cabecalho X-API-Key.",
        )

    host = request.client.host if request.client else ""
    if host in LOOPBACK_HOSTS:
        return
    raise HTTPException(
        status_code=401,
        detail="Acesso remoto bloqueado. Defina a variavel RPA_HUB_API_KEY no servidor e informe a chave no cabecalho X-API-Key.",
    )
