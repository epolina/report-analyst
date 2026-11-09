"""Dependency providers. Settings and models are created once; services are built per request."""

import anthropic

from fastapi import Depends
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from report_analyst.chat import ChatService, ConversationRepository
from report_analyst.embedder import Embedder
from report_analyst.facts import FactExtractor
from report_analyst.llm import AnthropicLLM
from report_analyst.pdf import MistralExtractor, PdfExtractor
from report_analyst.reports import ReportRepository, ReportService, Retriever
from report_analyst.settings import AppSettings


@lru_cache
def get_settings() -> AppSettings:
    """Get the app settings, reading the environment on the first call only.

    Returns:
        The settings.

    Raises:
        pydantic.ValidationError: A required setting is missing or invalid.
    """
    return AppSettings()


@lru_cache
def _anthropic_client(api_key: str) -> anthropic.Anthropic:
    # One client per key, so its connection pool is shared across requests.
    return anthropic.Anthropic(api_key=api_key)


def get_llm(settings: Annotated[AppSettings, Depends(get_settings)]) -> AnthropicLLM:
    """Build the LLM adapter for one request.

    Args:
        settings: The app settings.

    Returns:
        The Anthropic adapter with the configured model.
    """
    return AnthropicLLM(
        _anthropic_client(settings.anthropic_api_key.get_secret_value()), settings.anthropic_model
    )


@lru_cache
def _embedder(model_name: str, models_dir: Path) -> Embedder:
    # Loaded once (about a second) and shared by requests.
    return Embedder(model_name, models_dir)


def get_embedder(settings: Annotated[AppSettings, Depends(get_settings)]) -> Embedder:
    """Get the embedding model chosen in the settings.

    Args:
        settings: The app settings.

    Returns:
        The embedder for `embedding_model`.
    """
    return _embedder(settings.embedding_model, settings.models_dir / "fastembed")


@lru_cache
def _pdf_extractor(api_key: str) -> PdfExtractor:
    # One per key, so its connection pool is shared across requests.
    return MistralExtractor(api_key)


def get_pdf_extractor(settings: Annotated[AppSettings, Depends(get_settings)]) -> PdfExtractor:
    """Get the PDF text extractor: Mistral OCR.

    Args:
        settings: The app settings.

    Returns:
        The extractor.
    """
    return _pdf_extractor(settings.mistral_api_key.get_secret_value())


def get_report_repository(
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> ReportRepository:
    """Get the report storage, for routes that only read what upload stored.

    Args:
        settings: The app settings, for where reports are stored.

    Returns:
        The repository.
    """
    return ReportRepository(settings.reports_dir)


def get_retriever(
    repository: Annotated[ReportRepository, Depends(get_report_repository)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
) -> Retriever:
    """Build the retriever for one request.

    Args:
        repository: Where reports are stored.
        embedder: Embeds Passages and queries.

    Returns:
        The retriever.
    """
    return Retriever(repository, embedder)


def get_report_service(
    repository: Annotated[ReportRepository, Depends(get_report_repository)],
    pdf_extractor: Annotated[PdfExtractor, Depends(get_pdf_extractor)],
    retriever: Annotated[Retriever, Depends(get_retriever)],
    llm: Annotated[AnthropicLLM, Depends(get_llm)],
) -> ReportService:
    """Build the report service for one request.

    Args:
        repository: Where reports are stored.
        pdf_extractor: Extracts a PDF's text.
        retriever: Embeds and searches Passages.
        llm: Extracts the Facts.

    Returns:
        The service.
    """
    return ReportService(repository, pdf_extractor, retriever, FactExtractor(llm))


def get_conversation_repository(
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> ConversationRepository:
    """Get the Conversation storage.

    Args:
        settings: The app settings, for where Conversations are stored.

    Returns:
        The repository.
    """
    return ConversationRepository(settings.conversations_dir)


def get_chat_service(
    reports: Annotated[ReportRepository, Depends(get_report_repository)],
    retriever: Annotated[Retriever, Depends(get_retriever)],
    conversations: Annotated[ConversationRepository, Depends(get_conversation_repository)],
    llm: Annotated[AnthropicLLM, Depends(get_llm)],
) -> ChatService:
    """Build the chat service for one request.

    Args:
        reports: The stored reports.
        retriever: Searches a report's Passages.
        conversations: Where Conversations are stored.
        llm: Writes the Answers.

    Returns:
        The service.
    """
    return ChatService(reports, retriever, conversations, llm)
