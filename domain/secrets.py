from __future__ import annotations

import base64
import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from infra.db.models import Secret


class SecretStore:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.key = os.getenv("RPA_HUB_SECRET_KEY", "dev-local-key").encode("utf-8")

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
        secret.updated_at = datetime.utcnow()
        self.session.commit()
        self.session.refresh(secret)
        return secret

    def resolve(self, name: str) -> str | None:
        secret = self.session.scalar(select(Secret).where(Secret.name == name))
        if secret is None:
            return None
        return self._decrypt(secret.encrypted_value)

    def _encrypt(self, value: str) -> str:
        data = value.encode("utf-8")
        encrypted = bytes(byte ^ self.key[index % len(self.key)] for index, byte in enumerate(data))
        return base64.urlsafe_b64encode(encrypted).decode("ascii")

    def _decrypt(self, value: str) -> str:
        encrypted = base64.urlsafe_b64decode(value.encode("ascii"))
        data = bytes(byte ^ self.key[index % len(self.key)] for index, byte in enumerate(encrypted))
        return data.decode("utf-8")
