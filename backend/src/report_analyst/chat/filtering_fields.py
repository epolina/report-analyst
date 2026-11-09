"""What Claude reads out of a Question: which Fact it asks about, for which Companies and years.

Instructor sends each `Field(description=...)` as the response schema. Claude is shown the
stored reports, so it writes their Companies as stored ("ABN" becomes "ABN AMRO"); matching
the pairs to reports is then an exact comparison in code.
"""

from pydantic import BaseModel, Field

from report_analyst.chat.models import Turn
from report_analyst.domain import FactKind, Report


_EARLIER_QUESTIONS_IN_PROMPT = 3  # so a follow-up ("and in 2025?") keeps its Company

_FILTERING_FIELDS_PROMPT = """\
These annual reports are stored, one per line as Company, Reporting Year:

{stored_reports}

{earlier_questions}Question: {question}

Read from the question:
1. fact: "fte" if it asks about the number of employees or full-time equivalents,
   "sustainability_goals" if it asks about sustainability targets or goals (emissions, energy,
   water, diversity, safety...), or null if it asks about anything else (revenue, strategy,
   spending...).
2. company_year_pairs: each Company and Reporting Year it asks about. Write the Company as it
   is stored above when the question clearly means it, by a short form or another spelling
   ("ABN" is "ABN AMRO"); otherwise as the question writes it. A Company named without a year
   means its latest stored year. A follow-up such as "and in 2025?" keeps the Company of the
   earlier questions. If no Company is named here or earlier, leave the list empty."""


class CompanyYearPair(BaseModel):
    """A Company and Reporting Year the Question asks about."""

    company_name: str = Field(description="The Company, as stored when it is a stored one.")
    reporting_year: int = Field(description="The Reporting Year.")


class FilteringFields(BaseModel):
    """What the Question asks about, to find its Facts: the Fact, and each Company and year."""

    fact: FactKind | None = Field(
        default=None, description="The Fact asked about; null for anything else."
    )
    company_year_pairs: list[CompanyYearPair] = Field(
        default=[], description="Each Company and Reporting Year the question asks about."
    )


def build_filtering_fields_prompt(
    question: str, history: list[Turn], stored_reports: list[Report]
) -> str:
    """Build the prompt that reads the FilteringFields out of a Question.

    Args:
        question: The Question.
        history: The Conversation's earlier Turns, oldest first.
        stored_reports: Every stored report, so Claude writes their Companies as stored.

    Returns:
        The prompt.
    """
    return _FILTERING_FIELDS_PROMPT.format(
        stored_reports="\n".join(f"{r.company_name}, {r.reporting_year}" for r in stored_reports),
        earlier_questions="".join(
            f"Earlier question: {turn.question}\n"
            for turn in history[-_EARLIER_QUESTIONS_IN_PROMPT:]
        ),
        question=question,
    )
