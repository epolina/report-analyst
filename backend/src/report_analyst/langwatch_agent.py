"""Connects the report analyst to LangWatch, so scenario tests run against the real chat service."""

import asyncio
import langwatch

from uuid import UUID

from report_analyst.chat import Scope
from report_analyst.routers.dependencies import (
    get_chat_service,
    get_conversation_repository,
    get_embedder,
    get_llm,
    get_report_repository,
    get_retriever,
    get_settings,
)


@langwatch.connect_agent(name="report-analyst")
async def report_analyst(messages: list[dict], session: str | None = None) -> langwatch.AgentReply:
    """Answer the latest question with the chat service, keeping the Conversation as the session.

    Args:
        messages: The conversation so far, OpenAI-style; the last message is the question.
        session: The Conversation id from the previous turn, None on the first.

    Returns:
        The Answer text, with the Conversation id as the session for the next turn.
    """
    settings = get_settings()
    reports = get_report_repository(settings)
    service = get_chat_service(
        reports,
        get_retriever(reports, get_embedder(settings)),
        get_conversation_repository(settings),
        get_llm(settings),
    )
    reply = await asyncio.to_thread(
        service.ask, UUID(session) if session else None, messages[-1]["content"], Scope()
    )
    return langwatch.AgentReply(
        reply.answer.text or "Not found in the reports.", session=str(reply.conversation_id)
    )
