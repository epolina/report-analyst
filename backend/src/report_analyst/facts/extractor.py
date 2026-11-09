"""Extracts a Report's Facts: search for candidate Passages, ask Claude, which cites them by id."""

from collections.abc import Callable

from report_analyst.domain import Facts, Passage, Report
from report_analyst.facts.answer import PASSAGES_KEY, FactsAnswer
from report_analyst.llm import AnthropicLLM


type Search = Callable[[str, int], list[Passage]]
"""Finds up to `limit` Passages of the report for a query, best first."""

# One search per kind of fact; the passages found are all Claude reads. Tune the queries (or
# _HITS_PER_QUERY) if a known goal goes missing.
_QUERIES = [
    "total number of employees in full-time equivalents (FTE)",
    "greenhouse gas emissions reduction target net zero scope 1 2 3",
    "renewable energy and electricity target",
    "water use reduction target",
    "packaging recycling and circularity target",
    "sustainable sourcing of raw materials target",
    "gender diversity and inclusion target",
    "health and safety target",
    "biodiversity and nature target",
    "responsible consumption and community target",
]
_HITS_PER_QUERY = 10

_PROMPT = """\
Below are passages from the {year} annual report of {company}, each with an id.

Extract:
1. fte: the Company's total number of FTEs (full-time equivalents) for {year}, for the whole
   group. FTE is not headcount: if only a number of employees or people is given, leave it out.
2. goals: every sustainability target the Company has set for itself, such as emissions,
   energy, water, packaging, sourcing, diversity or safety targets. List each goal once, even
   if several passages repeat it. Skip general aspirations with nothing to measure, and skip
   targets that were already met.

For each fact, cite the id of the passage that states it and a short quote copied character
for character from that passage. If something isn't stated, leave it out: an empty answer is
better than a guess.

{passages}"""


class FactExtractor:
    """Reads the FTE and Sustainability Goals out of a Report. Stores nothing."""

    def __init__(self, llm: AnthropicLLM) -> None:
        """Create the extractor.

        Args:
            llm: Reads the candidate Passages and extracts the facts.
        """
        self._llm = llm

    def extract(self, report: Report, search: Search) -> Facts:
        """Extract a Report's Facts with one Claude call.

        Every fact cites a Passage it was shown; an answer citing one it wasn't goes back to
        Claude with the error. A fact whose quote isn't in its Passage is dropped.

        Args:
            report: The report, for its Company and Reporting Year.
            search: Searches the report's Passages.

        Returns:
            The facts, each with its Passage's page and boxes; empty if the report has no
            Passages.

        Raises:
            LLMError: The model call failed or gave no valid answer.
        """
        found = {p.index: p for q in _QUERIES for p in search(q, _HITS_PER_QUERY)}
        passages = dict(sorted(found.items()))  # reading order
        if not passages:
            return Facts()
        prompt = _PROMPT.format(
            company=report.company_name,
            year=report.reporting_year,
            passages="\n\n".join(
                f'<passage id="{i}" page="{p.page}">\n{p.text}\n</passage>'
                for i, p in passages.items()
            ),
        )
        answer = self._llm.complete(prompt, FactsAnswer, context={PASSAGES_KEY: passages})
        return answer.facts(passages)
