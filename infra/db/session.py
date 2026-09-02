from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


DATABASE_URL = os.getenv("RPA_HUB_DATABASE_URL", "sqlite:///./rpa_hub.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine_kwargs = {"connect_args": connect_args}
if DATABASE_URL == "sqlite:///:memory:":
    engine_kwargs["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from infra.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
