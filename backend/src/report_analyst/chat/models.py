"""A Conversation: Questions, the reports each searched, and Answers backed by Evidence."""

from enum import StrEnum
from pydantic import BaseModel, Field
from typing import Literal
from uuid import UUID, uuid4

from report_analyst.domain import Evidence


class ReportRef(BaseModel):
    """A stored report, named the way the UI shows it.

    Attributes:
        report_id: The report's id.
        company_name: Its Company.
        reporting_year: Its Reporting Year.
    """

    report_id: UUID
    company_name: str
    reporting_year: int


class ChatEvidence(Evidence):
    """Evidence for an Answer, naming its report, since one Question can search several.

    Attributes:
        report_id: The report the quote is from.
        company_name: Its Company.
        reporting_year: Its Reporting Year.
    """

    report_id: UUID
    company_name: str
    reporting_year: int


class NotFoundReason(StrEnum):
    """Why a Question has no Answer."""

    NOT_IN_REPORT = "not_in_report"
    """The reports' extracted Facts don't state it, or the answer cited none of them."""
    REPORT_NOT_READY = "report_not_ready"
    """The reports asked about are still processing or failed."""
    NO_REPORT = "no_report"
    """No report is stored yet."""
    NO_MATCHING_REPORT = "no_matching_report"
    """The Question names a Company or year that no stored report has; see `missing`."""
    UNSUPPORTED_TOPIC = "unsupported_topic"
    """The Question isn't about the FTE or the Sustainability Goals, the only Facts kept."""


class Answer(BaseModel):
    """What the user sees for a Question: an answer with Evidence, or Not Found with a reason.

    Attributes:
        kind: Whether the reports answered it.
        text: Claude's plain text, never HTML; "" for a Not Found the app decided without
            asking Claude, which the UI words from `reason`.
        evidence: At least one for an answer; none for Not Found.
        reason: Why it wasn't found; None for an answer.
        missing: For `no_matching_report`, what the Question names that isn't stored, e.g.
            "ABN AMRO 2023"; empty otherwise.
    """

    kind: Literal["answer", "not_found"]
    text: str
    evidence: list[ChatEvidence] = []
    reason: NotFoundReason | None = None
    missing: list[str] = []


class Turn(BaseModel):
    """One Question and its Answer.

    Attributes:
        question: As the user typed it.
        reports: The reports the Question was matched to and answered from; empty if none
            matched.
        answer: The Answer.
    """

    question: str
    reports: list[ReportRef] = []
    answer: Answer


class Conversation(BaseModel):
    """The Turns of one chat, oldest first. Stored, so it survives a restart.

    Attributes:
        conversation_id: The conversation's id.
        turns: The Turns.
    """

    conversation_id: UUID = Field(default_factory=uuid4)
    turns: list[Turn] = []


class ChatReply(Turn):
    """The reply to a Question: its Turn, and the Conversation it was added to.

    Attributes:
        conversation_id: The conversation, new if the Question started one.
    """

    conversation_id: UUID
