import json
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, ValidationInfo, field_validator

from report_analyst.llm import AnthropicLLM, LLMError


class Answer(BaseModel):
    company: str


class CheckedAnswer(Answer):
    @field_validator("company")
    @classmethod
    def _known(cls, value: str, info: ValidationInfo) -> str:
        if value not in info.context["companies"]:
            raise ValueError("unknown company")
        return value


def _llm(handler: Any) -> AnthropicLLM:
    client = anthropic.Anthropic(
        api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    return AnthropicLLM(client, "claude-opus-5-5")


def _tool_reply(request: httpx2.Request) -> httpx2.Response:
    assert json.loads(request.content)["messages"][0]["content"] == "Which company?"
    tool_use = {"type": "tool_use", "id": "tu_1", "name": "Answer", "input": {"company": "Shell"}}
    return httpx2.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [tool_use],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )


def _unauthorized(request: httpx2.Request) -> httpx2.Response:
    error = {"type": "authentication_error", "message": "invalid x-api-key"}
    return httpx2.Response(401, json={"type": "error", "error": error})


def test_complete_returns_the_validated_answer() -> None:
    answer = _llm(_tool_reply).complete("Which company?", Answer)

    assert answer.model_dump() == {"company": "Shell"}


def test_complete_wraps_api_errors() -> None:
    with pytest.raises(LLMError, match="The model call failed"):
        _llm(_unauthorized).complete("Which company?", Answer)


def test_complete_validates_with_the_context() -> None:
    llm = _llm(_tool_reply)

    assert (
        llm.complete("Which company?", CheckedAnswer, {"companies": {"Shell"}}).company == "Shell"
    )
    with pytest.raises(LLMError, match="No valid CheckedAnswer"):  # retried, then given up
        llm.complete("Which company?", CheckedAnswer, {"companies": {"ASML"}})


def test_a_table_is_cited_by_whole_rows() -> None:
    from anthropic.types.beta import BetaCitationContentBlockLocation

    from report_analyst.llm import _cited_text

    rows = ["Key figures", "| | 2025 |", "| --- | --- |", "| FTE | 23,126 |", "| NIM | 152 |"]
    citation = BetaCitationContentBlockLocation(
        type="content_block_location",
        cited_text="ignored",
        document_index=0,
        start_block_index=3,
        end_block_index=4,
    )

    assert _cited_text(citation, [("t", rows)]) == "| FTE | 23,126 |"
