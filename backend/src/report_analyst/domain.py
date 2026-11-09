"""The domain objects: Report, Passage, Evidence and Facts. See UBIQUITOUS_LANGUAGE.md."""

import inspect
import re

from enum import StrEnum
from pydantic import BaseModel, computed_field
from uuid import UUID

from report_analyst.pdf import Block, PageBox


# Markdown and HTML in extracted text (bold, table pipes, headings, <sup>, <br>, comments).
_MARKUP_PATTERN = re.compile(r"<[^>]*>|[*_|#`]")


def strip_markup(text: str) -> str:
    """The text without Markdown and HTML, whitespace collapsed, for search and quote checks.

    Args:
        text: Extracted text.

    Returns:
        The plain text.
    """
    return " ".join(_MARKUP_PATTERN.sub(" ", text).split())


class ReportStatus(StrEnum):
    """Where a Report is in processing. Processing runs in the background after the upload."""

    PROCESSING = "processing"
    """Extracting the text, drawing the pages, embedding the Passages and finding the Facts."""
    SUCCESS = "success"
    FAILED = "failed"


class ReportFailure(StrEnum):
    """Why processing failed. The UI words it for the user."""

    UNREADABLE_PDF = "unreadable_pdf"
    """The text couldn't be extracted."""
    FACTS_FAILED = "facts_failed"
    """Claude couldn't extract the FTE and goals."""
    INTERRUPTED = "interrupted"
    """A restart stopped the job."""
    UNEXPECTED = "unexpected"
    """A bug; the log has it."""


class Report(BaseModel):
    """One Company's annual report for one Reporting Year.

    Attributes:
        report_id: The report's id. Kept when the report is replaced.
        company_name: The Company, spelled as it was first entered for any report.
        reporting_year: The Reporting Year.
        sha256: The SHA-256 hash of the PDF, to spot the same file uploaded again.
        page_count: The number of pages.
        status: Where it is in processing.
        failure: Why processing failed; None unless `status` is failed.
    """

    report_id: UUID
    company_name: str
    reporting_year: int
    sha256: str
    page_count: int
    status: ReportStatus
    failure: ReportFailure | None = None

    @property
    def is_processing(self) -> bool:
        """Whether a background job is extracting its text or Facts."""
        return self.status is ReportStatus.PROCESSING


class OnDuplicate(StrEnum):
    """What the user chose for an upload with the Company and year of a stored report."""

    REPLACE = "replace"
    """Overwrite the stored report, keeping its id."""
    KEEP_BOTH = "keep_both"
    """Store the upload as a new report, next to the stored one."""


class Passage(BaseModel):
    """A span of a Report's text: one or more paragraphs or tables from a single page.

    Attributes:
        index: Its position in the report, starting at 0. Also its row in the embeddings.
        page: The page it's on, starting at 1.
        heading: The section heading above it, possibly from an earlier page; "" if none.
        blocks: Its paragraphs and tables as extracted, each with where it is on the page.
    """

    index: int
    page: int
    heading: str
    blocks: list[Block]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def text(self) -> str:
        """The paragraphs and tables as extracted (Markdown), a blank line between them."""
        return "\n\n".join(b.text for b in self.blocks)

    def boxes_of(self, quote: str) -> list[PageBox]:
        """Where a quote from this Passage is on the page, to highlight it.

        Args:
            quote: Text from the Passage.

        Returns:
            The boxes of the paragraphs or tables that contain the quote, ignoring markup; all
            the Passage's boxes if it spans several.
        """
        quote = strip_markup(quote)
        blocks_with_quote = [b for b in self.blocks if quote and quote in strip_markup(b.text)]
        return [b.box for b in blocks_with_quote or self.blocks]

    @property
    def search_text(self) -> str:
        """The heading and text without Markdown, as keyword and embedding search read it."""
        return strip_markup(f"{self.heading}\n{self.text}")


class Evidence(BaseModel):
    """A verbatim quote from a Report, the page it is on and where on the page.

    Attributes:
        page: The page number, starting at 1.
        quote: The sentence or table row that states the fact, copied verbatim.
        boxes: Where the quote is: the boxes of the paragraph or table holding it, to highlight
            it.
    """

    page: int
    quote: str
    boxes: list[PageBox]


class Fte(BaseModel):
    """The Company's total FTE (not headcount) for the Reporting Year.

    Attributes:
        amount: The number of full-time equivalents.
        evidence: Where the report states it.
    """

    amount: float  # reports may give a fraction, e.g. 82,302.5
    evidence: Evidence

    def as_string(self) -> str:
        """Say what the Fact states, e.g. "FTE 88,497" or "FTE 82,302.5".

        Returns:
            The text, never in exponent notation.
        """
        amount = self.amount
        return f"FTE {amount:,.0f}" if amount.is_integer() else f"FTE {amount:,}"


class SustainabilityGoal(BaseModel):
    """A sustainability target the Company has set.

    Attributes:
        title: A short label for the user, e.g. "Net-zero Scope 1 and 2 emissions by 2030".
            Written by the model; the quote is the proof.
        deadline: The year the target must be met, if stated.
        baseline: The year it's measured against, if stated.
        evidence: Where the report states it.
    """

    title: str
    deadline: int | None = None
    baseline: int | None = None
    evidence: Evidence

    def as_string(self) -> str:
        """Say what the Fact states, e.g. "Sustainability goal: Net zero, deadline 2050".

        Returns:
            The title, with the deadline and baseline when the report states them.
        """
        parts = [f"Sustainability goal: {self.title}"]
        if self.deadline:
            parts.append(f"deadline {self.deadline}")
        if self.baseline:
            parts.append(f"baseline {self.baseline}")
        return ", ".join(parts)


class FactKind(StrEnum):
    """The kinds of Facts extracted from every report: the FTE and the Sustainability Goals."""

    FTE = "fte"
    SUSTAINABILITY_GOALS = "sustainability_goals"

    @property
    def description(self) -> str:
        """What a Fact of this kind is: the first line of its class's docstring.

        Returns:
            E.g. "The Company's total FTE (not headcount) for the Reporting Year."
        """
        fact_class = Fte if self is FactKind.FTE else SustainabilityGoal
        return (inspect.getdoc(fact_class) or "").splitlines()[0]


class Facts(BaseModel):
    """Everything extracted from one Report. Empty means the report states none of it.

    Attributes:
        fte: The total FTE, or None if the report doesn't give it.
        goals: The Sustainability Goals, each listed once.
    """

    fte: Fte | None = None
    goals: list[SustainabilityGoal] = []
