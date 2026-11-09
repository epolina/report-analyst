"""Step 2 of a Question: the stored reports it asks about, and their Facts of the kind asked.

No model call: the Company and year pairs from step 1 are compared with the stored reports.
"""

from dataclasses import dataclass

from report_analyst.chat.filtering_fields import CompanyYearPair, FactKind
from report_analyst.domain import Facts, Fte, Report, SustainabilityGoal
from report_analyst.reports import ReportRepository


@dataclass(frozen=True)
class ReportsFound:
    """The stored reports for some Company and year pairs.

    Attributes:
        reports: The reports for the pairs, in the order asked, each once.
        missing_pairs: The pairs with no stored report.
    """

    reports: list[Report]
    missing_pairs: list[CompanyYearPair]


@dataclass(frozen=True)
class RelevantFact:
    """One Fact a Question asks about, with the report it is from.

    Attributes:
        report: The report.
        fact: The Fact.
    """

    report: Report
    fact: Fte | SustainabilityGoal


def find_reports(
    company_year_pairs: list[CompanyYearPair], stored_reports: list[Report]
) -> ReportsFound:
    """Find the stored reports for each Company and year pair.

    Args:
        company_year_pairs: The pairs the Question asks about.
        stored_reports: Every stored report.

    Returns:
        The reports found, and the pairs with none.
    """
    reports: list[Report] = []
    missing_pairs = []
    for pair in company_year_pairs:
        reports_for_pair = [r for r in stored_reports if _report_matches_pair(r, pair)]
        if not reports_for_pair:
            missing_pairs.append(pair)
        reports += [r for r in reports_for_pair if r not in reports]
    return ReportsFound(reports=reports, missing_pairs=missing_pairs)


def collect_relevant_facts(
    report_repository: ReportRepository, reports: list[Report], fact_kind: FactKind
) -> list[RelevantFact]:
    """Collect the reports' stored Facts of one kind: each FTE, or every goal.

    Args:
        report_repository: Where the Facts are stored.
        reports: The reports, processed successfully.
        fact_kind: The kind of Fact asked about.

    Returns:
        The Facts, report by report.
    """
    relevant_facts: list[RelevantFact] = []
    for report in reports:
        report_facts = report_repository.facts(report.report_id) or Facts()
        if fact_kind is FactKind.FTE and report_facts.fte:
            relevant_facts.append(RelevantFact(report, report_facts.fte))
        if fact_kind is FactKind.SUSTAINABILITY_GOALS:
            relevant_facts += [RelevantFact(report, goal) for goal in report_facts.goals]
    return relevant_facts


def _report_matches_pair(report: Report, pair: CompanyYearPair) -> bool:
    # The same Company (ignoring case) and the same Reporting Year.
    return (
        report.company_name.casefold() == pair.company_name.casefold()
        and report.reporting_year == pair.reporting_year
    )
