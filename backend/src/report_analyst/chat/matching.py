"""Step 1 of a Question: which stored reports it is about, and whether it is about the Facts.

Claude reads the Question, the last Turns and the list of stored reports, and answers with a
`ReportMatch`. Instructor sends each `Field(description=...)` as the response schema. An id
that isn't in the list fails validation, so the model tries again; the valid ids come from
the validation context as `{"report_ids": set[UUID]}`.
"""

from enum import StrEnum
from pydantic import BaseModel, Field, ValidationInfo, model_validator
from typing import Self
from uuid import UUID

from report_analyst.chat.models import Turn
from report_analyst.domain import Report


REPORT_IDS_CONTEXT_KEY = "report_ids"
_HISTORY_TURNS_IN_PROMPT = 3

_PROMPT_TEMPLATE = """\
You route questions about companies' annual reports. These reports are stored, one per line
as id: Company, Reporting Year:

{reports}

{history}Question: {question}

Decide:
1. report_ids: the ids of the reports the question is about. Match Companies loosely, by any
   clear short form or spelling ("ABN" is "ABN AMRO", "shell" is "Shell"), and a Company
   named without a year to its latest stored report. A follow-up such as "and in 2025?" is
   about the Company of the earlier questions. If the question and the earlier questions
   name no Company, it is about all the stored reports.
2. missing: each Company or Company and year the question names that has no stored report,
   as the user would say it, e.g. "ABN AMRO 2023" or "Heineken". Empty if all are stored.
3. topic: "fte" for the number of employees or full-time equivalents, "sustainability_goals"
   for sustainability targets or goals (emissions, energy, water, diversity, safety...), and
   "other" for anything else, such as revenue, strategy or spending."""


class Topic(StrEnum):
    """What a Question asks about. Only the FTE and the Sustainability Goals are extracted."""

    FTE = "fte"
    SUSTAINABILITY_GOALS = "sustainability_goals"
    OTHER = "other"


class ReportMatch(BaseModel):
    """Which stored reports a Question is about, what it names that isn't stored, its topic."""

    report_ids: list[UUID] = Field(
        default=[], description="The ids of the stored reports the question is about."
    )
    missing: list[str] = Field(
        default=[],
        description="Each Company, or Company and year, the question names that isn't stored.",
    )
    topic: Topic = Field(default=Topic.OTHER, description="What the question asks about.")

    @model_validator(mode="after")
    def _check_report_ids(self, info: ValidationInfo) -> Self:
        if info.context is not None:
            unknown = set(self.report_ids) - info.context[REPORT_IDS_CONTEXT_KEY]
            if unknown:
                raise ValueError(
                    f"There's no stored report {', '.join(map(str, unknown))}. "
                    "Use only ids from the list."
                )
        return self


def build_match_prompt(question: str, history: list[Turn], reports: list[Report]) -> str:
    """Build the prompt that matches a Question to the stored reports.

    Args:
        question: The Question.
        history: The Conversation's earlier Turns, oldest first.
        reports: The stored reports.

    Returns:
        The prompt.
    """
    return _PROMPT_TEMPLATE.format(
        reports="\n".join(f"{r.report_id}: {r.company_name}, {r.reporting_year}" for r in reports),
        history="".join(
            f"Earlier question: {turn.question}\n" for turn in history[-_HISTORY_TURNS_IN_PROMPT:]
        ),
        question=question,
    )
