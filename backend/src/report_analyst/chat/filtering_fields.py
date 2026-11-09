"""What Claude reads out of a Question: which Fact it asks about, for which Companies and years.

Instructor sends each `Field(description=...)` as the response schema. Claude is shown the
stored reports, so it writes their Companies as stored ("ABN" becomes "ABN AMRO"); matching
the pairs to reports is then an exact comparison in code.
"""

from enum import StrEnum
from pydantic import BaseModel, Field

from report_analyst.chat.models import Turn
from report_analyst.domain import Facts, Fte, Report, SustainabilityGoal
from report_analyst.llm import AnthropicLLM


_EARLIER_QUESTIONS_IN_PROMPT = 3  # so a follow-up ("and in 2025?") keeps its Company

_FILTERING_FIELDS_PROMPT = """\
These annual reports are stored, one per line as Company, Reporting Year:

{stored_reports}

{earlier_questions}Question: {question}

Read from the question:
1. fact: which of these the question asks about, or null if it asks about anything else
   (revenue, strategy, spending...):
{fact_kinds}
2. company_year_pairs: each Company and Reporting Year it asks about. Write the Company as it
   is stored above when the question clearly means it, by a short form or another spelling
   ("ABN" is "ABN AMRO"); otherwise as the question writes it. A Company named without a year
   means its latest stored year. A follow-up such as "and in 2025?" keeps the Company of the
   earlier questions. If no Company is named here or earlier, leave the list empty."""


class FactKind(StrEnum):
    """The kinds of Facts extracted from every report, and so the only ones the chat answers."""

    FTE = "fte"
    SUSTAINABILITY_GOALS = "sustainability_goals"

    @property
    def fact_class(self) -> type[Fte] | type[SustainabilityGoal]:
        """The class of the Facts of this kind, whose `description` Claude reads.

        Returns:
            `Fte` or `SustainabilityGoal`.
        """
        return Fte if self is FactKind.FTE else SustainabilityGoal

    def facts_in(self, facts: Facts) -> list[Fte] | list[SustainabilityGoal]:
        """The Facts of this kind among a report's Facts: its FTE, or all its goals.

        Args:
            facts: A report's Facts.

        Returns:
            The Facts of this kind; empty if the report has none.
        """
        if self is FactKind.FTE:
            return [facts.fte] if facts.fte else []
        return facts.goals


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


def extract_filtering_fields(
    llm: AnthropicLLM, question: str, history: list[Turn], stored_reports: list[Report]
) -> FilteringFields:
    """Ask Claude which Fact a Question asks about, for which Company and year pairs.

    Args:
        llm: Claude.
        question: The Question.
        history: The Conversation's earlier Turns, oldest first, so a follow-up keeps its
            Company.
        stored_reports: Every stored report, so Claude writes their Companies as stored.

    Returns:
        The FilteringFields: `fact` is None when the Question isn't about a Fact, and
        `company_year_pairs` empty when it names no Company.

    Raises:
        LLMError: The model call failed or gave no valid answer.
    """
    prompt = _build_prompt(question, history, stored_reports)
    return llm.complete(prompt=prompt, schema=FilteringFields)


def _build_prompt(question: str, history: list[Turn], stored_reports: list[Report]) -> str:
    return _FILTERING_FIELDS_PROMPT.format(
        stored_reports="\n".join(f"{r.company_name}, {r.reporting_year}" for r in stored_reports),
        fact_kinds="\n".join(f'   - "{kind}": {kind.fact_class.description}' for kind in FactKind),
        earlier_questions="".join(
            f"Earlier question: {turn.question}\n"
            for turn in history[-_EARLIER_QUESTIONS_IN_PROMPT:]
        ),
        question=question,
    )
