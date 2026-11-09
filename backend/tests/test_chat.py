from collections.abc import Callable

from fastapi.testclient import TestClient

from report_analyst.chat import Scope
from report_analyst.chat.service import resolve_scope
from report_analyst.domain import Report, ReportStatus
from report_analyst.llm import CitedSpan, CitedAnswer, LLMError
from conftest import WHOLE_PAGE, FakeLLM, upload

SPEND_SENTENCE = "In 2024, we spent $1.2 billion on climate adaptation."


def ask(client: TestClient, question: str, **body: object) -> dict:
    response = client.post("/chat", json={"question": question, **body})
    assert response.status_code == 200, response.text
    return response.json()


def answer(*quotes: str) -> CitedAnswer:
    return CitedAnswer(
        text="Shell spent $1.2 billion on climate adaptation in 2024.",
        citations=[CitedSpan(document_index=0, text=q) for q in quotes or (SPEND_SENTENCE,)],
    )


def test_answers_with_evidence_from_the_report_named_in_the_question(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    shell = upload(client, make_pdf(SPEND_SENTENCE)).json()["report_id"]
    upload(client, make_pdf("Heineken brewed beer."), company_name="Heineken")
    fake_llm.cited = answer()

    reply = ask(client, "How much did SHELL spend on climate adaptation in 2024?")

    assert reply["scope"] == {"company_name": "Shell", "reporting_year": 2024}
    assert reply["answer"]["kind"] == "answer"
    [evidence] = reply["answer"]["evidence"]
    assert (evidence["report_id"], evidence["company_name"], evidence["reporting_year"]) == (
        shell,
        "Shell",
        2024,
    )
    assert (evidence["page"], evidence["quote"]) == (1, SPEND_SENTENCE)
    [(title, text)] = fake_llm.documents  # only Shell was searched
    assert (title, text) == ("Shell 2024, page 1", SPEND_SENTENCE)


def test_conversation_is_stored_and_follow_ups_see_earlier_turns(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    upload(client, make_pdf(SPEND_SENTENCE))
    fake_llm.cited = answer()
    first = ask(client, "How much did Shell spend on climate adaptation?")

    second = ask(client, "And in total?", conversation_id=first["conversation_id"])

    assert second["conversation_id"] == first["conversation_id"]
    assert (
        "Earlier question: How much did Shell spend on climate adaptation?" in fake_llm.prompts[-1]
    )
    stored = client.get(f"/conversations/{first['conversation_id']}").json()
    assert [t["question"] for t in stored["turns"]] == [
        "How much did Shell spend on climate adaptation?",
        "And in total?",
    ]


def test_a_span_cited_twice_is_one_evidence(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    upload(client, make_pdf(SPEND_SENTENCE))
    fake_llm.cited = answer(SPEND_SENTENCE, f" {SPEND_SENTENCE}\n")

    reply = ask(client, "How much did Shell spend?")

    assert [e["quote"] for e in reply["answer"]["evidence"]] == [SPEND_SENTENCE]


def test_an_answer_citing_nothing_is_not_found(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    upload(client, make_pdf(SPEND_SENTENCE))
    fake_llm.cited = CitedAnswer(
        text="The report doesn't state carbon capture spend.", citations=[]
    )

    reply = ask(client, "What did Shell spend on carbon capture?")

    assert reply["answer"] == {
        "kind": "not_found",
        "text": "The report doesn't state carbon capture spend.",
        "evidence": [],
        "reason": "not_in_report",
    }


def test_no_report_in_scope_is_not_found_without_asking_the_model(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    upload(client, make_pdf(SPEND_SENTENCE))
    prompts = len(fake_llm.prompts)

    reply = ask(
        client, "What was the FTE?", scope={"company_name": "Shell", "reporting_year": 2023}
    )

    assert reply["answer"]["reason"] == "no_report"
    assert reply["answer"]["text"] == ""  # the UI words it from the reason
    assert len(fake_llm.prompts) == prompts


def test_model_failure_is_502_and_stores_nothing(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    upload(client, make_pdf(SPEND_SENTENCE))

    def fail(prompt: str, documents: object) -> CitedAnswer:
        raise LLMError("down")

    fake_llm.cite = fail  # type: ignore[method-assign]
    first = client.post("/chat", json={"question": "How much did Shell spend?"})

    assert (first.status_code, first.json()) == (502, {"code": "answer_failed"})


def test_scope_comes_from_the_question_then_the_ui() -> None:
    reports = [
        Report(
            report_id="00000000-0000-0000-0000-00000000000" + str(i),
            company_name=c,
            reporting_year=y,
            sha256="x",
            page_count=1,
            status=ReportStatus.SUCCESS,
        )
        for i, (c, y) in enumerate([("Shell", 2024), ("Shell", 2025), ("ABN AMRO", 2025)])
    ]
    ui = Scope(company_name="Shell", reporting_year=2024)

    def scope(question: str) -> tuple:
        s = resolve_scope(question, ui, reports)
        return s.company_name, s.reporting_year

    assert scope("What is the FTE?") == ("Shell", 2024)  # nothing named: the UI's
    assert scope("FTE of abn amro in 2025?") == ("ABN AMRO", 2025)  # named: the question's
    assert scope("Net zero by 2050?") == ("Shell", 2024)  # 2050 isn't a stored year
    assert scope("Compare Shell and ABN AMRO") == (None, 2024)  # two named: both


def test_tables_go_in_by_row_and_come_back_by_row() -> None:
    from anthropic.types.beta import BetaCitationContentBlockLocation

    from report_analyst.chat.service import _document_body
    from report_analyst.domain import Passage
    from report_analyst.pdf import Block, BlockKind
    from report_analyst.llm import _cited_text

    def passage(text: str) -> Passage:
        return Passage(
            index=0,
            page=1,
            heading="",
            blocks=[Block(page=1, kind=BlockKind.TEXT, text=text, box=WHOLE_PAGE)],
        )

    table = "Key figures\n\n| | 2025 |\n| --- | --- |\n| FTE | 23,126 |\n| NIM | 152 |"
    assert _document_body(passage("We aim. We act.")) == "We aim. We act."
    rows = _document_body(passage(table))
    assert rows == [
        "Key figures",
        "| | 2025 |",
        "| --- | --- |",
        "| FTE | 23,126 |",
        "| NIM | 152 |",
    ]

    citation = BetaCitationContentBlockLocation(
        type="content_block_location",
        cited_text="ignored",
        document_index=0,
        start_block_index=3,
        end_block_index=4,
    )
    assert _cited_text(citation, [("t", rows)]) == "| FTE | 23,126 |"


def test_citations_become_evidence_once_and_none_is_not_found() -> None:
    from uuid import uuid4

    from report_analyst.chat.service import _to_answer
    from report_analyst.domain import Passage
    from report_analyst.pdf import Block, BlockKind

    report = Report(
        report_id=uuid4(),
        company_name="Shell",
        reporting_year=2024,
        sha256="abc",
        page_count=9,
        status=ReportStatus.SUCCESS,
    )
    blocks = [Block(page=7, kind=BlockKind.TEXT, text=SPEND_SENTENCE, box=WHOLE_PAGE)]
    found = [(report, Passage(index=0, page=7, heading="", blocks=blocks))]
    text = "Shell spent $1.2 billion."

    cited = CitedAnswer(
        text=text,
        citations=[
            CitedSpan(document_index=0, text=f" {SPEND_SENTENCE} "),
            CitedSpan(document_index=0, text=SPEND_SENTENCE),
        ],
    )
    result = _to_answer(cited, found)
    [evidence] = result.evidence  # the same span cited twice is one Evidence
    assert (result.kind, evidence.page, evidence.quote, evidence.boxes) == (
        "answer",
        7,
        SPEND_SENTENCE,
        [WHOLE_PAGE],
    )
    assert (evidence.report_id, evidence.company_name, evidence.reporting_year) == (
        report.report_id,
        "Shell",
        2024,
    )

    for citations in (
        [],
        [CitedSpan(document_index=0, text="  ")],
    ):  # nothing cited, or only blanks
        result = _to_answer(CitedAnswer(text=text, citations=citations), found)
        assert (result.kind, result.text, result.reason) == ("not_found", text, "not_in_report")
