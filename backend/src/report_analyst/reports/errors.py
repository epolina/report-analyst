"""What can go wrong when adding a report."""

from report_analyst.domain import Report


class NotAPdfError(Exception):
    """The file doesn't start like a PDF."""


class UnreadablePdfError(Exception):
    """The PDF's text couldn't be extracted."""


class DuplicateError(Exception):
    """The upload duplicates a stored report. Nothing was saved.

    Attributes:
        existing: The stored report.
    """

    def __init__(self, existing: Report) -> None:
        """Create the error.

        Args:
            existing: The stored report the upload duplicates.
        """
        super().__init__(f"{existing.company_name} {existing.reporting_year}")
        self.existing = existing


class SameFileError(DuplicateError):
    """The exact same PDF is already stored. Replacing it would change nothing."""


class SameCompanyYearError(DuplicateError):
    """A report for this Company and Reporting Year is stored, and the user hasn't chosen yet."""


class StillProcessingError(DuplicateError):
    """The user chose to replace a stored report that is still processing."""


class NotFailedError(Exception):
    """Only a report whose processing failed can be retried."""
