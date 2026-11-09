"""FastAPI app: creates the app and includes the routers."""

import logging

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI

from report_analyst.reports import ReportRepository, fail_interrupted
from report_analyst.routers import chat, health, reports, uploads
from report_analyst.routers.dependencies import get_settings
from report_analyst.routers.errors import ApiError, handle_api_error


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Check the settings at start-up and fail reports a restart interrupted, then run the app.

    Args:
        app: The app being started.

    Yields:
        Control to FastAPI while the app runs.

    Raises:
        pydantic.ValidationError: A required setting is missing or invalid.
    """
    get_settings()
    # Uses the settings override when one is set.
    settings = app.dependency_overrides.get(get_settings, get_settings)()
    fail_interrupted(ReportRepository(settings.reports_dir))
    yield


def create_app() -> FastAPI:
    """Create the app and register its routes.

    Returns:
        The FastAPI app.
    """
    app = FastAPI(title="Report analyst", lifespan=lifespan)
    app.add_exception_handler(ApiError, handle_api_error)
    app.include_router(uploads.router)
    app.include_router(reports.router)
    app.include_router(chat.router)
    app.include_router(health.router)
    return app


app = create_app()
