from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.api.routes import create_router
from app.cases.loader import CaseLoader
from app.runtime.service import RuntimeContainer, create_runtime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASE_DIR = PROJECT_ROOT / "cases" / "fake_case"

runtime: RuntimeContainer | None = None


def build_runtime() -> RuntimeContainer:
    loader = CaseLoader()
    fake_case = loader.load(DEFAULT_CASE_DIR)
    return create_runtime([fake_case])


def get_runtime() -> RuntimeContainer:
    if runtime is None:
        raise RuntimeError("Runtime has not been initialized")
    return runtime


def create_app() -> FastAPI:
    global runtime
    runtime = build_runtime()
    app = FastAPI(title="LLM 多智能体悬疑叙事游戏后端运行时骨架")
    app.include_router(create_router(get_runtime))
    return app


app = create_app()
