"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from revvix_scout import __version__
from revvix_scout.api.router import public_router, router
from revvix_scout.application.bootstrap import bootstrap_defaults
from revvix_scout.config import get_settings
from revvix_scout.db.session import get_session_factory


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Seed deterministic development records after migrations are applied."""

    with get_session_factory()() as session:
        bootstrap_defaults(session, get_settings())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Provider-free business intake, evidence, deterministic qualification, and export."
        ),
        lifespan=lifespan,
    )
    app.include_router(public_router)
    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    """Run the development API server."""

    uvicorn.run("revvix_scout.main:app", host="127.0.0.1", port=8000, reload=False)
