import pytest
from pydantic import ValidationError

from report_analyst.domain import Passage
from report_analyst.facts.model_output import PASSAGES_CONTEXT_KEY
from report_analyst.facts.model_output import FactsOutput
from report_analyst.pdf import Block, BlockKind, PageBox

BOX = PageBox(x=0.1, y=0.2, width=0.5, height=0.1)
OTHER_BOX = PageBox(x=0.1, y=0.5, width=0.5, height=0.1)
PASSAGES = {
    4: Passage(
        index=4,
        page=7,
        heading="People",
        blocks=[
            Block(page=7, kind=BlockKind.TEXT, text="We employed **12,345** FTEs.", box=BOX),
            Block(page=7, kind=BlockKind.TEXT, text="Headcount was 13,000.", box=OTHER_BOX),
        ],
    ),
}


def answer(passage_id: int, quote: str) -> dict:
    return {"fte": {"amount": 12345, "citation": {"passage_id": passage_id, "quote": quote}}}


def test_citation_becomes_evidence_with_the_passages_page_and_boxes() -> None:
    validated = FactsOutput.model_validate(
        answer(4, "We employed 12,345 FTEs."),  # markup in the passage is ignored
        context={PASSAGES_CONTEXT_KEY: PASSAGES},
    )

    facts = validated.to_facts(PASSAGES)

    assert facts.fte is not None
    assert facts.fte.evidence.model_dump() == {
        "page": 7,
        "quote": "We employed 12,345 FTEs.",
        "boxes": [BOX.model_dump()],  # only the paragraph holding the quote
    }


def test_quote_across_blocks_highlights_the_whole_passage() -> None:
    assert PASSAGES[4].boxes_of("12,345 FTEs. Headcount was") == [BOX, OTHER_BOX]


def test_unknown_passage_is_rejected_for_a_retry() -> None:
    with pytest.raises(ValidationError, match="There's no passage 5"):
        FactsOutput.model_validate(
            answer(5, "We employed 12,345 FTEs."), context={PASSAGES_CONTEXT_KEY: PASSAGES}
        )


@pytest.mark.parametrize("quote", ["We employed 12,000 FTEs.", "  "])
def test_fact_whose_quote_isnt_in_its_passage_is_dropped(quote: str) -> None:
    goal = {"title": "Net zero", "citation": {"passage_id": 4, "quote": "We employed 12,345 FTEs."}}
    validated = FactsOutput.model_validate(
        {**answer(4, quote), "goals": [goal]}, context={PASSAGES_CONTEXT_KEY: PASSAGES}
    )

    facts = validated.to_facts(PASSAGES)

    assert facts.fte is None  # dropped
    assert [g.title for g in facts.goals] == ["Net zero"]  # the others are kept
