"""Answers a Question: finds the reports in scope, searches them, and asks Claude, which cites."""

import re

from uuid import UUID

from report_analyst.chat.models import (
    Answer,
    ChatEvidence,
    ChatReply,
    Conversation,
    NotFoundReason,
    Scope,
    Turn,
)
from report_analyst.chat.repository import ConversationRepository
from report_analyst.domain import Passage, Report, ReportStatus
from report_analyst.llm import AnthropicLLM, CitedAnswer
from report_analyst.reports import ReportRepository, Retriever


# Split across the reports searched, at least _MIN_PASSAGES_PER_REPORT each.
_MAX_PASSAGES_TOTAL = 24
_MIN_PASSAGES_PER_REPORT = 4
_HISTORY_TURNS_IN_PROMPT = 3  # earlier Turns shown to the model, so follow-ups make sense
_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d\d\b")

_PROMPT_TEMPLATE = """\
The documents above are passages from companies' annual reports; each title names the report
and page. Answer the question using only them.

{history}Question: {question}

Answer in plain text, in at most three sentences, with the figure and its unit if there is
one, citing the passages that state it. If they don't state the answer, say so in one sentence
and cite nothing: an honest "not found" is better than a guess."""


# The Passages found, each with its report. A citation's document index is a position here.
type _ReportPassages = list[tuple[Report, Passage]]


class ConversationNotFoundError(Exception):
    """No Conversation has this id."""


class ChatService:
    """Answers Questions about the stored reports and keeps the Conversation."""

    def __init__(
        self,
        reports: ReportRepository,
        retriever: Retriever,
        conversations: ConversationRepository,
        llm: AnthropicLLM,
    ) -> None:
        """Create the service.

        Args:
            reports: The stored reports, to find the ones in scope.
            retriever: Searches a report's Passages.
            conversations: Where Conversations are stored.
            llm: Writes the Answer from the Passages found.
        """
        self._reports = reports
        self._retriever = retriever
        self._conversations = conversations
        self._llm = llm

    def ask(self, conversation_id: UUID | None, question: str, scope: Scope) -> ChatReply:
        """Answer a Question and add it to its Conversation.

        A Company or year named in the Question overrides `scope`, so "How many FTE did Shell
        have in 2024?" searches Shell 2024 whatever the selects say.

        Args:
            conversation_id: The Conversation to continue; None starts a new one.
            question: The Question.
            scope: The Company and year chosen in the UI; None for any.

        Returns:
            The Turn, with the scope it searched, and the Conversation's id.

        Raises:
            ConversationNotFoundError: No Conversation has `conversation_id`.
            LLMError: The model call failed; nothing is stored.
        """
        if conversation_id is None:
            conversation = Conversation()
        elif (stored_conversation := self._conversations.get(conversation_id)) is None:
            raise ConversationNotFoundError
        else:
            conversation = stored_conversation
        all_reports = self._reports.list()
        resolved_scope = resolve_scope(question, scope, all_reports)
        answer = self._build_answer(question, resolved_scope, all_reports, conversation.turns)
        turn = Turn(question=question, scope=resolved_scope, answer=answer)
        # Two Questions at once in one Conversation: the last save wins.
        conversation.turns.append(turn)
        self._conversations.save(conversation)
        return ChatReply(conversation_id=conversation.conversation_id, **turn.model_dump())

    def _build_answer(
        self, question: str, scope: Scope, all_reports: list[Report], history: list[Turn]
    ) -> Answer:
        searchable_reports = _searchable_reports_in_scope(all_reports, scope)
        if isinstance(searchable_reports, NotFoundReason):
            return _not_found(searchable_reports)
        found_passages = self._search_passages(question, history, searchable_reports)
        if not found_passages:
            return _not_found(NotFoundReason.NOT_IN_REPORT)
        cited_answer = self._llm.cite(
            _build_prompt(question, history), _passages_as_documents(found_passages)
        )
        return _to_answer(cited_answer, found_passages)

    def _search_passages(
        self, question: str, history: list[Turn], searchable_reports: list[Report]
    ) -> _ReportPassages:
        # A follow-up such as "and in 2025?" searches badly alone, so the previous Question
        # joins the query.
        query = f"{history[-1].question} {question}" if history else question
        passages_per_report = max(
            _MIN_PASSAGES_PER_REPORT, _MAX_PASSAGES_TOTAL // len(searchable_reports)
        )
        return [
            (report, passage)
            for report in searchable_reports
            for passage in self._retriever.search(report.report_id, query, passages_per_report)
        ]


