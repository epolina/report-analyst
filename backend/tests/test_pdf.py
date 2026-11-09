from mistralai.client.models import OCRPageObject

from report_analyst.pdf import (
    BlockKind,
    mistral_extractor,
    page_count,
    render_pages,
)


def test_mistral_blocks_become_headings_text_and_tables_with_boxes() -> None:
    def block(type: str, content: str, y: int) -> dict:
        return dict(
            type=type,
            content=content,
            top_left_x=100,
            top_left_y=y,
            bottom_right_x=300,
            bottom_right_y=y + 50,
        )

    page = OCRPageObject.model_validate(
        dict(
            index=2,
            markdown="",
            images=[],
            dimensions=dict(dpi=72, width=1000, height=500),
            blocks=[
                block("header", "Annual Report", 0),
                block("title", "## Climate", 50),
                block("text", "We aim.", 100),
                block("table", "|a|b|\n|---|---|", 150),
                block("list", "- one", 200),
                block("image", "![img-0.jpeg](img-0.jpeg)", 250),
                block("footer", "3", 450),
            ],
        )
    )

    blocks = mistral_extractor._blocks(page)

    assert [(b.page, b.kind, b.text) for b in blocks] == [
        (3, BlockKind.HEADING, "Climate"),
        (3, BlockKind.TEXT, "We aim."),
        (3, BlockKind.TABLE, "|a|b|\n|---|---|"),
        (3, BlockKind.TEXT, "- one"),
    ]
    box = blocks[0].box
    assert (box.x, box.y, box.width, box.height) == (0.1, 0.1, 0.2, 0.1)


def test_counts_and_renders_every_page(two_page_pdf: bytes) -> None:
    assert page_count(two_page_pdf) == 2
    images = render_pages(two_page_pdf)
    assert len(images) == 2
    assert all(i.startswith(b"\xff\xd8") for i in images)  # JPEG
