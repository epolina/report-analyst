"""HTTP route for uploads: POST /uploads. Maps the report service's outcomes to HTTP."""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from http import HTTPStatus
from pydantic import StringConstraints
from typing import Annotated

from report_analyst.domain import OnDuplicate, Report
from report_analyst.reports import (
    NotAPdfError,
    ReportService,
    SameCompanyYearError,
    SameFileError,
    StillProcessingError,
    UnreadablePdfError,
)
from report_analyst.routers.dependencies import get_report_service, get_settings
from report_analyst.routers.errors import (
    ApiError,
    ErrorCode,
    ErrorOut,
    ExistingOut,
    TooLargeOut,
    api_error,
)
from report_analyst.settings import AppSettings


router = APIRouter(prefix="/uploads", tags=["uploads"])

BYTES_PER_MB = 1024 * 1024


@router.post(
    "",
    status_code=HTTPStatus.ACCEPTED,
    responses={
        HTTPStatus.CONFLICT: {"model": ExistingOut},
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE: {"model": TooLargeOut},
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE: {"model": ErrorOut},
    },
)
def upload(
    settings: Annotated[AppSettings, Depends(get_settings)],
    service: Annotated[ReportService, Depends(get_report_service)],
    file: Annotated[UploadFile, File()],
    company_name: Annotated[str, Form(), StringConstraints(strip_whitespace=True, min_length=1)],
    reporting_year: Annotated[int, Form(ge=1900, le=2100)],
    on_duplicate: Annotated[OnDuplicate | None, Form()] = None,
) -> Report:
    """Add an annual report PDF, asking first about a duplicate, and start processing it.

    Processing runs in the background: poll `GET /reports` until the report's status is success
    or failed. One report is processed at a time; a second one waits its turn.

    Args:
        settings: The app settings.
        service: Stores the report, then extracts its FTE and goals.
        file: The annual report PDF.
        company_name: The Company the report belongs to, as entered by the user.
        reporting_year: The Reporting Year the report covers.
        on_duplicate: What to do when a report for this Company and year is stored; None asks
            first with a 409 `same_company_year`.

    Returns:
        The stored report, processing.

    Raises:
        ApiError: 409 `same_file`, `same_company_year` or `still_processing`, naming the stored
            report; 413 `file_too_large`; 415 `not_a_pdf`; 422 `unreadable_pdf` if pdfium
            can't open it. Missing or invalid fields get FastAPI's own 422 validation error.
    """
    limit = settings.max_upload_mb * BYTES_PER_MB
    # Read one byte past the limit, so an oversized file is never fully loaded.
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise ApiError(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            TooLargeOut(code=ErrorCode.FILE_TOO_LARGE, max_upload_mb=settings.max_upload_mb),
        )
    try:
        return service.add(company_name, reporting_year, content, file.filename, on_duplicate)
    except NotAPdfError as exc:
        raise api_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, ErrorCode.NOT_A_PDF) from exc
    except UnreadablePdfError as exc:
        raise api_error(HTTPStatus.UNPROCESSABLE_CONTENT, ErrorCode.UNREADABLE_PDF) from exc
    except StillProcessingError as exc:
        raise _conflict_error(ErrorCode.STILL_PROCESSING, exc.existing) from exc
    except SameFileError as exc:
        raise _conflict_error(ErrorCode.SAME_FILE, exc.existing) from exc
    except SameCompanyYearError as exc:
        raise _conflict_error(ErrorCode.SAME_COMPANY_YEAR, exc.existing) from exc


def _conflict_error(code: ErrorCode, existing: Report) -> ApiError:
    return ApiError(HTTPStatus.CONFLICT, ExistingOut(code=code, existing=existing))
