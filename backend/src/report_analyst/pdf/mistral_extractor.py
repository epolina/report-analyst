"""The PdfExtractor interface, and its implementation with Mistral OCR, run by Mistral's API."""

from abc import ABC, abstractmethod
from mistralai.client import Mistral
from mistralai.client.models import OCRPageObject, UnknownBlock

from report_analyst.pdf.models import Block, BlockKind, PageBox


_MODEL = "mistral-ocr-latest"
_TIMEOUT_MS = 10 * 60 * 1000  # a 300-page report takes about 30 s; slack for a busy API
_SKIPPED = {"header", "footer", "image", "signature"}  # unknown types too, from a newer API
_KINDS = {"title": BlockKind.HEADING, "table": BlockKind.TABLE}  # the rest is text


class PdfExtractor(ABC):
    """Reads a PDF's text. Knows nothing about reports.

    Each implementation extracts text its own way, and says where each Block is. The PDF must
    be one pdfium can open.
    """

    @abstractmethod
    def extract(self, pdf: bytes) -> list[Block]:
        """Extract the text as Blocks: headings, paragraphs and tables.

        Args:
            pdf: The PDF bytes.

        Returns:
            The Blocks, in reading order.
        """


class MistralExtractor(PdfExtractor):
    """Extracts the text with Mistral OCR, which reads tables well and boxes each Block.

    The PDF is sent to Mistral's API. Page headers, footers and pictures are left out.
    """

    def __init__(self, api_key: str) -> None:
        """Create the client.

        Args:
            api_key: The Mistral API key.
        """
        self._client = Mistral(api_key=api_key, timeout_ms=_TIMEOUT_MS)

    def extract(self, pdf: bytes) -> list[Block]:
        """Extract the text as Blocks: headings, paragraphs and tables, with their boxes.

        Args:
            pdf: The PDF bytes.

        Returns:
            The Blocks, in reading order.
        """
        # Uploaded, not sent inline: a 40 MB report is over the request limit as base64.
        file = self._client.files.upload(
            file={"file_name": "report.pdf", "content": pdf}, purpose="ocr"
        )
        try:
            response = self._client.ocr.process(
                model=_MODEL,
                document={"type": "file", "file_id": file.id},
                table_format="markdown",
                extract_header=True,
                extract_footer=True,
            )
        finally:
            self._client.files.delete(file_id=file.id)
        return [block for page in response.pages for block in _blocks(page)]


def _blocks(page: OCRPageObject) -> list[Block]:
    width, height = page.dimensions.width, page.dimensions.height  # type: ignore[union-attr]
    blocks = []
    for b in page.blocks or []:
        if isinstance(b, UnknownBlock) or b.type in _SKIPPED or not b.content.strip():
            continue
        kind = _KINDS.get(b.type, BlockKind.TEXT)
        text = b.content.lstrip("#").strip() if kind == BlockKind.HEADING else b.content.strip()
        box = PageBox(
            x=b.top_left_x / width,
            y=b.top_left_y / height,
            width=(b.bottom_right_x - b.top_left_x) / width,
            height=(b.bottom_right_y - b.top_left_y) / height,
        )
        blocks.append(Block(page=page.index + 1, kind=kind, text=text, box=box))
    return blocks
