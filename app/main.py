from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import (
    routes_agent,
    routes_feishu,
    routes_health,
    routes_innovation,
    routes_knowledge,
    routes_papers,
    routes_rag,
    routes_topics,
    routes_workflow,
)
from app.core.config import settings
from app.core.database import init_db
from app.core.exceptions import AppError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="科研论文助手第一阶段 MVP",
        lifespan=lifespan,
    )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.include_router(routes_health.router)
    app.include_router(routes_topics.router, prefix="/api")
    app.include_router(routes_papers.router, prefix="/api")
    app.include_router(routes_knowledge.router, prefix="/api")
    app.include_router(routes_innovation.router, prefix="/api")
    app.include_router(routes_rag.router, prefix="/api/rag")
    app.include_router(routes_agent.router, prefix="/api")
    app.include_router(routes_feishu.router, prefix="/api")
    app.include_router(routes_workflow.router, prefix="/api/workflow")
    return app


app = create_app()
