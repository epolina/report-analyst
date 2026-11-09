"""Answers a Question from the extracted Facts, in three steps, and keeps the Conversation.

1. Extract the filtering fields (`filtering_fields.py`): Claude reads which Fact (FTE or
   Sustainability Goals) the Question asks about, for which Company and year pairs.
2. Find the relevant Facts (`relevant_facts.py`): the stored reports for those pairs, and
   their Facts of that kind.
3. Generate the answer (`answer_generation.py`): Claude answers from those Facts, citing them.

Every check between the steps is in `_answer_question`. One that fails raises
`QuestionNotAnsweredError`, which `ask` stores as a Not Found.
"""

from uuid import UUID

from report_analyst.chat.answer_generation import generate_answer
from report_analyst.chat.filtering_fields import extract_filtering_fields
from report_analyst.chat.models import (
    Answer,
    ChatReply,
    Conversation,
    NotFoundReason,
    ReportRef,
    Turn,
)
from report_analyst.chat.relevant_facts import collect_relevant_facts, find_reports
from report_analyst.chat.repository import ConversationRepository
from report_analyst.domain import Report, ReportStatus
from report_analyst.llm import AnthropicLLM
from report_analyst.reports import ReportRepository


class ConversationNotFoundError(Exception):
    """No Conversation has this id."""


class QuestionNotAnsweredError(Exception):
    """A step couldn't go on. `ask` stores it as a Not Found Answer with this reason.

    Attributes:
        reason: Why; the UI words it.
        missing: For `no_matching_report`, the pairs with no stored report, e.g. "ABN AMRO 2023".
        reports: The reports the Question was matched to, if it got that far.
        text: Claude's text, if it wrote one.
    """

    def __init__(
        self,
        reason: NotFoundReason,
        *,
        missing: list[str] | None = None,
        reports: list[Report] | None = None,
        text: str = "",
    ) -> None:
        """Create the error.

        Args:
            reason: Why the Question can't be answered.
            missing: The pairs with no stored report.
            reports: The reports the Question was matched to.
            text: Claude's text, if it wrote one.
        """
        super().__init__(reason)
        self.reason = reason
        self.missing = missing or []
        self.reports = reports or []
        self.text = text


class ChatService:
    """Answers Questions about the stored reports' Facts and keeps the Conversation."""

    def __init__(
        self,
        reports: ReportRepository,
        conversations: ConversationRepository,
        llm: AnthropicLLM,
    ) -> None:
        """Create the service.

        Args:
            reports: The stored reports and their Facts.
            conversations: Where Conversations are stored.
            llm: Extracts the filtering fields, then generates the answer.
        """
        self._reports = reports
        self._conversations = conversations
        self._llm = llm

    def ask(self, conversation_id: UUID | None, question: str) -> ChatReply:
        """Answer a Question and add it to its Conversation.

        Only the FTE and the Sustainability Goals are answered: they are the Facts extracted
        while a report is processed. Anything else, or a Company or year with no stored
        report, is a Not Found that says why.

        Args:
            conversation_id: The Conversation to continue; None starts a new one.
            question: The Question.

        Returns:
            The Turn, with the reports it was matched to, and the Conversation's id.

        Raises:
            ConversationNotFoundError: No Conversation has `conversation_id`.
            LLMError: A model call failed; nothing is stored.
        """
        if conversation_id is None:
            conversation = Conversation()
        elif (stored_conversation := self._conversations.get(conversation_id)) is None:
            raise ConversationNotFoundError
        else:
            conversation = stored_conversation
        try:
            turn = self._answer_question(question, conversation.turns)
        except QuestionNotAnsweredError as error:
            turn = _not_answered_turn(question, error)
        # Two Questions at once in one Conversation: the last save wins.
        conversation.turns.append(turn)
        self._conversations.save(conversation)
        return ChatReply(conversation_id=conversation.conversation_id, **turn.model_dump())

    def _answer_question(self, question: str, history: list[Turn]) -> Turn:
        stored_reports = self._reports.list()
        if not stored_reports:
            raise QuestionNotAnsweredError(NotFoundReason.NO_REPORT)

        # 1. Which Fact the Question asks about, for which Company and year pairs.
        filtering_fields = extract_filtering_fields(self._llm, question, history, stored_reports)
        if filtering_fields.fact is None:
            raise QuestionNotAnsweredError(NotFoundReason.UNSUPPORTED_TOPIC)
        if not filtering_fields.company_year_pairs:
            raise QuestionNotAnsweredError(NotFoundReason.NO_COMPANY_NAMED)

        # 2. The stored reports for those pairs, and their Facts of that kind.
        found = find_reports(filtering_fields.company_year_pairs, stored_reports)
        if found.missing_pairs:
            missing = [pair.as_string() for pair in found.missing_pairs]
            raise QuestionNotAnsweredError(
                NotFoundReason.NO_MATCHING_REPORT, missing=missing, reports=found.reports
            )
        ready_reports = [r for r in found.reports if r.status is ReportStatus.SUCCESS]
        if not ready_reports:
            raise QuestionNotAnsweredError(NotFoundReason.REPORT_NOT_READY, reports=found.reports)
        relevant_facts = collect_relevant_facts(self._reports, ready_reports, filtering_fields.fact)
        if not relevant_facts:
            raise QuestionNotAnsweredError(NotFoundReason.NOT_IN_REPORT, reports=found.reports)

        # 3. Claude's answer, citing those Facts.
        generated = generate_answer(
            self._llm, question, history, filtering_fields.fact, found.reports, relevant_facts
        )
        if not generated.evidence:  # nothing cited backs the text, whatever it says
            raise QuestionNotAnsweredError(
                NotFoundReason.NOT_IN_REPORT, reports=found.reports, text=generated.text
            )
        answer = Answer(kind="answer", text=generated.text, evidence=generated.evidence)
        return Turn(question=question, reports=_report_refs(found.reports), answer=answer)


def _report_refs(reports: list[Report]) -> list[ReportRef]:
    return [ReportRef(**r.model_dump()) for r in reports]


def _not_answered_turn(question: str, error: QuestionNotAnsweredError) -> Turn:
    return Turn(
        question=question,
        reports=_report_refs(error.reports),
        answer=Answer(
            kind="not_found", text=error.text, reason=error.reason, missing=error.missing
        ),
    )
