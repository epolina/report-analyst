from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import numpy as np
from fastapi.testclient import TestClient

from report_analyst.index import BM25, HybridIndex, tokenize
from report_analyst.pdf import Block, BlockKind, PageBox
from report_analyst.reports import ReportRepository, Retriever
from report_analyst.reports.splitting import split_into_passages
from report_analyst.settings import AppSettings
from conftest import WHOLE_PAGE, FakeEmbedder, upload


def test_bm25_prefers_rare_shared_words() -> None:
    bm25 = BM25(["net zero by 2040", "revenue grew by 5%", "net revenue by region"])

    scores = bm25.scores("net zero")

    assert np.argmax(scores) == 0
    assert scores[1] == 0  # shares no word with the query


def test_hybrid_index_finds_by_keyword_or_meaning() -> None:
    vectors = np.eye(3, dtype=np.float32)  # each text points its own way
    index = HybridIndex(["net zero by 2040", "revenue grew", "water use fell"], vectors)

    assert index.search("net zero", vectors[2], limit=2) == [0, 2]  # keyword first, then meaning


def test_splitter_keeps_pages_apart_and_carries_headings() -> None:
    def block(page: int, kind: BlockKind, text: str) -> Block:
        return Block(page=page, kind=kind, text=text, box=PageBox(x=page, y=0, width=0, height=0))

    blocks = [
        block(1, BlockKind.HEADING, "Climate"),
        block(1, BlockKind.TEXT, "We aim for net zero."),
        block(1, BlockKind.TEXT, "Scope 3 too."),
        block(2, BlockKind.TEXT, "Water use fell."),
        block(2, BlockKind.HEADING, "People"),
        block(2, BlockKind.TABLE, "| FTE | 9,000 | in | 2025 | group |"),
    ]

    passages = split_into_passages(blocks, max_words=4)

    assert [(p.index, p.page, p.heading, p.text) for p in passages] == [
        (0, 1, "Climate", "We aim for net zero."),  # 5 words: the next block starts anew
        (1, 1, "Climate", "Scope 3 too."),
        (2, 2, "Climate", "Water use fell."),  # heading carries over to the next page
        (3, 2, "People", "| FTE | 9,000 | in | 2025 | group |"),  # too long, but stays whole
    ]
    assert passages[0].search_text == "Climate We aim for net zero."
    assert [len(p.blocks) for p in passages] == [1, 1, 1, 1]  # headings aren't kept as blocks


def test_passage_keeps_its_blocks() -> None:
    box = PageBox(x=0.1, y=0.2, width=0.3, height=0.4)
    blocks = [Block(page=1, kind=BlockKind.TEXT, text=t, box=box) for t in ("a", "b")]

    [passage] = split_into_passages(blocks)

    assert passage.blocks == blocks
    assert passage.text == "a\n\nb"


def test_upload_indexes_the_report_for_search(
    client: TestClient, settings: AppSettings, make_pdf: Callable[[str], bytes]
) -> None:
    report_id = upload(client, make_pdf("Our target is net zero emissions by 2050.")).json()
    upload(client, make_pdf("Revenue grew strongly this year."), reporting_year="2023")

    retriever = Retriever(ReportRepository(settings.reports_dir), FakeEmbedder())
    [hit] = retriever.search(UUID(report_id["report_id"]), "net zero target", limit=1)

    assert hit.page == 1
    assert "net zero emissions" in hit.text


def test_tokenize_makes_plurals_singular() -> None:
    assert tokenize("Total FTEs: 18,703 in Scope 3 emissions; it was") == [
        "total",
        "fte",
        "18",
        "703",
        "in",
        "scope",
        "3",
        "emission",
        "it",
        "was",
    ]


def test_search_sees_passages_saved_again(tmp_path: Path) -> None:
    # A retry saves new Passages for the same PDF; the cached index must not keep the old ones.
    repository = ReportRepository(tmp_path)
    report = repository.create("Shell", 2024, b"%PDF-", pages=1, original_filename=None)
    retriever = Retriever(repository, FakeEmbedder())

    def save(text: str) -> None:
        passages = split_into_passages(
            [Block(page=1, kind=BlockKind.TEXT, text=text, box=WHOLE_PAGE)]
        )
        repository.save_contents(report.report_id, [], passages, retriever.embed(passages))

    save("Net zero by 2050.")
    assert "2050" in retriever.search(report.report_id, "net zero")[0].text
    save("Net zero by 2040.")
    assert "2040" in retriever.search(report.report_id, "net zero")[0].text
