"""Groups a report's Blocks into Passages for search."""

from report_analyst.domain import Passage
from report_analyst.pdf import Block, BlockKind


def split_into_passages(blocks: list[Block], max_words: int = 250) -> list[Passage]:
    """Group consecutive Blocks into Passages of up to `max_words` words.

    A Passage never spans two pages, so its Evidence has exactly one page number. A heading
    starts a new Passage and labels the ones after it, across pages, until the next heading.

    Args:
        blocks: The report's Blocks, in reading order.
        max_words: The size a Passage grows to before a new one starts. A single Block longer
            than this, such as a table, stays whole.

    Returns:
        The Passages, in reading order, indexed from 0.
    """
    passages: list[Passage] = []
    heading = ""
    current_blocks: list[Block] = []

    def close_passage() -> None:
        if current_blocks:
            passages.append(
                Passage(
                    index=len(passages),
                    page=current_blocks[0].page,
                    heading=heading,
                    blocks=list(current_blocks),
                )
            )
            current_blocks.clear()

    for block in blocks:
        if block.kind is BlockKind.HEADING:
            close_passage()
            heading = block.text
            continue
        if current_blocks and (
            block.page != current_blocks[0].page
            or _word_count(current_blocks) + _word_count([block]) > max_words
        ):
            close_passage()
        current_blocks.append(block)
    close_passage()
    return passages


def _word_count(blocks: list[Block]) -> int:
    return sum(len(b.text.split()) for b in blocks)
