from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.api.routes import create_router
from app.cases.loader import CaseLoader
from app.runtime.service import RuntimeContainer, create_runtime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_ROOT = PROJECT_ROOT / "cases"

runtime: RuntimeContainer | None = None


def build_runtime() -> RuntimeContainer:
    loader = CaseLoader()
    case_dirs = sorted(
        path for path in CASES_ROOT.iterdir() if path.is_dir() and (path / "case.yaml").exists()
    )
    return create_runtime([loader.load(case_dir) for case_dir in case_dirs])


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
