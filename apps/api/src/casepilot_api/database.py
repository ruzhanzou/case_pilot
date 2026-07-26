from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from casepilot_api.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        pool_recycle=300,
    )


def check_database() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("select 1"))


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


def get_db_session() -> Iterator[Session]:
    with get_session_factory()() as session:
        yield session
