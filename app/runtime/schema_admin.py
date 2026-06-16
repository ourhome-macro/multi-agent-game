from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.runtime.database import (
    DEFAULT_DATABASE_ENV,
    SCHEMA_PATH,
    apply_schema,
    connect_postgres,
)
from app.storage.postgres import ConnectionLike, PostgresEventStore, _stored_event_from_row

SCHEMA_NAME = "postgres_runtime_schema"
CURRENT_SCHEMA_VERSION = 1
CORE_TABLES = (
    "schema_migrations",
    "app_sessions",
    "world_events",
    "memory_snapshots",
    "memory_operations",
    "character_impressions",
    "character_fact_awareness",
    "runtime_traces",
    "idempotency_keys",
)
PROJECTION_TABLES = (
    "memory_operations",
    "memory_snapshots",
    "character_impressions",
    "character_fact_awareness",
)
REBUILD_PROJECTION_SQL = (
    "TRUNCATE TABLE memory_operations, memory_snapshots, "
    "character_impressions, character_fact_awareness"
)


@dataclass(frozen=True)
class SchemaCheckResult:
    ok: bool
    schema_name: str
    expected_version: int
    installed_version: int | None
    missing_tables: tuple[str, ...]

    @property
    def message(self) -> str:
        if self.ok:
            return (
                f"{self.schema_name} schema version {self.installed_version} is installed; "
                "core tables are present."
            )
        problems: list[str] = []
        if self.installed_version is None:
            problems.append("schema version is not installed")
        elif self.installed_version < self.expected_version:
            problems.append(
                f"schema version {self.installed_version} is older than "
                f"expected {self.expected_version}"
            )
        if self.missing_tables:
            problems.append("missing tables: " + ", ".join(self.missing_tables))
        return "; ".join(problems)


@dataclass(frozen=True)
class ProjectionRebuildResult:
    executed: bool
    rebuilt_tables: tuple[str, ...]
    replayed_events: int = 0


class SchemaCheckError(RuntimeError):
    def __init__(self, result: SchemaCheckResult) -> None:
        super().__init__(result.message)
        self.result = result


def apply_postgres_schema(
    connection: ConnectionLike,
    *,
    schema_path: Path | str = SCHEMA_PATH,
) -> SchemaCheckResult:
    apply_schema(connection, schema_path)
    return check_postgres_schema(connection)


def check_postgres_schema(
    connection: ConnectionLike,
    *,
    expected_version: int = CURRENT_SCHEMA_VERSION,
    core_tables: Sequence[str] = CORE_TABLES,
) -> SchemaCheckResult:
    existing_tables = _fetch_existing_tables(connection, core_tables)
    installed_version = (
        _fetch_schema_version(connection) if "schema_migrations" in existing_tables else None
    )
    missing_tables = tuple(table for table in core_tables if table not in existing_tables)
    ok = (
        installed_version is not None
        and installed_version >= expected_version
        and not missing_tables
    )
    return SchemaCheckResult(
        ok=ok,
        schema_name=SCHEMA_NAME,
        expected_version=expected_version,
        installed_version=installed_version,
        missing_tables=missing_tables,
    )


def ensure_postgres_schema(connection: ConnectionLike) -> SchemaCheckResult:
    result = check_postgres_schema(connection)
    if not result.ok:
        raise SchemaCheckError(result)
    return result


def rebuild_projection_tables(
    connection: ConnectionLike,
    *,
    dry_run: bool = True,
) -> ProjectionRebuildResult:
    """Rebuild derived projection tables from the authoritative world_events stream."""

    if dry_run:
        return ProjectionRebuildResult(
            executed=False,
            rebuilt_tables=PROJECTION_TABLES,
        )
    event_store = PostgresEventStore(connection)
    replayed_events = 0
    with _transaction(connection):
        with _cursor(connection) as cursor:
            cursor.execute(REBUILD_PROJECTION_SQL)
            cursor.execute(
                """
                SELECT id, case_id, session_id, actor_id, type, payload,
                       caused_by_event_id, created_at, sequence, schema_version
                FROM world_events
                ORDER BY session_id, sequence
                """
            )
            for row in cursor.fetchall():
                event_store._apply_projection(cursor, _stored_event_from_row(row))
                replayed_events += 1
    return ProjectionRebuildResult(
        executed=True,
        rebuilt_tables=PROJECTION_TABLES,
        replayed_events=replayed_events,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage PostgreSQL runtime schema for the agent service."
    )
    parser.add_argument(
        "--database-url",
        help=f"PostgreSQL URL. Defaults to {DEFAULT_DATABASE_ENV} or .env.",
    )
    parser.add_argument(
        "--env-name",
        default=DEFAULT_DATABASE_ENV,
        help="Environment variable to read when --database-url is omitted.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("apply", help="Apply app/storage/schema.sql and verify it.")
    subparsers.add_parser("check", help="Verify schema version and core table presence.")
    rebuild = subparsers.add_parser(
        "rebuild-projection",
        help="Show or run the projection table rebuild placeholder.",
    )
    rebuild.add_argument(
        "--execute",
        action="store_true",
        help="Truncate projection tables. Rehydration is not implemented in this command yet.",
    )
    args = parser.parse_args(argv)

    with _managed_connection(
        lambda: connect_postgres(args.database_url, env_name=args.env_name)
    ) as connection:
        if args.command == "apply":
            result = apply_postgres_schema(connection)
            print(result.message)
            return 0 if result.ok else 1
        if args.command == "check":
            check_result = check_postgres_schema(connection)
            print(check_result.message)
            return 0 if check_result.ok else 1
        if args.command == "rebuild-projection":
            rebuild_result = rebuild_projection_tables(connection, dry_run=not args.execute)
            if args.execute:
                print(
                    "Rebuilt projection tables from "
                    f"{rebuild_result.replayed_events} events: "
                    + ", ".join(rebuild_result.rebuilt_tables)
                )
            else:
                print(
                    "Dry run; would rebuild projection tables: "
                    + ", ".join(rebuild_result.rebuilt_tables)
                )
            return 0
    raise AssertionError(f"Unknown command: {args.command}")


def _fetch_existing_tables(
    connection: ConnectionLike,
    tables: Iterable[str],
) -> set[str]:
    requested = tuple(tables)
    with _transaction(connection):
        with _cursor(connection) as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = ANY(%s)
                """,
                (list(requested),),
            )
            return {str(_row_get(row, "table_name", 0)) for row in cursor.fetchall()}


def _fetch_schema_version(connection: ConnectionLike) -> int | None:
    with _transaction(connection):
        with _cursor(connection) as cursor:
            cursor.execute(
                """
                SELECT version
                FROM schema_migrations
                WHERE name = %s
                """,
                (SCHEMA_NAME,),
            )
            row = cursor.fetchone()
    if row is None:
        return None
    return int(_row_get(row, "version", 0))


@contextmanager
def _managed_connection(factory: Callable[[], ConnectionLike]) -> Iterator[ConnectionLike]:
    connection = factory()
    try:
        yield connection
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()


@contextmanager
def _transaction(connection: ConnectionLike) -> Iterator[None]:
    transaction = getattr(connection, "transaction", None)
    if callable(transaction):
        with transaction():
            yield
        return
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


def _row_get(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError):
        return row[index]


if __name__ == "__main__":
    raise SystemExit(main())
