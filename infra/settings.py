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


def _parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "sim", "on"}


@dataclass
class Settings:
    api_key: str | None = None
    allow_remote_without_api_key: bool = False
    delete_password: str | None = None
    allowed_roots: tuple[Path, ...] = field(default_factory=tuple)
    allowed_commands: tuple[str, ...] = field(default_factory=tuple)
    max_step_timeout_ms: int = DEFAULT_MAX_STEP_TIMEOUT_MS
    alert_email_to: str | None = None
    alert_email_from: str | None = None
    alert_email_host: str | None = None
    alert_email_port: int = 587
    alert_email_username: str | None = None
    alert_email_password_secret: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        try:
            max_timeout = int(env.get("RPA_HUB_MAX_STEP_TIMEOUT_MS", str(DEFAULT_MAX_STEP_TIMEOUT_MS)))
        except ValueError as exc:
            raise RuntimeError("RPA_HUB_MAX_STEP_TIMEOUT_MS deve ser um numero inteiro de milissegundos.") from exc
        try:
            alert_email_port = int(env.get("RPA_HUB_ALERT_EMAIL_PORT", "587"))
        except ValueError as exc:
            raise RuntimeError("RPA_HUB_ALERT_EMAIL_PORT deve ser um numero inteiro.") from exc
        return cls(
            api_key=env.get("RPA_HUB_API_KEY") or None,
            allow_remote_without_api_key=_parse_bool(env.get("RPA_HUB_ALLOW_REMOTE_WITHOUT_API_KEY")),
            delete_password=env.get("RPA_HUB_DELETE_PASSWORD") or None,
            allowed_roots=tuple(Path(item).expanduser() for item in _parse_csv(env.get("RPA_HUB_ALLOWED_ROOTS"))),
            allowed_commands=_parse_csv(env.get("RPA_HUB_ALLOWED_COMMANDS")),
            max_step_timeout_ms=max_timeout,
            alert_email_to=env.get("RPA_HUB_ALERT_EMAIL_TO") or None,
            alert_email_from=env.get("RPA_HUB_ALERT_EMAIL_FROM") or env.get("RPA_HUB_ALERT_EMAIL_USERNAME") or None,
            alert_email_host=env.get("RPA_HUB_ALERT_EMAIL_HOST") or None,
            alert_email_port=alert_email_port,
            alert_email_username=env.get("RPA_HUB_ALERT_EMAIL_USERNAME") or None,
            alert_email_password_secret=env.get("RPA_HUB_ALERT_EMAIL_PASSWORD_SECRET") or None,
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
