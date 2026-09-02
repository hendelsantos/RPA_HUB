from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet


DEFAULT_MAX_STEP_TIMEOUT_MS = 3_600_000
LEGACY_DEFAULT_SECRET_KEY = "dev-local-key"


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass
class Settings:
    api_key: str | None = None
    delete_password: str | None = None
    allowed_roots: tuple[Path, ...] = field(default_factory=tuple)
    allowed_commands: tuple[str, ...] = field(default_factory=tuple)
    max_step_timeout_ms: int = DEFAULT_MAX_STEP_TIMEOUT_MS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        try:
            max_timeout = int(env.get("RPA_HUB_MAX_STEP_TIMEOUT_MS", str(DEFAULT_MAX_STEP_TIMEOUT_MS)))
        except ValueError as exc:
            raise RuntimeError("RPA_HUB_MAX_STEP_TIMEOUT_MS deve ser um numero inteiro de milissegundos.") from exc
        return cls(
            api_key=env.get("RPA_HUB_API_KEY") or None,
            delete_password=env.get("RPA_HUB_DELETE_PASSWORD") or None,
            allowed_roots=tuple(Path(item).expanduser() for item in _parse_csv(env.get("RPA_HUB_ALLOWED_ROOTS"))),
            allowed_commands=_parse_csv(env.get("RPA_HUB_ALLOWED_COMMANDS")),
            max_step_timeout_ms=max_timeout,
        )


settings = Settings.from_env()


def load_fernet_key() -> bytes:
    env_key = os.getenv("RPA_HUB_SECRET_KEY")
    if env_key:
        key = env_key.strip().encode("ascii")
        try:
            Fernet(key)
        except ValueError as exc:
            raise RuntimeError(
                "RPA_HUB_SECRET_KEY invalida. Gere uma chave com: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            ) from exc
        return key

    key_file = Path(os.getenv("RPA_HUB_SECRET_KEY_FILE", ".rpa_hub_secret.key"))
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip().encode("ascii")
        try:
            Fernet(key)
        except ValueError as exc:
            raise RuntimeError(f"Arquivo de chave {key_file} contem uma chave invalida.") from exc
        return key

    key = Fernet.generate_key()
    key_file.write_text(key.decode("ascii"), encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key
