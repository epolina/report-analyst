"""Claude: structured output through Instructor, or cited text. Prompts live with their callers."""

import anthropic
import instructor
import logging

from anthropic.types.beta import BetaContentBlockParam
from collections.abc import Sequence
from instructor.core.exceptions import InstructorRetryException
from pydantic import BaseModel
from typing import Any


logger = logging.getLogger(__name__)


class LLMError(Exception):
    """The model gave no valid output after the retries, or the API call failed."""


class CitedSpan(BaseModel):
    """A span Claude cited: which document, and its text, copied exactly by the API.

    Attributes:
        document_index: The document's index in the list given.
        text: The cited text, verbatim from that document.
    """

    document_index: int
    text: str


class CitedAnswer(BaseModel):
    """Claude's answer from documents, with what it cited. No citations means it cited nothing.

    Attributes:
        text: The answer.
        citations: The cited spans, in the order they back the answer.
    """

    text: str
    citations: list[CitedSpan]


_MAX_TOKENS = 16_000  # the output limit per call
_MAX_ATTEMPTS = 3  # tries for output that passes validation, the first included

# Server-side fallback: if a safety classifier declines, the API reruns on a fallback model.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM:
    """Claude, two ways: structured output, or text citing documents.

    `complete` goes through Instructor, which retries until the output fits a schema. `cite`
    uses the API's citations, which quote the documents exactly.
    """

    def __init__(self, client: anthropic.Anthropic, model: str) -> None:
        """Create the adapter.

        Args:
            client: The Anthropic client. The adapter wraps it with Instructor.
            model: The Claude model ID.
        """
        self._anthropic_client = client
        # beta=True: the refusal fallback below is a beta parameter.
        self._instructor_client = instructor.from_anthropic(client, beta=True)
        self._model = model

    def complete[T: BaseModel](
        self, prompt: str, schema: type[T], context: dict[str, Any] | None = None
    ) -> T:
        """Send a prompt to Claude and get the answer back as an instance of `schema`.

        Args:
            prompt: The full prompt.
            schema: The Pydantic model the answer must validate against.
            context: Given to the schema's validators, e.g. what the answer may cite.

        Returns:
            The validated answer.

        Raises:
            LLMError: If no valid answer came back after the retries, or the API call failed.
        """
        try:
            return self._instructor_client.create(
                response_model=schema,
                messages=[{"role": "user", "content": prompt}],
                # Instructor's max_retries counts the retries after the first try.
                max_retries=_MAX_ATTEMPTS - 1,
                context=context,
                model=self._model,
                max_tokens=_MAX_TOKENS,
                # Instructor forces the tool call by default, which this model rejects (400).
                tool_choice={"type": "auto"},
                # If a safety classifier declines, the API reruns the request on a fallback model.
                betas=[_FALLBACK_BETA],
                fallbacks="default",
            )
        except InstructorRetryException as error:
            # Instructor also wraps API errors (a bad key, an outage) in its retry exception.
            if isinstance(error.__cause__, anthropic.APIError):
                logger.warning("Anthropic API call failed: %s", error.__cause__)
                raise LLMError(f"The model call failed: {error.__cause__.message}") from error
            logger.warning("No valid %s after %d attempts", schema.__name__, error.n_attempts)
            raise LLMError(
                f"No valid {schema.__name__} after {error.n_attempts} attempts"
            ) from error

    def cite(self, prompt: str, documents: Sequence[tuple[str, str]]) -> CitedAnswer:
        """Ask Claude about documents, getting text back with what it cites from them.

        The API copies each cited span from its document, so quotes are verbatim by
        construction. It doesn't combine with structured output, so the answer is plain text.

        Args:
            prompt: The question and instructions, sent after the documents.
            documents: (title, text) pairs; a citation names one by its index here. Claude
                cites the text, not the title.

        Returns:
            The answer and its citations.

        Raises:
            LLMError: The API call failed or the model declined.
        """
        content: list[BetaContentBlockParam] = [
            {
                "type": "document",
                "source": {"type": "text", "media_type": "text/plain", "data": text},
                "title": title,
                "citations": {"enabled": True},
            }
            for title, text in documents
        ]
        content.append({"type": "text", "text": prompt})
        try:
            message = self._anthropic_client.beta.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                messages=[{"role": "user", "content": content}],
                betas=[_FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIError as error:
            logger.warning("Anthropic API call failed: %s", error)
            raise LLMError(f"The model call failed: {error.message}") from error
        if message.stop_reason == "refusal":
            raise LLMError("The model declined to answer")
        text_blocks = [block for block in message.content if block.type == "text"]
        citations = []
        for block in text_blocks:
            for citation in block.citations or []:
                if citation.type == "char_location":  # what a plain-text document is cited by
                    citations.append(
                        CitedSpan(document_index=citation.document_index, text=citation.cited_text)
                    )
        return CitedAnswer(
            text="".join(block.text for block in text_blocks).strip(), citations=citations
        )
