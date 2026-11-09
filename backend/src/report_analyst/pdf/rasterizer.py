"""Counting a PDF's pages and drawing them as images, with pdfium."""

import io
import pypdfium2 as pdfium
import threading

from report_analyst.pdf.models import ExtractionError


_PAGE_WIDTH_PX = 1200  # sharp at the viewer's width on a 2x screen
_JPEG_QUALITY = 85  # text stays crisp
# pdfium isn't thread-safe and FastAPI runs requests on a thread pool: two uploads rendering at
# once crash the process. One lock for the process, held for a whole render, so an upload's
# page count waits while a long report renders; a process pool if uploads queue up.
_PDFIUM_LOCK = threading.Lock()


def count_pages(pdf: bytes) -> int:
    """Count a PDF's pages.

    Args:
        pdf: The PDF bytes.

    Returns:
        The number of pages.

    Raises:
        ExtractionError: pdfium can't open the bytes as a PDF.
    """
    try:
        with _PDFIUM_LOCK, pdfium.PdfDocument(pdf) as document:
            return len(document)
    except pdfium.PdfiumError as error:
        raise ExtractionError(str(error)) from error


def render_pages(pdf: bytes) -> list[bytes]:
    """Render every page as a JPEG image, 1200 px wide.

    Args:
        pdf: The PDF bytes. pdfium must be able to open them.

    Returns:
        The JPEG bytes of each page, in order.
    """
    with _PDFIUM_LOCK, pdfium.PdfDocument(pdf) as document:
        return [_render_jpeg(page) for page in document]


def _render_jpeg(page: pdfium.PdfPage) -> bytes:
    # Closes what pdfium allocated here, under the caller's lock, not later in the GC.
    width, _ = page.get_size()
    bitmap = page.render(scale=_PAGE_WIDTH_PX / width)
    buffer = io.BytesIO()
    bitmap.to_pil().save(buffer, "JPEG", quality=_JPEG_QUALITY)
    bitmap.close()
    page.close()
    return buffer.getvalue()
