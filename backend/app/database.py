import os
from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://nexoeventos_app@/nexoeventos"


def build_engine(database_url: str | None = None) -> Engine:
    # El pool por worker se acota con variables de entorno (V2: varias instancias comparten una RDS pequeña); los valores por defecto son los de siempre.
    return create_engine(
        database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        pool_pre_ping=True,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(request: Request) -> Generator[Session, None, None]:
    with request.app.state.session_factory() as session:
        yield session
