"""Answers a Question from the extracted Facts, in three steps.

1. Extract the filtering fields: Claude reads which Fact (FTE or Sustainability Goals) the
   Question asks about, for which Company and year pairs.
2. Find the relevant Facts: the stored reports for those pairs, and their Facts of that kind.
3. Generate the answer: Claude answers from those Facts, citing them, so every quote is a
   Fact's verified Evidence.

A step that can't go on raises `QuestionNotAnsweredError`; `ask` stores it as a Not Found.
"""

from dataclasses import dataclass, field
from uuid import UUID

from report_analyst.chat.filtering_fields import (
    CompanyYearPair,
    FactKind,
    FilteringFields,
    build_filtering_fields_prompt,
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
from report_analyst.domain import Facts, Fte, Report, ReportStatus, SustainabilityGoal
from report_analyst.llm import AnthropicLLM
from report_analyst.reports import ReportRepository


_EARLIER_TURNS_IN_PROMPT = 3  # so a follow-up makes sense

_ANSWER_PROMPT = """\
The documents above are facts extracted from companies' annual reports, all of one kind:
{fact_description} Each title names the report, the page and the fact; each document is the
quote from the report that states it.

The reports asked about:
{reports}

{earlier_turns}Question: {question}

{length} Cite the documents that state what you say. If they don't answer the question, say
so in one sentence and cite nothing: an honest "not found" is better than a guess."""

_LENGTH_FOR_ONE_REPORT = (
    "Answer in plain text, in at most three sentences, with the figure and its unit if there"
    " is one."
)
_LENGTH_FOR_SEVERAL_REPORTS = (
    "Answer in plain text: a short paragraph for each report, then one or two sentences"
    " comparing them. Say so if a report has no facts on this."
)


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


@dataclass(frozen=True)
class RelevantFact:
    """One Fact the Question asks about, with the report it is from."""

    report: Report
    fact: Fte | SustainabilityGoal

    def as_document(self) -> tuple[str, str]:
        """The Fact as a document Claude can cite: (title, content).

        The title names the report, page and Fact, e.g. "Shell 2024, page 93: FTE 88,497".
        The content is the report's verbatim quote, so whatever Claude cites from it is a
        quote from the report. Claude can't cite the title.

        Returns:
            The title and the content.
        """
        report, evidence = self.report, self.fact.evidence
        title = f"{report.company_name} {report.reporting_year}, page {evidence.page}"
        return f"{title}: {self.fact.as_string()}", evidence.quote

    def as_chat_evidence(self) -> ChatEvidence:
        """The Fact's Evidence (quote, page, boxes) with its report, to show in the chat.

        Returns:
            The Evidence.
        """
        return ChatEvidence(
            **self.fact.evidence.model_dump(),
            report_id=self.report.report_id,
            company_name=self.report.company_name,
            reporting_year=self.report.reporting_year,
        )


@dataclass(frozen=True)
class RelevantFacts:
    """The reports a Question asks about, and their Facts of the kind it asks about."""

    reports: list[Report]
    facts: list[RelevantFact] = field(default_factory=list)


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
            turn = self._answer(question, conversation.turns)
        except QuestionNotAnsweredError as error:
            turn = _not_answered_turn(question, error)
        # Two Questions at once in one Conversation: the last save wins.
        conversation.turns.append(turn)
        self._conversations.save(conversation)
        return ChatReply(conversation_id=conversation.conversation_id, **turn.model_dump())

    def _answer(self, question: str, history: list[Turn]) -> Turn:
        stored_reports = self._reports.list()
        if not stored_reports:
            raise QuestionNotAnsweredError(NotFoundReason.NO_REPORT)

        # 1. Which Fact the Question asks about, for which Company and year pairs.
        filtering_fields = self._extract_filtering_fields(question, history, stored_reports)
        if filtering_fields.fact is None:
            raise QuestionNotAnsweredError(NotFoundReason.UNSUPPORTED_TOPIC)
        if not filtering_fields.company_year_pairs:
            raise QuestionNotAnsweredError(NotFoundReason.NO_COMPANY_NAMED)

        # 2. The stored reports for those pairs, and their Facts of that kind.
        relevant_facts = self._find_relevant_facts(
            filtering_fields.company_year_pairs, filtering_fields.fact, stored_reports
        )
        if not relevant_facts.facts:
            raise QuestionNotAnsweredError(
                NotFoundReason.NOT_IN_REPORT, reports=relevant_facts.reports
            )

        # 3. Claude's answer, citing those Facts.
        answer = self._generate_answer(question, history, filtering_fields.fact, relevant_facts)
        if not answer.evidence:  # nothing cited backs the text, whatever it says
            raise QuestionNotAnsweredError(
                NotFoundReason.NOT_IN_REPORT, reports=relevant_facts.reports, text=answer.text
            )
        return Turn(question=question, reports=_report_refs(relevant_facts.reports), answer=answer)

    def _extract_filtering_fields(
        self, question: str, history: list[Turn], stored_reports: list[Report]
    ) -> FilteringFields:
        prompt = build_filtering_fields_prompt(question, history, stored_reports)
        return self._llm.complete(prompt=prompt, schema=FilteringFields)

    def _find_relevant_facts(
        self,
        company_year_pairs: list[CompanyYearPair],
        fact: FactKind,
        stored_reports: list[Report],
    ) -> RelevantFacts:
        reports = _find_reports_for_pairs(company_year_pairs, stored_reports)
        ready_reports = [r for r in reports if r.status is ReportStatus.SUCCESS]
        if not ready_reports:
            raise QuestionNotAnsweredError(NotFoundReason.REPORT_NOT_READY, reports=reports)
        facts = self._collect_relevant_facts(ready_reports, fact)
        return RelevantFacts(reports=reports, facts=facts)

    def _collect_relevant_facts(self, reports: list[Report], fact: FactKind) -> list[RelevantFact]:
        # Each report's stored Facts of the kind asked about: its FTE, or all its goals.
        relevant_facts: list[RelevantFact] = []
        for report in reports:
            report_facts = self._reports.facts(report.report_id) or Facts()
            if fact is FactKind.FTE and report_facts.fte:
                relevant_facts.append(RelevantFact(report, report_facts.fte))
            if fact is FactKind.SUSTAINABILITY_GOALS:
                relevant_facts += [RelevantFact(report, goal) for goal in report_facts.goals]
        return relevant_facts

    def _generate_answer(
        self, question: str, history: list[Turn], fact: FactKind, relevant_facts: RelevantFacts
    ) -> Answer:
        prompt = _build_answer_prompt(question, history, fact, relevant_facts)
        documents = [relevant_fact.as_document() for relevant_fact in relevant_facts.facts]
        cited_answer = self._llm.cite(prompt=prompt, documents=documents)

        # A citation points at a document by its position, which is the Fact's position in
        # `relevant_facts.facts`. Each cited Fact is shown once, even if Claude cites it twice.
        cited_positions = dict.fromkeys(
            citation.document_index for citation in cited_answer.citations if citation.text.strip()
        )
        evidence = [relevant_facts.facts[i].as_chat_evidence() for i in cited_positions]
        return Answer(kind="answer", text=cited_answer.text, evidence=evidence)


def _find_reports_for_pairs(
    company_year_pairs: list[CompanyYearPair], stored_reports: list[Report]
) -> list[Report]:
    # The stored reports for each pair, in the order asked. A pair with no stored report
    # stops the Question, naming every such pair.
    reports: list[Report] = []
    missing = []
    for pair in company_year_pairs:
        reports_for_pair = [r for r in stored_reports if _report_matches_pair(r, pair)]
        if not reports_for_pair:
            missing.append(f"{pair.company_name} {pair.reporting_year}")
        reports += [r for r in reports_for_pair if r not in reports]
    if missing:
        raise QuestionNotAnsweredError(
            NotFoundReason.NO_MATCHING_REPORT, missing=missing, reports=reports
        )
    return reports


def _report_matches_pair(report: Report, pair: CompanyYearPair) -> bool:
    # The same Company (ignoring case) and the same Reporting Year.
    return (
        report.company_name.casefold() == pair.company_name.casefold()
        and report.reporting_year == pair.reporting_year
    )


def _build_answer_prompt(
    question: str, history: list[Turn], fact: FactKind, relevant_facts: RelevantFacts
) -> str:
    # Each report asked about says what was found in it, so Claude can say which one has
    # nothing on the Fact, or is still processing. An empty earlier answer is a Not Found
    # the app decided; Claude still needs to know there was one.
    reports = relevant_facts.reports
    return _ANSWER_PROMPT.format(
        fact_description=fact.fact_class.description,
        reports="\n".join(f"- {_report_summary(r, fact, relevant_facts)}" for r in reports),
        earlier_turns="".join(
            f"Earlier question: {turn.question}\n"
            f"Earlier answer: {turn.answer.text or '(not found)'}\n\n"
            for turn in history[-_EARLIER_TURNS_IN_PROMPT:]
        ),
        question=question,
        length=_LENGTH_FOR_ONE_REPORT if len(reports) == 1 else _LENGTH_FOR_SEVERAL_REPORTS,
    )


def _report_summary(report: Report, fact: FactKind, relevant_facts: RelevantFacts) -> str:
    name = f"{report.company_name} {report.reporting_year}"
    if report.status is ReportStatus.PROCESSING:
        return f"{name}: still being processed, so it has no facts yet"
    if report.status is ReportStatus.FAILED:
        return f"{name}: processing failed, so it has no facts"
    found = sum(1 for f in relevant_facts.facts if f.report.report_id == report.report_id)
    if fact is FactKind.FTE:
        return f"{name}: {'FTE found' if found else 'no FTE found'}"
    return f"{name}: {found} sustainability goal{'' if found == 1 else 's'} found"


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
