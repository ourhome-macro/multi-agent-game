from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI

from app.api.routes import create_router
from app.cases.loader import CaseLoader
from app.runtime.database import apply_schema, connect_postgres, load_dotenv_if_needed
from app.runtime.postgres_runtime import PostgresActionRuntime, PostgresRuntimeBackend
from app.runtime.service import RuntimeContainer, create_runtime
from app.storage.postgres import PostgresEventStore, PostgresSessionStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_ROOT = PROJECT_ROOT / "cases"
RUNTIME_MODE_ENV = "AGENT_RUNTIME"
POSTGRES_RUNTIME_MODE = "postgres"
APPLY_SCHEMA_ENV = "AGENT_POSTGRES_APPLY_SCHEMA"

runtime: RuntimeContainer | None = None


def build_runtime() -> RuntimeContainer:
    load_dotenv_if_needed()
    loader = CaseLoader()
    case_dirs = sorted(
        path for path in CASES_ROOT.iterdir() if path.is_dir() and (path / "case.yaml").exists()
    )
    container = create_runtime([loader.load(case_dir) for case_dir in case_dirs])
    runtime_mode = os.getenv(RUNTIME_MODE_ENV, "memory").strip().casefold()
    if runtime_mode != POSTGRES_RUNTIME_MODE:
        return container

    connection = connect_postgres()
    if os.getenv(APPLY_SCHEMA_ENV, "").strip().casefold() in {"1", "true", "yes"}:
        apply_schema(connection)
    event_store = PostgresEventStore(connection)
    session_store = PostgresSessionStore(connection, event_store=event_store)
    action_runtime = PostgresActionRuntime(
        event_store=event_store,
        action_service=container.action_service,
    )
    return replace(
        container,
        session_backend=PostgresRuntimeBackend(
            case_store=container.case_store,
            session_store=session_store,
            event_store=event_store,
            action_runtime=action_runtime,
            connection=connection,
        ),
    )


def get_runtime() -> RuntimeContainer:
    if runtime is None:
        raise RuntimeError("Runtime has not been initialized")
    return runtime


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        if runtime is not None:
            runtime.close()


def create_app() -> FastAPI:
    global runtime
    runtime = build_runtime()
    app = FastAPI(title="LLM multi-agent mystery runtime", lifespan=lifespan)
    app.include_router(create_router(get_runtime))
    return app


app = create_app()
