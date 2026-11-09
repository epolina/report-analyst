import json

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from report_analyst.chat.filtering_fields import FilteringFields
from report_analyst.llm import CitedAnswer, CitedSpan, LLMError
from report_analyst.settings import AppSettings
from conftest import WHOLE_PAGE, FakeLLM, HeldJobs, upload

FTE_SENTENCE = "We employed 12,345 FTEs."
GOAL_SENTENCE = "Our target is net zero by 2050."


def ask(client: TestClient, question: str, **body: object) -> dict:
    response = client.post("/chat", json={"question": question, **body})
    assert response.status_code == 200, response.text
    return response.json()


def facts(fte: bool = True, goal: str | None = GOAL_SENTENCE) -> dict[str, Any]:
    """What fact extraction answers for a one-page report holding the two sentences."""
    answer: dict[str, Any] = {"goals": []}
    if fte:
        answer["fte"] = {"amount": 12345, "citation": {"passage_id": 0, "quote": FTE_SENTENCE}}
    if goal:
        answer["goals"] = [
            {"title": "Net zero", "deadline": 2050, "citation": {"passage_id": 0, "quote": goal}}
        ]
    return answer


def add_report(
    client: TestClient,
    make_pdf: Callable[[str], bytes],
    fake_llm: FakeLLM,
    company_name: str = "Shell",
    reporting_year: str = "2024",
    **extracted: Any,
) -> str:
    """Upload a report whose Facts are extracted as `facts(**extracted)`; return its id."""
    fake_llm.answer = facts(**extracted)
    pdf = make_pdf(f"{company_name} {reporting_year}. {FTE_SENTENCE} {GOAL_SENTENCE}")
    form = {"company_name": company_name, "reporting_year": reporting_year}
    return str(upload(client, pdf, **form).json()["report_id"])


def filtering_fields(fake_llm: FakeLLM, fact: str | None, *pairs: tuple[str, int]) -> None:
    """Make Claude read `fact` and these Company and year pairs out of the next Question."""
    fake_llm.answers[FilteringFields] = {
        "fact": fact,
        "company_year_pairs": [{"company_name": c, "reporting_year": y} for c, y in pairs],
    }


