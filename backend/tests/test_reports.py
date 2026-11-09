from collections.abc import Callable

from fastapi.testclient import TestClient

from conftest import FakeLLM, upload


def test_list_reports_sorted_by_company_then_year(
    client: TestClient, make_pdf: Callable[[str], bytes]
) -> None:
    assert client.get("/reports").json() == []
    for company, year in [("Shell", "2024"), ("ASML", "2025"), ("Shell", "2023")]:
        upload(client, make_pdf(f"{company} {year}"), company_name=company, reporting_year=year)

    body = client.get("/reports").json()

    assert [(r["company_name"], r["reporting_year"]) for r in body] == [
        ("ASML", 2025),
        ("Shell", 2023),
        ("Shell", 2024),
    ]


def test_upload_extracts_verified_facts_once(
    client: TestClient, make_pdf: Callable[[str], bytes], fake_llm: FakeLLM
) -> None:
    fake_llm.answer = {
        "fte": {
            "amount": 12345,
            "citation": {"passage_id": 0, "quote": "We employed 12,345 FTEs."},
        },
        "goals": [
            {
                "title": "Net zero by 2050",
                "deadline": 2050,
                "citation": {"passage_id": 0, "quote": "Our target is net zero by 2050."},
            }
        ],
    }
    pdf = make_pdf("We employed 12,345 FTEs. Our target is net zero by 2050.")
    report_id = upload(client, pdf).json()["report_id"]
    [prompt] = fake_llm.prompts  # extracted while processing
    assert "2024 annual report of Shell" in prompt
    assert '<passage id="0" page="1">' in prompt

    body = client.get(f"/reports/{report_id}").json()

    assert body["company_name"] == "Shell"
    assert body["page_count"] == 1
    assert body["fte"] == {
        "amount": 12345,
        "evidence": {
            "page": 1,
            "quote": "We employed 12,345 FTEs.",
            "boxes": [{"x": 0, "y": 0, "width": 1, "height": 1}],
        },  # the fake extractor boxes the whole page
    }
    assert [g["title"] for g in body["goals"]] == ["Net zero by 2050"]
    assert client.get(f"/reports/{report_id}").json() == body  # stored: no second call
    assert len(fake_llm.prompts) == 1

    fake_llm.answer = {}
    upload(client, make_pdf("We employed 99 people."), on_duplicate="replace")  # same id, new PDF
    assert len(fake_llm.prompts) == 2
    assert client.get(f"/reports/{report_id}").json()["fte"] is None  # old facts are gone


def test_get_page_serves_the_image_rendered_at_upload(
    client: TestClient, make_pdf: Callable[[str], bytes]
) -> None:
    report = upload(client, make_pdf("Net zero by 2040")).json()
    url = f"/reports/{report['report_id']}/pages"

    page = client.get(f"{url}/1")

    assert page.status_code == 200
    assert page.headers["content-type"] == "image/jpeg"
    assert page.content[:3] == b"\xff\xd8\xff"  # JPEG magic
    assert client.get(f"{url}/2").status_code == 404