def resolve_scope(question: str, scope: Scope, reports: list[Report]) -> Scope:
    """Read the Company and year from the Question, falling back to `scope` for each.

    Only stored Companies and years count, so "net zero by 2050" doesn't set the year. Two
    Companies or years named (a comparison) search all of them: that field becomes None.

    Args:
        question: The Question.
        scope: The scope chosen in the UI.
        reports: The stored reports.

    Returns:
        The scope to search.
    """
    companies_named = {
        r.company_name
        for r in reports
        if re.search(rf"\b{re.escape(r.company_name)}\b", question, re.IGNORECASE)
    }
    years_named = {int(y) for y in _YEAR_PATTERN.findall(question)} & {
        r.reporting_year for r in reports
    }
    return Scope(
        company_name=_scope_field(companies_named, scope.company_name),
        reporting_year=_scope_field(years_named, scope.reporting_year),
    )


def _scope_field[T](named_in_question: set[T], chosen_in_ui: T | None) -> T | None:
    if len(named_in_question) == 1:
        return next(iter(named_in_question))
    return None if named_in_question else chosen_in_ui


def _document_body(passage: Passage) -> str | list[str]:
    # A passage with a Markdown table goes in one line per block, so Claude cites the rows it
    # used, not the whole table (a table has no sentences to cite by). Prose stays text.
    lines = [line for line in passage.text.splitlines() if line.strip()]
    return lines if any(line.lstrip().startswith("|") for line in lines) else passage.text


def _searchable_reports_in_scope(
    all_reports: list[Report], scope: Scope
) -> list[Report] | NotFoundReason:
    # The reports in scope that can be searched, or why none can.
    in_scope = [r for r in all_reports if _report_in_scope(r, scope)]
    if not in_scope:
        return NotFoundReason.NO_REPORT
    searchable = [r for r in in_scope if r.status is ReportStatus.SUCCESS]
    return searchable or NotFoundReason.REPORT_NOT_READY


def _build_prompt(question: str, history: list[Turn]) -> str:
    # An empty answer is a Not Found the app decided; Claude still needs to know there was one.
    return _PROMPT_TEMPLATE.format(
        history="".join(
            f"Earlier question: {turn.question}\n"
            f"Earlier answer: {turn.answer.text or '(not found in the reports)'}\n\n"
            for turn in history[-_HISTORY_TURNS_IN_PROMPT:]
        ),
        question=question,
    )


def _passages_as_documents(found_passages: _ReportPassages) -> list[tuple[str, str | list[str]]]:
    # One document per Passage, titled with its report and page.
    return [
        (f"{r.company_name} {r.reporting_year}, page {p.page}", _document_body(p))
        for r, p in found_passages
    ]


def _to_answer(cited_answer: CitedAnswer, found_passages: _ReportPassages) -> Answer:
    # Each citation becomes Evidence from its Passage. No citation means nothing in the reports
    # backs the text: Not Found, whatever it says.
    evidence_by_quote: dict[tuple[int, str], ChatEvidence] = {}
    for citation in cited_answer.citations:
        report, passage = found_passages[citation.document]
        quote = citation.text.strip()
        # Claude may cite a span twice
        if quote and (citation.document, quote) not in evidence_by_quote:
            evidence_by_quote[citation.document, quote] = ChatEvidence(
                page=passage.page,
                quote=quote,
                boxes=passage.boxes_of(quote),
                report_id=report.report_id,
                company_name=report.company_name,
                reporting_year=report.reporting_year,
            )
    if not evidence_by_quote:
        return _not_found(NotFoundReason.NOT_IN_REPORT, cited_answer.text)
    return Answer(kind="answer", text=cited_answer.text, evidence=list(evidence_by_quote.values()))


def _report_in_scope(report: Report, scope: Scope) -> bool:
    return (
        scope.company_name is None
        or report.company_name.casefold() == scope.company_name.casefold()
    ) and (scope.reporting_year is None or report.reporting_year == scope.reporting_year)


def _not_found(reason: NotFoundReason, text: str = "") -> Answer:
    return Answer(kind="not_found", text=text, reason=reason)
