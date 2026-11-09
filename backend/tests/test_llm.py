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


def test_cite_sends_each_document_and_returns_the_spans_cited() -> None:
    def reply(request: httpx2.Request) -> httpx2.Response:
        [document, prompt] = json.loads(request.content)["messages"][0]["content"]
        assert document["title"] == "Shell 2024, page 93: FTE 88,497"
        assert document["source"] == {
            "type": "text",
            "media_type": "text/plain",
            "data": "We employed 88,497 FTEs.",
        }
        assert prompt == {"type": "text", "text": "How many FTE?"}
        citation = {
            "type": "char_location",
            "cited_text": "We employed 88,497 FTEs.",
            "document_index": 0,
            "document_title": document["title"],
            "start_char_index": 0,
            "end_char_index": 24,
        }
        text = {"type": "text", "text": "Shell had 88,497 FTE.", "citations": [citation]}
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [text],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    cited = _llm(reply).cite(
        "How many FTE?", [("Shell 2024, page 93: FTE 88,497", "We employed 88,497 FTEs.")]
    )

    assert cited.text == "Shell had 88,497 FTE."
    assert [(c.document_index, c.text) for c in cited.citations] == [
        (0, "We employed 88,497 FTEs.")
    ]
