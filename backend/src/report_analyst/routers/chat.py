"""HTTP routes for chat: ask a Question, reload a Conversation."""

from fastapi import APIRouter, Depends
from http import HTTPStatus
from pydantic import BaseModel, StringConstraints
from typing import Annotated
from uuid import UUID

from report_analyst.chat import (
    ChatReply,
    ChatService,
    Conversation,
    ConversationNotFoundError,
    ConversationRepository,
)
from report_analyst.llm import LLMError
from report_analyst.routers.dependencies import get_chat_service, get_conversation_repository
from report_analyst.routers.errors import ErrorCode, ErrorOut, api_error


router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """A Question, in a new or an existing Conversation.

    Attributes:
        conversation_id: The Conversation to continue; None starts one.
        question: The Question. Its Company and year are read from it, or from the
            earlier Questions for a follow-up.
    """

    conversation_id: UUID | None = None
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]


@router.post(
    "/chat",
    responses={
        HTTPStatus.NOT_FOUND: {"model": ErrorOut},
        HTTPStatus.BAD_GATEWAY: {"model": ErrorOut},
    },
)
def ask(
    request: ChatRequest, service: Annotated[ChatService, Depends(get_chat_service)]
) -> ChatReply:
    """Answer a Question about the FTE or Sustainability Goals, with verbatim Evidence.

    Not Found is a normal answer (`kind: "not_found"`), not an error: also for a Company
    or year with no stored report, or a Question about anything else. Takes about 5-15 s.

    Args:
        request: The Question.
        service: Answers it.

    Returns:
        The Turn and its Conversation's id.

    Raises:
        ApiError: 404 `conversation_not_found`; 502 `answer_failed` if Claude couldn't answer.
    """
    try:
        return service.ask(request.conversation_id, request.question)
    except ConversationNotFoundError as exc:
        raise api_error(HTTPStatus.NOT_FOUND, ErrorCode.CONVERSATION_NOT_FOUND) from exc
    except LLMError as exc:
        raise api_error(HTTPStatus.BAD_GATEWAY, ErrorCode.ANSWER_FAILED) from exc


@router.get(
    "/conversations/{conversation_id}", responses={HTTPStatus.NOT_FOUND: {"model": ErrorOut}}
)
def get_conversation(
    conversation_id: UUID,
    conversations: Annotated[ConversationRepository, Depends(get_conversation_repository)],
) -> Conversation:
    """Get a Conversation with all its Turns, to show it again after a reload.

    Args:
        conversation_id: Its id.
        conversations: Where Conversations are stored.

    Returns:
        The Conversation.

    Raises:
        ApiError: 404 `conversation_not_found`.
    """
    if (conversation := conversations.get(conversation_id)) is None:
        raise api_error(HTTPStatus.NOT_FOUND, ErrorCode.CONVERSATION_NOT_FOUND)
    return conversation
