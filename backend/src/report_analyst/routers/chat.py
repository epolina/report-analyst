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
    Scope,
)
from report_analyst.llm import LLMError
from report_analyst.routers.dependencies import get_chat_service, get_conversation_repository
from report_analyst.routers.errors import ErrorCode, ErrorOut, error


router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """A Question, in a new or an existing Conversation.

    Attributes:
        conversation_id: The Conversation to continue; None starts one.
        question: The Question.
        scope: The Company and year chosen in the UI. Ones named in the Question win.
    """

    conversation_id: UUID | None = None
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    scope: Scope = Scope()


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
    """Answer a Question from the reports in scope, with verbatim Evidence, or say Not Found.

    Not Found is a normal answer (`kind: "not_found"`), not an error. Takes about 5-15 s.

    Args:
        request: The Question.
        service: Answers it.

    Returns:
        The Turn and its Conversation's id.

    Raises:
        ApiError: 404 `conversation_not_found`; 502 `answer_failed` if Claude couldn't answer.
    """
    try:
        return service.ask(request.conversation_id, request.question, request.scope)
    except ConversationNotFoundError as exc:
        raise error(HTTPStatus.NOT_FOUND, ErrorCode.CONVERSATION_NOT_FOUND) from exc
    except LLMError as exc:
        raise error(HTTPStatus.BAD_GATEWAY, ErrorCode.ANSWER_FAILED) from exc


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
        raise error(HTTPStatus.NOT_FOUND, ErrorCode.CONVERSATION_NOT_FOUND)
    return conversation
