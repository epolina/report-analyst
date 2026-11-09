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


_PASSAGES_SHOWN = 24  # split across the reports searched, at least _MIN_PER_REPORT each
_MIN_PER_REPORT = 4
_HISTORY_TURNS = 3  # earlier Turns shown to the model, so follow-ups make sense
_YEAR = re.compile(r"\b(?:19|20)\d\d\b")

_PROMPT = """\
The documents above are passages from companies' annual reports; each title names the report
and page. Answer the question using only them.

{history}Question: {question}

Answer in plain text, in at most three sentences, with the figure and its unit if there is
one, citing the passages that state it. If they don't state the answer, say so in one sentence
and cite nothing: an honest "not found" is better than a guess."""


# The Passages found, each with its report. A citation's document index is a position here.
type _Found = list[tuple[Report, Passage]]


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
        elif (found := self._conversations.get(conversation_id)) is None:
            raise ConversationNotFoundError
        else:
            conversation = found
        all_reports = self._reports.list()
        scope = resolve_scope(question, scope, all_reports)
        answer = self._answer(question, scope, all_reports, conversation.turns)
        turn = Turn(question=question, scope=scope, answer=answer)
        # Two Questions at once in one Conversation: the last save wins.
        conversation.turns.append(turn)
        self._conversations.save(conversation)
        return ChatReply(conversation_id=conversation.conversation_id, **turn.model_dump())

    def _answer(
        self, question: str, scope: Scope, all_reports: list[Report], history: list[Turn]
    ) -> Answer:
        ready = _ready_reports(all_reports, scope)
        if isinstance(ready, NotFoundReason):
            return _not_found(ready)
        found = self._search(question, history, ready)
        if not found:
            return _not_found(NotFoundReason.NOT_IN_REPORT)
        cited = self._llm.cite(_prompt(question, history), _documents(found))
        return _to_answer(cited, found)

    def _search(self, question: str, history: list[Turn], ready: list[Report]) -> _Found:
        # A follow-up such as "and in 2025?" searches badly alone, so the previous Question
        # joins the query.
        query = f"{history[-1].question} {question}" if history else question
        per_report = max(_MIN_PER_REPORT, _PASSAGES_SHOWN // len(ready))
        return [
            (r, p) for r in ready for p in self._retriever.search(r.report_id, query, per_report)
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
    companies = {
        r.company_name
        for r in reports
        if re.search(rf"\b{re.escape(r.company_name)}\b", question, re.IGNORECASE)
    }
    years = {int(y) for y in _YEAR.findall(question)} & {r.year for r in reports}
    return Scope(
        company=_pick(companies, scope.company),
        reporting_year=_pick(years, scope.reporting_year),
    )


def _pick[T](named: set[T], chosen: T | None) -> T | None:
    if len(named) == 1:
        return next(iter(named))
    return None if named else chosen


def _body(passage: Passage) -> str | list[str]:
    # A passage with a Markdown table goes in one line per block, so Claude cites the rows it
    # used, not the whole table (a table has no sentences to cite by). Prose stays text.
    lines = [line for line in passage.text.splitlines() if line.strip()]
    return lines if any(line.lstrip().startswith("|") for line in lines) else passage.text


def _ready_reports(all_reports: list[Report], scope: Scope) -> list[Report] | NotFoundReason:
    # The reports in scope that can be searched, or why none can.
    in_scope = [r for r in all_reports if _matches(r, scope)]
    if not in_scope:
        return NotFoundReason.NO_REPORT
    ready = [r for r in in_scope if r.status is ReportStatus.SUCCESS]
    return ready or NotFoundReason.REPORT_NOT_READY


def _prompt(question: str, history: list[Turn]) -> str:
    # An empty answer is a Not Found the app decided; Claude still needs to know there was one.
    return _PROMPT.format(
        history="".join(
            f"Earlier question: {t.question}\n"
            f"Earlier answer: {t.answer.text or '(not found in the reports)'}\n\n"
            for t in history[-_HISTORY_TURNS:]
        ),
        question=question,
    )


def _documents(found: _Found) -> list[tuple[str, str | list[str]]]:
    # One document per Passage, titled with its report and page.
    return [(f"{r.company_name} {r.year}, page {p.page}", _body(p)) for r, p in found]


def _to_answer(cited: CitedAnswer, found: _Found) -> Answer:
    # Each citation becomes Evidence from its Passage. No citation means nothing in the reports
    # backs the text: Not Found, whatever it says.
    evidence: dict[tuple[int, str], ChatEvidence] = {}
    for c in cited.citations:
        report, passage = found[c.document]
        quote = c.text.strip()
        if quote and (c.document, quote) not in evidence:  # Claude may cite a span twice
            evidence[c.document, quote] = ChatEvidence(
                page=passage.page,
                quote=quote,
                boxes=passage.boxes_of(quote),
                report_id=report.report_id,
                company_name=report.company_name,
                year=report.year,
            )
    if not evidence:
        return _not_found(NotFoundReason.NOT_IN_REPORT, cited.text)
    return Answer(kind="answer", text=cited.text, evidence=list(evidence.values()))


def _matches(report: Report, scope: Scope) -> bool:
    return (
        scope.company is None or report.company_name.casefold() == scope.company.casefold()
    ) and (scope.reporting_year is None or report.year == scope.reporting_year)


def _not_found(reason: NotFoundReason, text: str = "") -> Answer:
    return Answer(kind="not_found", text=text, reason=reason)
