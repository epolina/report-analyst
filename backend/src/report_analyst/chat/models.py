"""A Conversation: Questions, the scope each searched, and Answers backed by Evidence."""

from enum import StrEnum
from pydantic import BaseModel, Field
from typing import Literal
from uuid import UUID, uuid4

from report_analyst.domain import Evidence


class Scope(BaseModel):
    """Which reports a Question searches. None means any.

    Attributes:
        company: The Company.
        reporting_year: The Reporting Year.
    """

    company: str | None = None
    reporting_year: int | None = None


class ChatEvidence(Evidence):
    """Evidence for an Answer, naming its report, since one Question can search several.

    Attributes:
        report_id: The report the quote is from.
        company_name: Its Company.
        year: Its Reporting Year.
    """

    report_id: UUID
    company_name: str
    year: int


class NotFoundReason(StrEnum):
    """Why a Question has no Answer."""

    NOT_IN_REPORT = "not_in_report"
    """The searched reports don't state it, or the quote couldn't be verified."""
    REPORT_NOT_READY = "report_not_ready"
    """The reports in scope are still processing or failed."""
    NO_REPORT = "no_report"
    """No report matches the scope."""


class Answer(BaseModel):
    """What the user sees for a Question: an answer with Evidence, or Not Found with a reason.

    Attributes:
        kind: Whether the reports answered it.
        text: Claude's plain text, never HTML; "" for a Not Found the app decided without
            asking Claude, which the UI words from `reason`.
        evidence: At least one for an answer; none for Not Found.
        reason: Why it wasn't found; None for an answer.
    """

    kind: Literal["answer", "not_found"]
    text: str
    evidence: list[ChatEvidence] = []
    reason: NotFoundReason | None = None


class Turn(BaseModel):
    """One Question and its Answer.

    Attributes:
        question: As the user typed it.
        scope: The scope it searched, after reading the Company and year from the Question.
        answer: The Answer.
    """

    question: str
    scope: Scope
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
