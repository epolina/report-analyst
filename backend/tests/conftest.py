import re
import zlib
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pymupdf
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from typing import Any

from pydantic import BaseModel, SecretStr, ValidationError

from report_analyst.llm import CitedAnswer, LLMError
from report_analyst.main import create_app
from report_analyst.pdf import Block, BlockKind, ExtractionError, PageBox, PdfExtractor
from report_analyst.reports import service
from report_analyst.routers.dependencies import (
    get_embedder,
    get_llm,
    get_pdf_extractor,
    get_settings,
)
from report_analyst.settings import AppSettings


class FakeEmbedder:
    """Bag-of-words vectors: texts sharing words are similar. No model download."""

    def _vector(self, text: str) -> np.ndarray:
        v = np.zeros(64, dtype=np.float32)
        for word in re.findall(r"\w+", text.lower()):
            v[zlib.crc32(word.encode()) % 64] += 1
        return v / max(float(np.linalg.norm(v)), 1e-12)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vector(t) for t in texts]) if texts else np.empty((0, 0), np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        return self._vector(query)[None, :]


WHOLE_PAGE = PageBox(x=0, y=0, width=1, height=1)


class FakePdfExtractor(PdfExtractor):
    """One text Block per page, read from the PDF's text layer with pdfium. No API calls."""

    def extract(self, pdf: bytes) -> list[Block]:
        try:
            with pdfium.PdfDocument(pdf) as doc:
                texts = [page.get_textpage().get_text_range() for page in doc]
        except pdfium.PdfiumError as error:
            raise ExtractionError(str(error)) from error
        return [
            Block(page=n, kind=BlockKind.TEXT, text=t.strip(), box=WHOLE_PAGE)
            for n, t in enumerate(texts, start=1)
            if t.strip()
        ]


class FakeLLM:
    """Records prompts. `complete` validates `answer` (a dict) against the schema, with the
    context the real call would get, or gives an empty instance; `cite` returns `cited`. No
    API calls."""

    def __init__(self) -> None:
        self.answer: dict[str, Any] | None = None
        self.cited = CitedAnswer(text="", citations=[])  # what `cite` returns
        self.prompts: list[str] = []
        self.documents: list[tuple[str, str | list[str]]] = []  # what the last `cite` was given

    def cite(self, prompt: str, documents: list[tuple[str, str | list[str]]]) -> CitedAnswer:
        self.prompts.append(prompt)
        self.documents = documents
        return self.cited

    def complete(self, prompt: str, schema: type[BaseModel], context: Any = None) -> BaseModel:
        self.prompts.append(prompt)
        if self.answer is None:
            return schema()
        try:
            return schema.model_validate(self.answer, context=context)
        except ValidationError as error:  # the real one retries, then gives up like this
            raise LLMError(str(error)) from error


class HeldJobs(list[Callable[[], None]]):
    """Stands in for the job queue: keeps jobs until `run` is called."""

    def submit(self, fn: Callable[..., None], *args: Any) -> None:
        self.append(lambda: fn(*args))

    def run(self) -> None:
        while self:
            self.pop(0)()


class ImmediateJobs:
    """Stands in for the job queue: runs each job before `submit` returns."""

    def submit(self, fn: Callable[..., None], *args: Any) -> None:
        fn(*args)


@pytest.fixture(autouse=True)
def immediate_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Process uploads straight away, so a test sees the report ready after the request."""
    monkeypatch.setattr(service, "_JOBS", ImmediateJobs())


@pytest.fixture
def held_jobs(monkeypatch: pytest.MonkeyPatch) -> HeldJobs:
    """Keep jobs queued until the test calls `run`, to see a report while it's processing."""
    jobs = HeldJobs()
    monkeypatch.setattr(service, "_JOBS", jobs)
    return jobs


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    """Settings that store everything in a temporary directory."""
    return AppSettings(
        reports_dir=tmp_path / "reports",
        conversations_dir=tmp_path / "conversations",
        anthropic_api_key=SecretStr("test"),
        mistral_api_key=SecretStr("test"),
    )


def one_page_pdf(text: str) -> bytes:
    """Build a one-page PDF holding `text`; different text gives a different file."""
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), text)
        return doc.tobytes()


@pytest.fixture
def make_pdf() -> Callable[[str], bytes]:
    """`one_page_pdf`, for tests that take it as a fixture."""
    return one_page_pdf


@pytest.fixture
def two_page_pdf() -> bytes:
    """A two-page PDF with one line of text mid-page on each."""
    with pymupdf.open() as doc:
        for text in ("Total FTEs: 44,209", "Net zero by 2040"):
            doc.new_page().insert_text((72, 400), text)
        return doc.tobytes()


def upload(client: TestClient, pdf: bytes, **form: str) -> Response:
    """POST /uploads, as Shell 2024 unless `form` says otherwise."""
    return client.post(
        "/uploads",
        files={"file": ("shell-2024.pdf", pdf)},
        data={"company": "Shell", "reporting_year": "2024", **form},
    )


@pytest.fixture
def client(
    settings: AppSettings, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A test client whose requests use `settings`.

    The start-up check reads the real environment, so it gets a dummy API key too.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("MISTRAL_API_KEY", "test")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_llm] = lambda: fake_llm
    app.dependency_overrides[get_pdf_extractor] = FakePdfExtractor
    with TestClient(app) as client:
        yield client
