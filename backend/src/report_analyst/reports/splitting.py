"""Groups a report's Blocks into Passages for search."""

from report_analyst.domain import Passage
from report_analyst.pdf import Block, BlockKind


def split(blocks: list[Block], max_words: int = 250) -> list[Passage]:
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
    group: list[Block] = []

    def flush() -> None:
        if group:
            passages.append(
                Passage(
                    index=len(passages),
                    page=group[0].page,
                    heading=heading,
                    blocks=list(group),
                )
            )
            group.clear()

    for block in blocks:
        if block.kind is BlockKind.HEADING:
            flush()
            heading = block.text
            continue
        if group and (block.page != group[0].page or _words(group) + _words([block]) > max_words):
            flush()
        group.append(block)
    flush()
    return passages


def _words(blocks: list[Block]) -> int:
    return sum(len(b.text.split()) for b in blocks)
