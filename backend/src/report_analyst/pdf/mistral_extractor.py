"""The PdfExtractor interface, and its implementation with Mistral OCR, run by Mistral's API."""

from abc import ABC, abstractmethod
from mistralai.client import Mistral
from mistralai.client.models import OCRPageObject, UnknownBlock

from report_analyst.pdf.models import Block, BlockKind, PageBox


_OCR_MODEL = "mistral-ocr-latest"
_TIMEOUT_MS = 10 * 60 * 1000  # a 300-page report takes about 30 s; slack for a busy API
_SKIPPED_BLOCK_TYPES = {
    "header",
    "footer",
    "image",
    "signature",
}  # unknown types too, from a newer API
_KIND_BY_BLOCK_TYPE = {"title": BlockKind.HEADING, "table": BlockKind.TABLE}  # the rest is text


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
        uploaded_file = self._client.files.upload(
            file={"file_name": "report.pdf", "content": pdf}, purpose="ocr"
        )
        try:
            response = self._client.ocr.process(
                model=_OCR_MODEL,
                document={"type": "file", "file_id": uploaded_file.id},
                table_format="markdown",
                extract_header=True,
                extract_footer=True,
            )
        finally:
            self._client.files.delete(file_id=uploaded_file.id)
        return [block for page in response.pages for block in _page_blocks(page)]


def _page_blocks(page: OCRPageObject) -> list[Block]:
    width, height = page.dimensions.width, page.dimensions.height  # type: ignore[union-attr]
    blocks = []
    for ocr_block in page.blocks or []:
        if (
            isinstance(ocr_block, UnknownBlock)
            or ocr_block.type in _SKIPPED_BLOCK_TYPES
            or not ocr_block.content.strip()
        ):
            continue
        kind = _KIND_BY_BLOCK_TYPE.get(ocr_block.type, BlockKind.TEXT)
        content = ocr_block.content
        text = content.lstrip("#").strip() if kind == BlockKind.HEADING else content.strip()
        box = PageBox(
            x=ocr_block.top_left_x / width,
            y=ocr_block.top_left_y / height,
            width=(ocr_block.bottom_right_x - ocr_block.top_left_x) / width,
            height=(ocr_block.bottom_right_y - ocr_block.top_left_y) / height,
        )
        blocks.append(Block(page=page.index + 1, kind=kind, text=text, box=box))
    return blocks
