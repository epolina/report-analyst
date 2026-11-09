"""Background processing: statuses, failures, retry, start-up recovery."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from report_analyst.domain import ReportStatus
from report_analyst.llm import LLMError
from report_analyst.pdf import ExtractionError
from report_analyst.reports import ReportRepository
from report_analyst.settings import AppSettings
from conftest import FakePdfExtractor, FakeLLM, HeldJobs, upload


def status(client: TestClient, report_id: str) -> str:
    return client.get(f"/reports/{report_id}").json()["status"]


def test_upload_goes_through_the_stages_to_ready(
    client: TestClient,
    held_jobs: HeldJobs,
    make_pdf: Callable[[str], bytes],
    fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="report_analyst.reports.service")
    seen: list[str] = []
    complete = fake_llm.complete

    def spy(*args: object, **kwargs: object) -> object:
        seen.append(status(client, report["report_id"]))
        return complete(*args, **kwargs)  # type: ignore[arg-type]

    report = upload(client, make_pdf("We employed 12,345 FTEs.")).json()
    assert report["status"] == "processing"
    detail = client.get(f"/reports/{report['report_id']}").json()
    assert (detail["fte"], detail["goals"]) == (None, [])
    assert fake_llm.prompts == []  # a processing report's view makes no LLM call

    monkeypatch.setattr(fake_llm, "complete", spy)
    held_jobs.run()

    assert seen == ["processing"]
    assert status(client, report["report_id"]) == "success"
    steps = [r.getMessage().split(": ", 1)[1] for r in caplog.records if " took " in r.message]
    assert [s.rsplit(" took ", 1)[0] for s in steps] == [
        "text extraction",
        "embedding 1 passages",
        "rendering 1 pages",
        "saving",
        "fact extraction",
    ]


def _raise(error: Exception) -> Callable[..., object]:
    def broken(*args: object, **kwargs: object) -> object:
        raise error

    return broken


@pytest.mark.parametrize(
    ("owner", "method", "error", "failure"),
    [
        (
            FakePdfExtractor,
            "extract",
            ExtractionError("bad xref"),
            "unreadable_pdf",
        ),
        (
            FakePdfExtractor,
            "extract",
            RuntimeError("bug"),
            "unexpected",
        ),
        (FakeLLM, "complete", LLMError("down"), "facts_failed"),
    ],
)
def test_a_failure_while_processing_fails_the_report(
    client: TestClient,
    make_pdf: Callable[[str], bytes],
    monkeypatch: pytest.MonkeyPatch,
    owner: type,
    method: str,
    error: Exception,
    failure: str,
) -> None:
    monkeypatch.setattr(owner, method, _raise(error))

    assert upload(client, make_pdf("We employed 12,345 FTEs.")).status_code == 202

    [failed] = client.get("/reports").json()
    assert (failed["status"], failed["failure"]) == ("failed", failure)


def test_retry_processes_a_failed_report_again(
    client: TestClient, make_pdf: Callable[[str], bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(FakePdfExtractor, "extract", _raise(ExtractionError("bad xref")))
        report_id = upload(client, make_pdf("We employed 12,345 FTEs.")).json()["report_id"]

    response = client.post(f"/reports/{report_id}/retry")

    assert response.status_code == 202
    detail = client.get(f"/reports/{report_id}").json()
    assert (detail["status"], detail["failure"]) == ("success", None)
    assert client.get(f"/reports/{report_id}/pages/1").status_code == 200


def test_only_a_failed_report_can_be_retried(
    client: TestClient, held_jobs: HeldJobs, make_pdf: Callable[[str], bytes]
) -> None:
    report = upload(client, make_pdf("first")).json()

    assert client.post(f"/reports/{report['report_id']}/retry").status_code == 409  # processing
    held_jobs.run()
    assert client.post(f"/reports/{report['report_id']}/retry").status_code == 409  # ready


def test_start_up_fails_interrupted_reports(
    settings: AppSettings,
    make_pdf: Callable[[str], bytes],
    request: pytest.FixtureRequest,
) -> None:
    repository = ReportRepository(settings.reports_dir)
    report = repository.create("Shell", 2024, make_pdf("x"), 1, None)
    repository.set_status(report.report_id, ReportStatus.PROCESSING)

    client: TestClient = request.getfixturevalue("client")  # starts the app

    detail = client.get(f"/reports/{report.report_id}").json()
    assert (detail["status"], detail["failure"]) == ("failed", "interrupted")
