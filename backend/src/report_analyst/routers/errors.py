"""Error responses: a code for each error, which the UI turns into its own message."""

from enum import StrEnum
from fastapi import Request
from fastapi.responses import JSONResponse
from http import HTTPStatus
from pydantic import BaseModel

from report_analyst.domain import Report


class ErrorCode(StrEnum):
    """What went wrong. Each route's `responses` lists the codes it can send."""

    REPORT_NOT_FOUND = "report_not_found"
    PAGE_NOT_FOUND = "page_not_found"
    CONVERSATION_NOT_FOUND = "conversation_not_found"
    NOT_FAILED = "not_failed"
    """Only a failed report can be retried."""
    ANSWER_FAILED = "answer_failed"
    """Claude couldn't answer; asking again may work."""
    FILE_TOO_LARGE = "file_too_large"
    NOT_A_PDF = "not_a_pdf"
    UNREADABLE_PDF = "unreadable_pdf"
    STILL_PROCESSING = "still_processing"
    """Replacing a report that is still processing."""
    SAME_FILE = "same_file"
    """The exact PDF is stored; there is nothing to choose."""
    SAME_COMPANY_YEAR = "same_company_year"
    """Another report for this Company and year is stored; send again with `on_duplicate`."""


class ErrorOut(BaseModel):
    """An error response.

    Attributes:
        code: What went wrong.
    """

    code: ErrorCode


class ExistingOut(ErrorOut):
    """An error about a stored report: a duplicate, or one still processing. Nothing was saved.

    Attributes:
        existing: The stored report.
    """

    existing: Report


class TooLargeOut(ErrorOut):
    """The upload is over the size limit.

    Attributes:
        max_upload_mb: The limit, in MB.
    """

    max_upload_mb: int


class ApiError(Exception):
    """Raised by a route to send `body` with `status`."""

    def __init__(self, status: HTTPStatus, body: ErrorOut) -> None:
        """Create the error.

        Args:
            status: The HTTP status.
            body: The response body.
        """
        super().__init__(body.code)
        self.status = status
        self.body = body


def api_error(status: HTTPStatus, code: ErrorCode) -> ApiError:
    """Build an error that carries only its code.

    Args:
        status: The HTTP status.
        code: What went wrong.

    Returns:
        The error, to raise.
    """
    return ApiError(status, ErrorOut(code=code))


def handle_api_error(_: Request, exc: Exception) -> JSONResponse:
    """Send an `ApiError`'s body. Registered on the app.

    Args:
        exc: The `ApiError`.

    Returns:
        The response.
    """
    assert isinstance(exc, ApiError)
    return JSONResponse(exc.body.model_dump(mode="json"), status_code=exc.status)
