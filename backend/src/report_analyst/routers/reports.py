"""HTTP routes for reports: the list, one report with its facts, retry, and page images."""

from fastapi import APIRouter, Depends, Response
from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from report_analyst.domain import Facts, Fte, Report, SustainabilityGoal
from report_analyst.reports import NotFailedError, ReportRepository, ReportService
from report_analyst.routers.dependencies import get_report_repository, get_report_service
from report_analyst.routers.errors import ErrorCode, ErrorOut, api_error


router = APIRouter(prefix="/reports", tags=["reports"])


class ReportDetail(Report):
    """A report with the facts found in it.

    Attributes:
        fte: The total FTE, or None if it wasn't found.
        goals: The Sustainability Goals, in page order.
    """

    fte: Fte | None
    goals: list[SustainabilityGoal]


@router.get("")
def list_reports(
    repository: Annotated[ReportRepository, Depends(get_report_repository)],
) -> list[Report]:
    """List all stored reports.

    Args:
        repository: Where reports are stored.

    Returns:
        The reports, by Company and then year.
    """
    return repository.list()


@router.get("/{report_id}", responses={HTTPStatus.NOT_FOUND: {"model": ErrorOut}})
def get_report(
    report_id: UUID,
    repository: Annotated[ReportRepository, Depends(get_report_repository)],
) -> ReportDetail:
    """Get a report with its FTE and Sustainability Goals.

    The Facts are extracted while the report is processed. A report that is processing or
    failed has none yet: `fte` is null and `goals` empty.

    Args:
        report_id: The report's id.
        repository: Where reports are stored.

    Returns:
        The report and its facts.

    Raises:
        ApiError: 404 `report_not_found`.
    """
    report = repository.get(report_id)
    if report is None:
        raise api_error(HTTPStatus.NOT_FOUND, ErrorCode.REPORT_NOT_FOUND)
    facts = repository.facts(report_id) or Facts()
    return ReportDetail(
        **report.model_dump(),
        fte=facts.fte,
        goals=facts.goals,
    )


@router.post(
    "/{report_id}/retry",
    status_code=HTTPStatus.ACCEPTED,
    responses={
        HTTPStatus.NOT_FOUND: {"model": ErrorOut},
        HTTPStatus.CONFLICT: {"model": ErrorOut},
    },
)
def retry_report(
    report_id: UUID,
    repository: Annotated[ReportRepository, Depends(get_report_repository)],
    service: Annotated[ReportService, Depends(get_report_service)],
) -> Report:
    """Process a failed report again, from the PDF it stored.

    Args:
        report_id: The report's id.
        repository: Where reports are stored.
        service: Processes the report in the background.

    Returns:
        The report, processing.

    Raises:
        ApiError: 404 `report_not_found`; 409 `not_failed`.
    """
    if repository.get(report_id) is None:
        raise api_error(HTTPStatus.NOT_FOUND, ErrorCode.REPORT_NOT_FOUND)
    try:
        return service.retry(report_id)
    except NotFailedError as exc:
        raise api_error(HTTPStatus.CONFLICT, ErrorCode.NOT_FAILED) from exc


@router.get(
    "/{report_id}/pages/{page_number}",
    response_class=Response,
    responses={
        HTTPStatus.OK: {"content": {"image/jpeg": {}}},
        HTTPStatus.NOT_FOUND: {"model": ErrorOut},
    },
)
def get_page(
    report_id: UUID,
    page_number: int,
    repository: Annotated[ReportRepository, Depends(get_report_repository)],
) -> Response:
    """Get one page of a report as a JPEG image, rendered while it was processed.

    Args:
        report_id: The report's id.
        page_number: The page number, starting at 1.
        repository: Where the page images are stored.

    Returns:
        The image.

    Raises:
        ApiError: 404 `page_not_found`, also for an unknown report.
    """
    if (image := repository.page_image(report_id, page_number)) is None:
        raise api_error(HTTPStatus.NOT_FOUND, ErrorCode.PAGE_NOT_FOUND)
    return Response(image, media_type="image/jpeg")
