"""What a PDF's text is extracted as: Blocks of text, each with its box on the page."""

from enum import StrEnum
from pydantic import BaseModel


class ExtractionError(Exception):
    """The file couldn't be read as a PDF: it is broken, truncated or not a PDF at all."""


class PageBox(BaseModel):
    """A rectangle on a page, as fractions of the page size from its top-left corner.

    Attributes:
        x: The left edge, 0 to 1.
        y: The top edge, 0 to 1.
        width: The width, 0 to 1.
        height: The height, 0 to 1.
    """

    x: float
    y: float
    width: float
    height: float


class BlockKind(StrEnum):
    """What a Block is, as far as splitting text into Passages cares."""

    HEADING = "heading"
    TEXT = "text"
    """A paragraph, list item, caption or footnote."""
    TABLE = "table"


class Block(BaseModel):
    """One element of a page's text, in reading order: a heading, a paragraph or a table.

    Attributes:
        page: The page it's on, starting at 1.
        kind: What it is.
        text: The text. Tables are Markdown tables; headings are plain text.
        box: Where it is on its page.
    """

    page: int
    kind: BlockKind
    text: str
    box: PageBox
