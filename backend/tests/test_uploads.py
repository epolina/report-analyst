import hashlib
import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from report_analyst.reports import ReportRepository
from report_analyst.routers.uploads import BYTES_PER_MB
from report_analyst.settings import AppSettings
from conftest import HeldJobs, one_page_pdf, upload

SHELL_PDF = one_page_pdf("Total FTEs: 44,209")
NEWER_SHELL_PDF = one_page_pdf("Total FTEs: 44,210")
TRUNCATED_PDF = b"%PDF-1.7\nthe rest is missing"
FORM = {"company_name": "Shell", "reporting_year": "2024"}


def stored_ids(settings: AppSettings) -> list[str]:
    return [str(r.report_id) for r in ReportRepository(settings.reports_dir).list()]


def test_upload_stores_pdf_and_metadata(client: TestClient, settings: AppSettings) -> None:
    response = upload(client, SHELL_PDF)

    assert response.status_code == 202
    body = response.json()
    report_id = body.pop("report_id")
    assert body == {
        "company_name": "Shell",
        "reporting_year": 2024,
        "sha256": hashlib.sha256(SHELL_PDF).hexdigest(),
        "page_count": 1,
        "status": "processing",
        "failure": None,
    }
    folder = settings.reports_dir / str(UUID(report_id))
    assert (folder / "upload.pdf").read_bytes() == SHELL_PDF
    metadata = json.loads((folder / "metadata.json").read_text())
    assert metadata["report_id"] == report_id
    assert metadata["original_filename"] == "shell-2024.pdf"  # for reference, never a path


def test_failed_replace_keeps_the_stored_report(client: TestClient, settings: AppSettings) -> None:
    first = upload(client, SHELL_PDF).json()

    response = upload(client, TRUNCATED_PDF, on_duplicate="replace")

    assert response.status_code == 422
    folder = settings.reports_dir / first["report_id"]
    assert (folder / "upload.pdf").read_bytes() == SHELL_PDF


@pytest.mark.parametrize(
    ("content", "form", "code"),
    [
        (SHELL_PDF, {"company_name": "Shell", "reporting_year": "2025"}, "same_file"),  # other year
        (NEWER_SHELL_PDF, {"company_name": "shell"}, "same_company_year"),  # Company in any case
    ],
)
def test_duplicate_asks_and_saves_nothing(
    client: TestClient, settings: AppSettings, content: bytes, form: dict[str, str], code: str
) -> None:
    first = upload(client, SHELL_PDF).json()

    response = upload(client, content, **form)

    assert response.status_code == 409
    assert response.json()["code"] == code
    assert response.json()["existing"] == {**first, "status": "success"}
    assert stored_ids(settings) == [first["report_id"]]


@pytest.mark.parametrize("choice", ["replace", "keep_both"])
def test_same_file_is_refused_whatever_the_choice(
    client: TestClient, settings: AppSettings, choice: str
) -> None:
    first = upload(client, SHELL_PDF).json()

    response = upload(client, SHELL_PDF, on_duplicate=choice)

    assert response.status_code == 409
    assert response.json()["code"] == "same_file"
    assert stored_ids(settings) == [first["report_id"]]


def test_duplicate_replace_keeps_id(client: TestClient, settings: AppSettings) -> None:
    first = upload(client, SHELL_PDF).json()

    second = upload(client, NEWER_SHELL_PDF, company_name="shell", on_duplicate="replace").json()

    assert second["report_id"] == first["report_id"]
    assert second["company_name"] == "Shell"  # first spelling kept
    folder = settings.reports_dir / first["report_id"]
    assert (folder / "upload.pdf").read_bytes() == NEWER_SHELL_PDF


def test_replacing_a_report_still_processing_is_refused(
    client: TestClient, settings: AppSettings, held_jobs: HeldJobs
) -> None:
    # Its job would otherwise save the old PDF's contents over the new one.
    first = upload(client, SHELL_PDF).json()

    response = upload(client, NEWER_SHELL_PDF, on_duplicate="replace")

    assert response.status_code == 409
    assert response.json()["code"] == "still_processing"
    assert (settings.reports_dir / first["report_id"] / "upload.pdf").read_bytes() == SHELL_PDF


def test_duplicate_keep_both_creates_new_id(client: TestClient, settings: AppSettings) -> None:
    first = upload(client, SHELL_PDF).json()

    second = upload(client, NEWER_SHELL_PDF, on_duplicate="keep_both").json()

    assert second["report_id"] != first["report_id"]
    assert sorted(stored_ids(settings)) == sorted([first["report_id"], second["report_id"]])


@pytest.mark.parametrize(
    ("content", "form", "status"),
    [
        (b"PK\x03\x04 a zip, not a pdf", FORM, 415),
        (b"", FORM, 415),
        (TRUNCATED_PDF, FORM, 422),  # pdfium can't open it
        (SHELL_PDF, {"company_name": "  ", "reporting_year": "2024"}, 422),
        (SHELL_PDF, {"company_name": "Shell", "reporting_year": "24"}, 422),
        (SHELL_PDF, {"company_name": "Shell"}, 422),
    ],
)
def test_upload_rejects_invalid_and_saves_nothing(
    client: TestClient, settings: AppSettings, content: bytes, form: dict[str, str], status: int
) -> None:
    response = client.post("/uploads", files={"file": ("x.pdf", content)}, data=form)

    assert response.status_code == status
    assert stored_ids(settings) == []


def test_upload_rejects_too_large(client: TestClient, settings: AppSettings) -> None:
    settings.max_upload_mb = 1
    content = SHELL_PDF + b"0" * BYTES_PER_MB

    response = client.post("/uploads", files={"file": ("big.pdf", content)}, data=FORM)

    assert response.status_code == 413
    assert response.json() == {"code": "file_too_large", "max_upload_mb": 1}
