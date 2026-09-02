from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from infra.db.models import AuditEvent


def audit(session: Session, action: str, entity_type: str, entity_id: int | str, data: dict[str, Any] | None = None, actor: str = "system") -> None:
    session.add(
        AuditEvent(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            data=data,
        )
    )
