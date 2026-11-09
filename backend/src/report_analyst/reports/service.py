"""A Report's use cases: adding it and processing it in the background, up to its Facts."""

import hashlib
import logging
import time

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID

from report_analyst.domain import OnDuplicate, Report, ReportFailure, ReportStatus
from report_analyst.facts import FactExtractor
from report_analyst.llm import LLMError
from report_analyst.pdf import ExtractionError, PdfExtractor, page_count, render_pages
from report_analyst.reports.errors import (
    NotAPdfError,
    NotFailedError,
    SameCompanyYearError,
    SameFileError,
    StillProcessingError,
    UnreadablePdfError,
)
from report_analyst.reports.repository import ReportRepository
from report_analyst.reports.retriever import Retriever
from report_analyst.reports.splitting import split_into_passages


logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF-"

# One report is processed at a time, so rendering and embedding don't fight over the CPU. A
# second job waits its turn; the UI only offers one upload or retry at a time anyway. The queue
# is in memory, so a restart loses the job (`fail_interrupted_reports` marks it failed); a real
# queue (arq, RQ) if jobs must survive restarts or run on more workers.
_PROCESSING_QUEUE = ThreadPoolExecutor(max_workers=1)


class ReportService:
    """Adds Reports, from the PDF check to their Facts.

    Plain reads of what upload stored go through `ReportRepository` instead.
    """

    def __init__(
        self,
        repository: ReportRepository,
        pdf_extractor: PdfExtractor,
        retriever: Retriever,
        fact_extractor: FactExtractor,
    ) -> None:
        """Create the service.

        Args:
            repository: Where reports are stored.
            pdf_extractor: Extracts a PDF's text.
            retriever: Embeds the Passages, and finds them for fact extraction.
            fact_extractor: Reads the FTE and Sustainability Goals out of a report.
        """
        self._repository = repository
        self._pdf_extractor = pdf_extractor
        self._retriever = retriever
        self._fact_extractor = fact_extractor

    def add(
        self,
        company_name: str,
        reporting_year: int,
        content: bytes,
        original_filename: str | None,
        on_duplicate: OnDuplicate | None,
    ) -> Report:
        """Add a report: check and store its PDF, then process it in the background.

        Only the quick checks run here. Processing (text, pages, embeddings, then Facts) takes
        minutes for a long report and runs as a background job; the report's status says how
        far it got. A replaced report loses its old content as soon as the new PDF is stored.

        Args:
            company_name: The Company, as entered by the user.
            reporting_year: The Reporting Year.
            content: The PDF bytes.
            original_filename: The uploaded file's name, kept in the metadata for reference.
            on_duplicate: What to do when a report for this Company and Reporting Year is
                stored; None raises `SameCompanyYearError` so the user can choose.

        Returns:
            The stored report, processing.

        Raises:
            NotAPdfError: The file isn't a PDF.
            SameFileError: The same PDF is already stored, whatever `on_duplicate` says.
            SameCompanyYearError: A report for this Company and year is stored and
                `on_duplicate` is None.
            StillProcessingError: The user chose to replace a report that is still processing,
                whose job would otherwise save the old PDF's contents over the new one.
            UnreadablePdfError: pdfium can't open the PDF.
        """
        if not content.startswith(_PDF_MAGIC):
            raise NotAPdfError
        reports = self._repository.list()  # once: each call reads every report's metadata
        sha256 = hashlib.sha256(content).hexdigest()
        if same_file := next((r for r in reports if r.sha256 == sha256), None):
            raise SameFileError(same_file)
        # A Company keeps the spelling it was first entered with: "shell" is stored as "Shell".
        same_company_reports = [
            r for r in reports if r.company_name.casefold() == company_name.casefold()
        ]
        existing = next(
            (r for r in same_company_reports if r.reporting_year == reporting_year), None
        )
        if existing and on_duplicate is None:
            raise SameCompanyYearError(existing)
        should_replace = existing is not None and on_duplicate is OnDuplicate.REPLACE
        if should_replace and existing and existing.is_processing:
            raise StillProcessingError(existing)
        try:
            pages = page_count(content)
        except ExtractionError as error:
            raise UnreadablePdfError from error
        report = self._repository.create(
            company_name=same_company_reports[0].company_name
            if same_company_reports
            else company_name,
            reporting_year=reporting_year,
            content=content,
            pages=pages,
            original_filename=original_filename,
            report_id=existing.report_id if should_replace and existing else None,
        )
        _PROCESSING_QUEUE.submit(self._process_report, report, content)
        return report

    def retry(self, report_id: UUID) -> Report:
        """Process a failed report again, from its stored PDF.

        Args:
            report_id: The report. It must exist.

        Returns:
            The report, processing.

        Raises:
            NotFailedError: The report didn't fail.
        """
        report = self._repository.get(report_id)
        if report is None or report.status is not ReportStatus.FAILED:
            raise NotFailedError
        report = self._repository.set_status(report_id, ReportStatus.PROCESSING)
        _PROCESSING_QUEUE.submit(self._process_report, report, self._repository.pdf(report_id))
        return report

    def _process_report(self, report: Report, pdf: bytes) -> None:
        # The background job. Anything it raises would be lost in the executor, so it records
        # every failure on the report instead.
        report_id = report.report_id
        started = time.perf_counter()
        try:
            with _log_duration(report, "text extraction"):
                passages = split_into_passages(self._pdf_extractor.extract(pdf))
            with _log_duration(report, f"embedding {len(passages)} passages"):
                embeddings = self._retriever.embed(passages)
            with _log_duration(report, f"rendering {report.pages} pages"):
                images = render_pages(pdf)
            with _log_duration(report, "saving"):
                self._repository.save_contents(report_id, images, passages, embeddings)
            with _log_duration(report, "fact extraction"):
                facts = self._fact_extractor.extract(
                    report, lambda query, limit: self._retriever.search(report_id, query, limit)
                )
            self._repository.save_facts(report_id, facts)
            self._repository.set_status(report_id, ReportStatus.SUCCESS)
            logger.info(
                "%s: processed in %.1f s", _log_label(report), time.perf_counter() - started
            )
        except ExtractionError:
            logger.warning("Couldn't extract the text of %s", report_id, exc_info=True)
            self._repository.set_status(
                report_id, ReportStatus.FAILED, ReportFailure.UNREADABLE_PDF
            )
        except LLMError:
            logger.warning("Couldn't extract the facts of %s", report_id, exc_info=True)
            self._repository.set_status(report_id, ReportStatus.FAILED, ReportFailure.FACTS_FAILED)
        except Exception:
            logger.exception("Processing %s failed", report_id)
            self._repository.set_status(report_id, ReportStatus.FAILED, ReportFailure.UNEXPECTED)


@contextmanager
def _log_duration(report: Report, step: str) -> Iterator[None]:
    # Logs how long a processing step took, also when it fails: how long it ran before failing.
    start = time.perf_counter()
    try:
        yield
    finally:
        logger.info("%s: %s took %.1f s", _log_label(report), step, time.perf_counter() - start)


def _log_label(report: Report) -> str:
    return f"{report.company_name} {report.reporting_year} ({report.report_id})"


def fail_interrupted_reports(repository: ReportRepository) -> None:
    """Mark reports left processing by a restart as failed, so the user can retry them.

    Call it at start-up, before any job runs. Assumes one app process; with several workers,
    one would fail the others' running jobs.

    Args:
        repository: Where reports are stored.
    """
    for report in repository.list():
        if report.is_processing:
            repository.set_status(report.report_id, ReportStatus.FAILED, ReportFailure.INTERRUPTED)
