from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from typing import Any

from app.runtime import schema_admin


def test_check_postgres_schema_reports_installed_version_and_core_tables() -> None:
    connection = FakeConnection(
        existing_tables=schema_admin.CORE_TABLES,
        schema_version=schema_admin.CURRENT_SCHEMA_VERSION,
    )

    result = schema_admin.check_postgres_schema(connection)

    assert result.ok is True
    assert result.installed_version == schema_admin.CURRENT_SCHEMA_VERSION
    assert result.missing_tables == ()
    assert "core tables are present" in result.message


def test_check_postgres_schema_reports_missing_tables_and_version() -> None:
    connection = FakeConnection(existing_tables=("app_sessions", "world_events"))

    result = schema_admin.check_postgres_schema(connection)

    assert result.ok is False
    assert result.installed_version is None
    assert "schema_migrations" in result.missing_tables
    assert "memory_snapshots" in result.missing_tables
    assert "schema version is not installed" in result.message


def test_apply_postgres_schema_applies_sql_then_checks_schema() -> None:
    connection = FakeConnection()

    result = schema_admin.apply_postgres_schema(connection)

    assert result.ok is True
    assert result.installed_version == schema_admin.CURRENT_SCHEMA_VERSION
    assert connection.applied_schema is True
    assert connection.commits >= 1


def test_rebuild_projection_tables_is_dry_run_by_default() -> None:
    connection = FakeConnection(
        existing_tables=schema_admin.CORE_TABLES,
        schema_version=schema_admin.CURRENT_SCHEMA_VERSION,
    )

    result = schema_admin.rebuild_projection_tables(connection)

    assert result.executed is False
    assert result.rebuilt_tables == schema_admin.PROJECTION_TABLES
    assert result.replayed_events == 0
    assert connection.truncated_projection is False


def test_rebuild_projection_tables_can_replay_projection_tables() -> None:
    connection = FakeConnection(
        existing_tables=schema_admin.CORE_TABLES,
        schema_version=schema_admin.CURRENT_SCHEMA_VERSION,
    )

    result = schema_admin.rebuild_projection_tables(connection, dry_run=False)

    assert result.executed is True
    assert result.rebuilt_tables == schema_admin.PROJECTION_TABLES
    assert result.replayed_events == 0
    assert connection.truncated_projection is True
    assert connection.projection_replay_selects == 1


class FakeConnection:
    def __init__(
        self,
        *,
        existing_tables: Sequence[str] = (),
        schema_version: int | None = None,
    ) -> None:
        self.existing_tables = set(existing_tables)
        self.schema_version = schema_version
        self.applied_schema = False
        self.truncated_projection = False
        self.projection_replay_selects = 0
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    @contextmanager
    def transaction(self) -> Any:
        try:
            yield
        except Exception:
            self.rollback()
            raise
        self.commit()


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.rows: list[dict[str, object]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: Sequence[object] | None = None) -> None:
        normalized = " ".join(query.split()).casefold()
        if "create table if not exists schema_migrations" in normalized:
            self.connection.applied_schema = True
            self.connection.existing_tables.update(schema_admin.CORE_TABLES)
            self.connection.schema_version = schema_admin.CURRENT_SCHEMA_VERSION
            self.rows = []
            return
        if "from information_schema.tables" in normalized:
            raw_requested = params[0] if params else ()
            assert isinstance(raw_requested, Iterable)
            requested = {str(table) for table in raw_requested}
            self.rows = [
                {"table_name": table}
                for table in sorted(requested & self.connection.existing_tables)
            ]
            return
        if "from schema_migrations" in normalized:
            self.rows = (
                [{"version": self.connection.schema_version}]
                if self.connection.schema_version is not None
                else []
            )
            return
        if normalized.startswith("truncate table memory_operations"):
            self.connection.truncated_projection = True
            self.rows = []
            return
        if "from world_events" in normalized:
            self.connection.projection_replay_selects += 1
            self.rows = []
            return
        raise AssertionError(f"Unexpected SQL in fake cursor: {query}")

    def fetchone(self) -> dict[str, object] | None:
        if not self.rows:
            return None
        return self.rows[0]

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows
