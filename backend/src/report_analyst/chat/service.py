"""Answers a Question from the extracted Facts: match it to the stored reports, then ask Claude.

Two Claude calls. The first (`matching.py`) says which stored reports the Question is about,
what it names that isn't stored, and whether it asks about the FTE or the Sustainability
Goals. The second answers from those reports' Facts, given as documents Claude cites, so
every quote is a Fact's verified Evidence.
"""

from uuid import UUID

from report_analyst.chat.matching import (
    REPORT_IDS_CONTEXT_KEY,
    ReportMatch,
    Topic,
    build_match_prompt,
)
from report_analyst.chat.models import (
    Answer,
    ChatEvidence,
    ChatReply,
    Conversation,
    NotFoundReason,
    ReportRef,
    Turn,
)
from report_analyst.chat.repository import ConversationRepository
from report_analyst.domain import Evidence, Facts, Report, ReportStatus
from report_analyst.llm import AnthropicLLM, CitedAnswer
from report_analyst.reports import ReportRepository


_HISTORY_TURNS_IN_PROMPT = 3  # earlier Turns shown to the model, so follow-ups make sense

_PROMPT_TEMPLATE = """\
The documents above are facts extracted from companies' annual reports: {topic}. Each title
names the report, the page and the fact; each document is the quote from the report that
states it.

The reports asked about:
{reports}

{history}Question: {question}

{length} Cite the documents that state what you say. If they don't answer the question, say
so in one sentence and cite nothing: an honest "not found" is better than a guess."""

_TOPIC = {
    Topic.FTE: "the total number of full-time equivalents (FTE)",
    Topic.SUSTAINABILITY_GOALS: "the Company's sustainability goals",
}

_ONE_REPORT = (
    "Answer in plain text, in at most three sentences, with the figure and its unit if there"
    " is one."
)
_SEVERAL_REPORTS = (
    "Answer in plain text: a short paragraph for each report, then one or two sentences"
    " comparing them. Say so if a report has no facts on this."
)

# The Facts shown to Claude, each with its report and a short label. A citation's document
# index is a position here.
type _FactsShown = list[tuple[Report, str, Evidence]]


class ConversationNotFoundError(Exception):
    """No Conversation has this id."""


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
            llm: Matches the Question to reports, then writes the Answer from their Facts.
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
        matched_reports, answer = self._build_answer(question, conversation.turns)
        turn = Turn(
            question=question,
            reports=[ReportRef(**r.model_dump()) for r in matched_reports],
            answer=answer,
        )
        # Two Questions at once in one Conversation: the last save wins.
        conversation.turns.append(turn)
        self._conversations.save(conversation)
        return ChatReply(conversation_id=conversation.conversation_id, **turn.model_dump())

    def _build_answer(self, question: str, history: list[Turn]) -> tuple[list[Report], Answer]:
        all_reports = self._reports.list()
        if not all_reports:
            return [], _not_found(NotFoundReason.NO_REPORT)
        match = self._llm.complete(
            build_match_prompt(question, history, all_reports),
            ReportMatch,
            context={REPORT_IDS_CONTEXT_KEY: {r.report_id for r in all_reports}},
        )
        by_id = {r.report_id: r for r in all_reports}
        matched_reports = [by_id[i] for i in dict.fromkeys(match.report_ids)]
        if match.missing or not matched_reports:
            return matched_reports, _not_found(
                NotFoundReason.NO_MATCHING_REPORT, missing=match.missing
            )
        if match.topic is Topic.OTHER:
            return matched_reports, _not_found(NotFoundReason.UNSUPPORTED_TOPIC)
        ready = [r for r in matched_reports if r.status is ReportStatus.SUCCESS]
        if not ready:
            return matched_reports, _not_found(NotFoundReason.REPORT_NOT_READY)
        facts = {r.report_id: self._reports.facts(r.report_id) or Facts() for r in ready}
        shown = _facts_shown(match.topic, ready, facts)
        if not shown:
            return matched_reports, _not_found(NotFoundReason.NOT_IN_REPORT)
        cited_answer = self._llm.cite(
            _build_prompt(question, history, match.topic, matched_reports, facts),
            [
                (f"{r.company_name} {r.reporting_year}, page {e.page}: {label}", e.quote)
                for r, label, e in shown
            ],
        )
        return matched_reports, _to_answer(cited_answer, shown)


def _facts_shown(topic: Topic, reports: list[Report], facts: dict[UUID, Facts]) -> _FactsShown:
    # The Facts on the topic, report by report, each labelled with what it states.
    shown: _FactsShown = []
    for report in reports:
        report_facts = facts[report.report_id]
        if topic is Topic.FTE and report_facts.fte:
            fte = report_facts.fte
            shown.append((report, f"FTE {_format_amount(fte.amount)}", fte.evidence))
        if topic is Topic.SUSTAINABILITY_GOALS:
            for goal in report_facts.goals:
                years = [
                    f"deadline {goal.deadline}" if goal.deadline else "",
                    f"baseline {goal.baseline}" if goal.baseline else "",
                ]
                label = ", ".join(["goal: " + goal.title, *filter(None, years)])
                shown.append((report, label, goal.evidence))
    return shown


def _format_amount(amount: float) -> str:
    # 88497.0 -> "88,497"; 82302.5 -> "82,302.5". Never in exponent notation.
    return f"{amount:,.0f}" if amount.is_integer() else f"{amount:,}"


def _build_prompt(
    question: str,
    history: list[Turn],
    topic: Topic,
    reports: list[Report],
    facts: dict[UUID, Facts],
) -> str:
    # Each report asked about says what was extracted from it, so Claude can say which one
    # has nothing on the topic, or is still processing. An empty earlier answer is a Not
    # Found the app decided; Claude still needs to know there was one.
    return _PROMPT_TEMPLATE.format(
        topic=_TOPIC[topic],
        reports="\n".join(f"- {_report_summary(r, topic, facts)}" for r in reports),
        history="".join(
            f"Earlier question: {turn.question}\n"
            f"Earlier answer: {turn.answer.text or '(not found)'}\n\n"
            for turn in history[-_HISTORY_TURNS_IN_PROMPT:]
        ),
        question=question,
        length=_ONE_REPORT if len(reports) == 1 else _SEVERAL_REPORTS,
    )


def _report_summary(report: Report, topic: Topic, facts: dict[UUID, Facts]) -> str:
    name = f"{report.company_name} {report.reporting_year}"
    if report.status is ReportStatus.PROCESSING:
        return f"{name}: still being processed, so it has no facts yet"
    if report.status is ReportStatus.FAILED:
        return f"{name}: processing failed, so it has no facts"
    report_facts = facts[report.report_id]
    if topic is Topic.FTE:
        return f"{name}: {'FTE extracted' if report_facts.fte else 'no FTE found'}"
    return f"{name}: {len(report_facts.goals)} sustainability goals extracted"


def _to_answer(cited_answer: CitedAnswer, shown: _FactsShown) -> Answer:
    # Each cited Fact becomes Evidence: its own quote, page and boxes, so the UI highlights
    # it as in the report view. No citation means nothing backs the text: Not Found,
    # whatever it says.
    evidence_by_fact: dict[int, ChatEvidence] = {}
    for citation in cited_answer.citations:
        if not citation.text.strip() or citation.document_index in evidence_by_fact:
            continue  # Claude may cite a Fact twice
        report, _, evidence = shown[citation.document_index]
        evidence_by_fact[citation.document_index] = ChatEvidence(
            **evidence.model_dump(),
            report_id=report.report_id,
            company_name=report.company_name,
            reporting_year=report.reporting_year,
        )
    if not evidence_by_fact:
        return _not_found(NotFoundReason.NOT_IN_REPORT, cited_answer.text)
    return Answer(kind="answer", text=cited_answer.text, evidence=list(evidence_by_fact.values()))


def _not_found(reason: NotFoundReason, text: str = "", missing: list[str] | None = None) -> Answer:
    return Answer(kind="not_found", text=text, reason=reason, missing=missing or [])
