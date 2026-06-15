from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.storage.postgres import ConnectionLike

DEFAULT_DATABASE_ENV = "AGENT_DATABASE_URL"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "storage" / "schema.sql"


def database_url_from_env(env_name: str = DEFAULT_DATABASE_ENV) -> str:
    value = os.getenv(env_name)
    if not value:
        raise RuntimeError(
            f"{env_name} is not set. Use a PostgreSQL URL such as "
            "postgresql://agent_app:***@localhost:5432/agent_runtime."
        )
    return value


def connect_postgres(
    database_url: str | None = None,
    *,
    env_name: str = DEFAULT_DATABASE_ENV,
) -> ConnectionLike:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL runtime persistence requires psycopg. "
            "Install psycopg[binary] in the deployment environment."
        ) from exc

    return psycopg.connect(
        database_url or database_url_from_env(env_name),
        autocommit=False,
        row_factory=dict_row,
    )


def apply_schema(connection: ConnectionLike, schema_path: Path | str = SCHEMA_PATH) -> None:
    schema_sql = Path(schema_path).read_text(encoding="utf-8")
    with _transaction(connection):
        with _cursor(connection) as cursor:
            cursor.execute(schema_sql)


@contextmanager
def postgres_connection(
    database_url: str | None = None,
    *,
    env_name: str = DEFAULT_DATABASE_ENV,
) -> Iterator[ConnectionLike]:
    connection = connect_postgres(database_url, env_name=env_name)
    try:
        yield connection
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()


@contextmanager
def _transaction(connection: ConnectionLike) -> Iterator[None]:
    try:
        yield
    except Exception:
        connection.rollback()
        raise
    connection.commit()


@contextmanager
def _cursor(connection: ConnectionLike) -> Iterator[Any]:
    raw_cursor = connection.cursor()
    if hasattr(raw_cursor, "__enter__"):
        with raw_cursor as cursor:
            yield cursor
        return
    try:
        yield raw_cursor
    finally:
        close = getattr(raw_cursor, "close", None)
        if callable(close):
            close()
