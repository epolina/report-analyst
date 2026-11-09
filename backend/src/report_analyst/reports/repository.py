"""Stores annual reports on disk: one folder per report with everything derived from its PDF."""

import hashlib
import io
import numpy as np
import shutil

from pathlib import Path
from pydantic import TypeAdapter
from uuid import UUID, uuid4

from report_analyst.domain import Facts, Passage, Report, ReportFailure, ReportStatus
from report_analyst.embedder import Vectors
from report_analyst.storage import write_atomic


# The storage layout belongs to the repository alone; nothing outside it names these files.
_PDF_FILE = "upload.pdf"
_PASSAGES_FILE = "passages.json"
_EMBEDDINGS_FILE = "embeddings.npy"  # row i embeds passage i
_METADATA_FILE = "metadata.json"
_FACTS_FILE = "facts.json"
_PAGE_IMAGES_DIR = "page-images"  # <n>.jpg
_PASSAGE_LIST = TypeAdapter(list[Passage])


class _StoredReport(Report):
    """What `metadata.json` holds: the report plus the uploaded file's original name.

    The original name is kept for reference only. It is never shown and never used as a path.
    """

    original_filename: str | None


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _to_report(stored: _StoredReport) -> Report:
    return Report.model_validate(stored.model_dump(exclude={"original_filename"}))


