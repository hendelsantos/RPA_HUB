from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from infra.db.models import Secret
from infra.settings import LEGACY_DEFAULT_SECRET_KEY, load_fernet_key
from infra.time import utc_now


FERNET_PREFIX = "gAAAA"


class SecretStore:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.fernet = Fernet(load_fernet_key())

    def list(self) -> list[Secret]:
        return list(self.session.scalars(select(Secret).order_by(Secret.name)))

    def create_or_update(self, name: str, value: str, description: str = "", secret_type: str = "credential") -> Secret:
        secret = self.session.scalar(select(Secret).where(Secret.name == name))
        if secret is None:
            secret = Secret(name=name, encrypted_value="")
            self.session.add(secret)
        secret.description = description
        secret.secret_type = secret_type
        secret.encrypted_value = self._encrypt(value)
        secret.updated_at = utc_now()
        self.session.flush()
        return secret

    def can_resolve(self, name: str) -> bool:
        return self.resolve(name) is not None

    def resolve(self, name: str) -> str | None:
        secret = self.session.scalar(select(Secret).where(Secret.name == name))
        if secret is None:
            return None
        value = self._decrypt(secret.encrypted_value)
        if value is None:
            return None
        if secret.encrypted_value and not secret.encrypted_value.startswith(FERNET_PREFIX):
            secret.encrypted_value = self._encrypt(value)
            self.session.flush()
        return value

    def _encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt(self, stored: str) -> str | None:
        if not stored:
            return None
        try:
            return self.fernet.decrypt(stored.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            pass
        return self._legacy_decrypt(stored)

    def _legacy_decrypt(self, stored: str) -> str | None:
        key = os.getenv("RPA_HUB_LEGACY_SECRET_KEY", LEGACY_DEFAULT_SECRET_KEY).encode("utf-8")
        try:
            encrypted = base64.urlsafe_b64decode(stored.encode("ascii"))
            data = bytes(byte ^ key[index % len(key)] for index, byte in enumerate(encrypted))
            return data.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