def test_an_fte_question_is_answered_from_the_extracted_facts(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    shell = add_report(client, make_pdf, fake_llm)
    filtering_fields(fake_llm, "fte", ("shell", 2024))  # matched ignoring case
    fake_llm.cited = CitedAnswer(
        text="Shell had 12,345 FTE in 2024.",
        citations=[
            CitedSpan(document_index=0, text=FTE_SENTENCE),
            CitedSpan(document_index=0, text="12,345 FTEs"),  # the same Fact twice
        ],
    )

    reply = ask(client, "How many FTE did shell have?")

    filtering_fields_prompt, answer_prompt = fake_llm.prompts[-2:]
    assert "Shell, 2024" in filtering_fields_prompt  # the stored reports
    assert "Question: How many FTE did shell have?" in filtering_fields_prompt
    assert "- Shell 2024: FTE found" in answer_prompt
    assert "at most three sentences" in answer_prompt
    assert fake_llm.documents == [("Shell 2024, page 1: FTE 12,345", FTE_SENTENCE)]
    assert reply["reports"] == [
        {"report_id": shell, "company_name": "Shell", "reporting_year": 2024}
    ]
    assert reply["answer"]["kind"] == "answer"
    assert reply["answer"]["evidence"] == [  # the Fact's own Evidence, cited once
        {
            "page": 1,
            "quote": FTE_SENTENCE,
            "boxes": [WHOLE_PAGE.model_dump()],
            "report_id": shell,
            "company_name": "Shell",
            "reporting_year": 2024,
        }
    ]


def test_goals_of_two_reports_are_compared(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    abn = add_report(client, make_pdf, fake_llm, "ABN AMRO", "2025")
    shell = add_report(client, make_pdf, fake_llm, "Shell", "2025", goal=None)
    filtering_fields(fake_llm, "sustainability_goals", ("ABN AMRO", 2025), ("Shell", 2025))
    fake_llm.cited = CitedAnswer(
        text="ABN AMRO aims for net zero by 2050; Shell 2025 lists no goals.",
        citations=[CitedSpan(document_index=0, text=GOAL_SENTENCE)],
    )

    reply = ask(client, "Compare the sustainability goals of ABN 2025 and Shell 2025")

    answer_prompt = fake_llm.prompts[-1]
    assert "- ABN AMRO 2025: 1 sustainability goal found" in answer_prompt
    assert "- Shell 2025: 0 sustainability goals found" in answer_prompt
    assert "a short paragraph for each report" in answer_prompt
    assert fake_llm.documents == [
        ("ABN AMRO 2025, page 1: goal: Net zero, deadline 2050", GOAL_SENTENCE)
    ]
    assert [r["report_id"] for r in reply["reports"]] == [abn, shell]
    [evidence] = reply["answer"]["evidence"]
    assert (evidence["company_name"], evidence["quote"]) == ("ABN AMRO", GOAL_SENTENCE)


def test_a_company_or_year_not_stored_is_named_without_answering(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    shell = add_report(client, make_pdf, fake_llm)
    filtering_fields(fake_llm, "fte", ("Shell", 2024), ("ABN AMRO", 2023))
    calls = len(fake_llm.prompts)

    reply = ask(client, "Compare the FTE of Shell 2024 and ABN AMRO 2023")

    assert reply["answer"] == {
        "kind": "not_found",
        "text": "",  # the UI words it from the reason and `missing`
        "evidence": [],
        "reason": "no_matching_report",
        "missing": ["ABN AMRO 2023"],
    }
    assert reply["reports"][0]["report_id"] == shell  # the pair that is stored
    assert len(fake_llm.prompts) == calls + 1  # fields extracted, no answer generated


def test_a_question_about_anything_else_is_not_supported(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    add_report(client, make_pdf, fake_llm)
    filtering_fields(fake_llm, None, ("Shell", 2024))
    calls = len(fake_llm.prompts)

    reply = ask(client, "What was Shell's revenue in 2024?")

    assert reply["answer"]["reason"] == "unsupported_topic"
    assert len(fake_llm.prompts) == calls + 1


def test_a_question_naming_no_company_asks_for_one(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    add_report(client, make_pdf, fake_llm)
    filtering_fields(fake_llm, "fte")

    reply = ask(client, "How many FTE?")

    assert (reply["answer"]["reason"], reply["reports"]) == ("no_company_named", [])


def test_a_report_still_processing_has_no_facts_yet(
    client: TestClient, held_jobs: HeldJobs, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    upload(client, make_pdf(FTE_SENTENCE))
    filtering_fields(fake_llm, "fte", ("Shell", 2024))

    reply = ask(client, "How many FTE did Shell have?")

    assert reply["answer"]["reason"] == "report_not_ready"


def test_no_fact_on_the_topic_is_not_found_without_answering(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    add_report(client, make_pdf, fake_llm, fte=False)
    filtering_fields(fake_llm, "fte", ("Shell", 2024))
    calls = len(fake_llm.prompts)

    reply = ask(client, "How many FTE did Shell have?")

    assert reply["answer"]["reason"] == "not_in_report"
    assert len(fake_llm.prompts) == calls + 1


def test_no_report_stored_is_not_found_without_asking_the_model(
    client: TestClient, fake_llm: FakeLLM
) -> None:
    reply = ask(client, "How many FTE did Shell have?")

    assert (reply["answer"]["reason"], reply["reports"]) == ("no_report", [])
    assert fake_llm.prompts == []


def test_an_answer_citing_nothing_is_not_found(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    shell = add_report(client, make_pdf, fake_llm)
    filtering_fields(fake_llm, "fte", ("Shell", 2024))
    fake_llm.cited = CitedAnswer(text="The facts don't give it.", citations=[])

    reply = ask(client, "How many FTE did Shell have?")

    assert (reply["answer"]["kind"], reply["answer"]["text"], reply["answer"]["reason"]) == (
        "not_found",
        "The facts don't give it.",
        "not_in_report",
    )


def test_follow_ups_see_earlier_turns_and_the_conversation_is_stored(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    shell = add_report(client, make_pdf, fake_llm)
    filtering_fields(fake_llm, "fte", ("Shell", 2024))
    fake_llm.cited = CitedAnswer(
        text="12,345 FTE.", citations=[CitedSpan(document_index=0, text=FTE_SENTENCE)]
    )
    first = ask(client, "How many FTE did Shell have?")

    second = ask(client, "And in 2024?", conversation_id=first["conversation_id"])

    match_prompt, answer_prompt = fake_llm.prompts[-2:]
    assert "Earlier question: How many FTE did Shell have?" in match_prompt
    assert "Earlier answer: 12,345 FTE." in answer_prompt
    assert second["conversation_id"] == first["conversation_id"]
    stored = client.get(f"/conversations/{first['conversation_id']}").json()
    assert [t["question"] for t in stored["turns"]] == [
        "How many FTE did Shell have?",
        "And in 2024?",
    ]


def test_model_failure_is_502_and_stores_nothing(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    shell = add_report(client, make_pdf, fake_llm)
    filtering_fields(fake_llm, "fte", ("Shell", 2024))

    def fail(prompt: str, documents: object) -> CitedAnswer:
        raise LLMError("down")

    fake_llm.cite = fail  # type: ignore[method-assign]
    response = client.post("/chat", json={"question": "How many FTE did Shell have?"})

    assert (response.status_code, response.json()) == (502, {"code": "answer_failed"})


def test_a_conversation_stored_before_report_matching_still_loads(
    client: TestClient, settings: AppSettings
) -> None:
    conversation_id = "00000000-0000-0000-0000-0000000000c1"
    old_turn = {  # has the old `scope` and no `reports`
        "question": "FTE?",
        "scope": {"company_name": "Shell", "reporting_year": 2024},
        "answer": {"kind": "not_found", "text": "", "evidence": [], "reason": "no_report"},
    }
    settings.conversations_dir.mkdir(parents=True, exist_ok=True)
    (settings.conversations_dir / f"{conversation_id}.json").write_text(
        json.dumps({"conversation_id": conversation_id, "turns": [old_turn]})
    )

    [turn] = client.get(f"/conversations/{conversation_id}").json()["turns"]

    assert (turn["question"], turn["reports"], turn["answer"]["missing"]) == ("FTE?", [], [])
