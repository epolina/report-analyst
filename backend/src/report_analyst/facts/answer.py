"""The Facts as the model writes them: each cites a Passage by its id.

Each rule is stated in a `Field(description=...)`, which Instructor sends to the model as the
response schema. A cited id that wasn't shown fails validation, so the model tries again; the
valid Passages come from the validation context as `{"passages": dict[int, Passage]}`. A quote
that isn't in its Passage only drops that fact; the rest of the answer stands.
"""

import logging

from pydantic import BaseModel, Field, ValidationInfo, model_validator
from typing import Self

from report_analyst.domain import Evidence, Facts, Fte, Passage, SustainabilityGoal, plain


logger = logging.getLogger(__name__)

PASSAGES_KEY = "passages"


class Citation(BaseModel):
    """Where a fact is stated: a Passage and a quote from it."""

    passage_id: int = Field(description="The id of the passage that states the fact.")
    quote: str = Field(
        description=(
            "The sentence or table row that states the fact, copied character for character "
            "from that passage. Never reworded, shortened mid-sentence or joined."
        )
    )

    @model_validator(mode="after")
    def _check_passage_id(self, info: ValidationInfo) -> Self:
        if info.context is not None and self.passage_id not in info.context[PASSAGES_KEY]:
            raise ValueError(
                f"There's no passage {self.passage_id}. Cite only ids of the passages shown."
            )
        return self

    def evidence(self, passages: dict[int, Passage]) -> Evidence | None:
        """Turn the citation into Evidence: the cited Passage's page and boxes, and the quote.

        Args:
            passages: The Passages the citation was checked against, by id.

        Returns:
            The Evidence, or None if the quote isn't in the Passage, ignoring markup.
        """
        passage = passages[self.passage_id]
        if not (quote := plain(self.quote)) or quote not in plain(passage.text):
            logger.warning(
                "Dropped a citation: quote not in passage %d: %r", passage.index, self.quote
            )
            return None
        return Evidence(page=passage.page, quote=self.quote, boxes=passage.boxes_of(self.quote))


class FteAnswer(BaseModel):
    """The Company's total FTE for the year."""

    amount: float = Field(description="The total number of full-time equivalents.")
    citation: Citation


class GoalAnswer(BaseModel):
    """A sustainability target the Company has set."""

    title: str = Field(description="What the goal is, in at most 10 words, with its target.")
    deadline: int | None = Field(None, description="The year it must be met, if stated.")
    baseline: int | None = Field(None, description="The year it's measured against, if stated.")
    citation: Citation


class FactsAnswer(BaseModel):
    """The facts found in the passages. Empty means none are stated."""

    fte: FteAnswer | None = None
    goals: list[GoalAnswer] = []

    def facts(self, passages: dict[int, Passage]) -> Facts:
        """Turn the answer into Facts, each with the Evidence of its citation.

        Args:
            passages: The Passages the answer was checked against, by id.

        Returns:
            The Facts whose quote is in the cited Passage; the others are dropped.
        """
        fte = None
        if self.fte and (evidence := self.fte.citation.evidence(passages)):
            fte = Fte(amount=self.fte.amount, evidence=evidence)
        goals = []
        for g in self.goals:
            evidence = g.citation.evidence(passages)
            if evidence:
                goals.append(
                    SustainabilityGoal(
                        title=g.title, deadline=g.deadline, baseline=g.baseline, evidence=evidence
                    )
                )
        return Facts(fte=fte, goals=goals)
