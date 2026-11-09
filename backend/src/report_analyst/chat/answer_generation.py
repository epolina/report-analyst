"""Step 3 of a Question: Claude answers from the relevant Facts, citing them.

Each Fact is one document: its title names the report, page and Fact, and its content is the
report's verbatim quote, the only part Claude can cite. A cited Fact becomes Evidence with its
own quote, page and boxes, so every quote in an answer is a Fact's verified Evidence.
"""

from dataclasses import dataclass

from report_analyst.chat.filtering_fields import FactKind
from report_analyst.chat.models import ChatEvidence, Turn
from report_analyst.chat.relevant_facts import RelevantFact
from report_analyst.domain import Report, ReportStatus
from report_analyst.llm import AnthropicLLM


# Questions and their answers: the answer needs what was said, not only what was asked. The
# filtering-fields prompt has its own count, with the questions only.
_EARLIER_TURNS_IN_PROMPT = 3

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


@dataclass(frozen=True)
class GeneratedAnswer:
    """Claude's answer and the Facts it cited.

    Attributes:
        text: Claude's plain text.
        evidence: One per cited Fact, in the order first cited; empty if it cited nothing.
    """

    text: str
    evidence: list[ChatEvidence]


def generate_answer(
    llm: AnthropicLLM,
    question: str,
    history: list[Turn],
    fact_kind: FactKind,
    reports: list[Report],
    relevant_facts: list[RelevantFact],
) -> GeneratedAnswer:
    """Ask Claude to answer a Question from the relevant Facts, citing them.

    Args:
        llm: Claude.
        question: The Question.
        history: The Conversation's earlier Turns, oldest first.
        fact_kind: The kind of Fact asked about.
        reports: Every report asked about, also those still processing or failed, so Claude
            can say which has nothing.
        relevant_facts: The Facts to answer from; at least one.

    Returns:
        The text and the Evidence of each Fact cited.

    Raises:
        LLMError: The model call failed or the model declined.
    """
    prompt = _build_prompt(question, history, fact_kind, reports, relevant_facts)
    documents = [_as_document(relevant_fact) for relevant_fact in relevant_facts]
    cited_answer = llm.cite(prompt=prompt, documents=documents)

    # A citation points at a document by its position, which is the Fact's position in
    # `relevant_facts`. Each cited Fact is shown once, even if Claude cites it twice.
    cited_positions = dict.fromkeys(
        citation.document_index for citation in cited_answer.citations if citation.text.strip()
    )
    evidence = [_as_chat_evidence(relevant_facts[i]) for i in cited_positions]
    return GeneratedAnswer(text=cited_answer.text, evidence=evidence)


def _as_document(relevant_fact: RelevantFact) -> tuple[str, str]:
    # (title, content), e.g. ("Shell 2024, page 93: FTE 88,497", "<the verbatim quote>").
    # Claude can cite the content only, so whatever it cites is a quote from the report.
    report, fact = relevant_fact.report, relevant_fact.fact
    title = f"{report.company_name} {report.reporting_year}, page {fact.evidence.page}"
    return f"{title}: {fact.as_string()}", fact.evidence.quote


def _as_chat_evidence(relevant_fact: RelevantFact) -> ChatEvidence:
    report = relevant_fact.report
    return ChatEvidence(
        **relevant_fact.fact.evidence.model_dump(),
        report_id=report.report_id,
        company_name=report.company_name,
        reporting_year=report.reporting_year,
    )


def _build_prompt(
    question: str,
    history: list[Turn],
    fact_kind: FactKind,
    reports: list[Report],
    relevant_facts: list[RelevantFact],
) -> str:
    # Each report asked about says what was found in it, so Claude can say which one has
    # nothing on the Fact, or is still processing. An empty earlier answer is a Not Found
    # the app decided; Claude still needs to know there was one.
    return _ANSWER_PROMPT.format(
        fact_description=fact_kind.fact_class.description,
        reports="\n".join(f"- {_report_summary(r, relevant_facts)}" for r in reports),
        earlier_turns="".join(
            f"Earlier question: {turn.question}\n"
            f"Earlier answer: {turn.answer.text or '(not found)'}\n\n"
            for turn in history[-_EARLIER_TURNS_IN_PROMPT:]
        ),
        question=question,
        length=_LENGTH_FOR_ONE_REPORT if len(reports) == 1 else _LENGTH_FOR_SEVERAL_REPORTS,
    )


def _report_summary(report: Report, relevant_facts: list[RelevantFact]) -> str:
    name = f"{report.company_name} {report.reporting_year}"
    if report.status is ReportStatus.PROCESSING:
        return f"{name}: still being processed, so it has no facts yet"
    if report.status is ReportStatus.FAILED:
        return f"{name}: processing failed, so it has no facts"
    found = sum(1 for f in relevant_facts if f.report.report_id == report.report_id)
    return f"{name}: {found} fact{'' if found == 1 else 's'} found"
