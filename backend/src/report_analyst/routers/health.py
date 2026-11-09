"""HTTP route for the health check: GET /health."""

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(tags=["health"])


class Health(BaseModel):
    """Response of GET /health."""

    status: str


@router.get("/health")
def health() -> Health:
    """Report that the service is up.

    Returns:
        Always `{"status": "ok"}`.
    """
    return Health(status="ok")