class ReportRepository:
    """Annual reports, one folder each, holding the PDF and everything derived from it.

    That is the extracted Blocks, the page images, the Passages and their embeddings, and the
    metadata. `create` stores the PDF and metadata; processing adds the rest with
    `save_contents`, so a report still processing has no Passages or pages yet.
    """

    def __init__(self, reports_dir: Path) -> None:
        """Create the repository, making the folder if it is missing.

        Args:
            reports_dir: The folder that holds one sub-folder per report.
        """
        self._reports_dir = reports_dir
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        company_name: str,
        reporting_year: int,
        content: bytes,
        page_count: int,
        original_filename: str | None,
        report_id: UUID | None = None,
    ) -> Report:
        """Store a PDF as a new report, or over an existing one, ready to be processed.

        A replaced report loses everything derived from its old PDF here, before processing.

        Args:
            company_name: The Company, spelled as it is stored.
            reporting_year: The Reporting Year.
            content: The PDF bytes.
            page_count: The number of pages.
            original_filename: The uploaded file's name, kept in the metadata for reference.
            report_id: The report to replace; None creates a new report.

        Returns:
            The stored report, processing.
        """
        stored = _StoredReport(
            report_id=report_id or uuid4(),
            company_name=company_name,
            reporting_year=reporting_year,
            sha256=_sha256(content),
            page_count=page_count,
            status=ReportStatus.PROCESSING,
            original_filename=original_filename,
        )
        folder = self._reports_dir / str(stored.report_id)
        folder.mkdir(exist_ok=True)
        # A replaced PDF has other text, pages and facts; the old ones must not be served.
        shutil.rmtree(folder / _PAGE_IMAGES_DIR, ignore_errors=True)
        for name in (_FACTS_FILE, _PASSAGES_FILE, _EMBEDDINGS_FILE):
            (folder / name).unlink(missing_ok=True)
        # Metadata last: a report with metadata always has its PDF.
        write_atomic(folder / _PDF_FILE, content)
        self._write_metadata(stored)
        return _to_report(stored)

    def save_contents(
        self,
        report_id: UUID,
        images: list[bytes],
        passages: list[Passage],
        embeddings: Vectors,
    ) -> None:
        """Store everything processing derives from a report's PDF.

        Args:
            report_id: The report's id. It must exist.
            images: Each page as a JPEG image, in order; one per page.
            passages: The text extracted from the PDF, grouped for search.
            embeddings: One row per passage, in the same order.
        """
        folder = self._reports_dir / str(report_id)
        (folder / _PAGE_IMAGES_DIR).mkdir(exist_ok=True)
        for number, image in enumerate(images, start=1):
            write_atomic(folder / _PAGE_IMAGES_DIR / f"{number}.jpg", image)
        self._write_index(folder, passages, embeddings)

    def set_status(
        self, report_id: UUID, status: ReportStatus, failure: ReportFailure | None = None
    ) -> Report:
        """Record where a report is in processing.

        Args:
            report_id: The report's id. It must exist.
            status: The new status.
            failure: Why processing failed, for a failed report; cleared otherwise.

        Returns:
            The updated report.
        """
        path = self._reports_dir / str(report_id) / _METADATA_FILE
        stored = _StoredReport.model_validate_json(path.read_bytes())
        stored = stored.model_copy(update={"status": status, "failure": failure})
        self._write_metadata(stored)
        return _to_report(stored)

    def pdf(self, report_id: UUID) -> bytes:
        """Get a stored report's PDF.

        Args:
            report_id: The report's id. It must exist.

        Returns:
            The PDF bytes.
        """
        return (self._reports_dir / str(report_id) / _PDF_FILE).read_bytes()

    def get(self, report_id: UUID) -> Report | None:
        """Get a stored report.

        Args:
            report_id: The report's id.

        Returns:
            The report, or None if there's no such report.
        """
        path = self._reports_dir / str(report_id) / _METADATA_FILE
        return Report.model_validate_json(path.read_bytes()) if path.exists() else None

    def passages(self, report_id: UUID) -> list[Passage]:
        """Get a processed report's Passages.

        Args:
            report_id: The report's id. Its Passages must be saved.

        Returns:
            The Passages by index.
        """
        return _PASSAGE_LIST.validate_json(
            (self._reports_dir / str(report_id) / _PASSAGES_FILE).read_bytes()
        )

    def passages_version(self, report_id: UUID) -> int | None:
        """Tell whether a report's Passages changed, e.g. to refresh a cache of them.

        Args:
            report_id: The report's id.

        Returns:
            A number that changes whenever the Passages are saved again; None if there are none.
        """
        path = self._reports_dir / str(report_id) / _PASSAGES_FILE
        return path.stat().st_mtime_ns if path.exists() else None

    def embeddings(self, report_id: UUID) -> Vectors:
        """Get the embeddings of a processed report's Passages.

        Args:
            report_id: The report's id. Its Passages must be saved.

        Returns:
            One row per passage.
        """
        vectors: Vectors = np.load(self._reports_dir / str(report_id) / _EMBEDDINGS_FILE)
        return vectors

    def facts(self, report_id: UUID) -> Facts | None:
        """Get a report's stored Facts.

        Args:
            report_id: The report's id.

        Returns:
            The Facts, or None if none are saved yet.
        """
        path = self._reports_dir / str(report_id) / _FACTS_FILE
        return Facts.model_validate_json(path.read_bytes()) if path.exists() else None

    def save_facts(self, report_id: UUID, facts: Facts) -> None:
        """Save a report's Facts. They're deleted when the report is replaced.

        Args:
            report_id: The report's id. It must exist.
            facts: The Facts.
        """
        write_atomic(
            self._reports_dir / str(report_id) / _FACTS_FILE,
            facts.model_dump_json(indent=2).encode(),
        )

    def page_image(self, report_id: UUID, page_number: int) -> bytes | None:
        """Get a page image.

        Args:
            report_id: The report's id.
            page_number: The page number, starting at 1.

        Returns:
            The JPEG bytes, or None if there's no such report or page.
        """
        path = self._reports_dir / str(report_id) / _PAGE_IMAGES_DIR / f"{page_number}.jpg"
        return path.read_bytes() if path.exists() else None

    def _write_metadata(self, stored: _StoredReport) -> None:
        write_atomic(
            self._reports_dir / str(stored.report_id) / _METADATA_FILE,
            stored.model_dump_json(indent=2).encode(),
        )

    @staticmethod
    def _write_index(folder: Path, passages: list[Passage], embeddings: Vectors) -> None:
        if len(passages) != len(embeddings):
            raise ValueError(f"{len(passages)} passages but {len(embeddings)} embeddings")
        vectors = io.BytesIO()
        np.save(vectors, embeddings)
        # Embeddings first: passages.json without its embeddings would mis-align search.
        write_atomic(folder / _EMBEDDINGS_FILE, vectors.getvalue())
        write_atomic(folder / _PASSAGES_FILE, _PASSAGE_LIST.dump_json(passages, indent=2))

    def list(self) -> list[Report]:
        """List the stored reports.

        Returns:
            The reports, by Company and then year.
        """
        # Reads every metadata file on each call; fine for tens of reports.
        # `Report` ignores the extra fields, such as the original file name.
        reports = [
            Report.model_validate_json(p.read_bytes())
            for p in self._reports_dir.glob(f"*/{_METADATA_FILE}")
        ]
        return sorted(reports, key=lambda r: (r.company_name.casefold(), r.reporting_year))
