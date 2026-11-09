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

    A pair without a year means the Company's latest stored year.

    Args:
        company_year_pairs: The pairs the Question asks about.
        stored_reports: Every stored report.

    Returns:
        The reports found, and the pairs with none.
    """
    reports: list[Report] = []
    missing_pairs = []
    for pair in company_year_pairs:
        reports_for_pair = _reports_for_pair(pair, stored_reports)
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
        relevant_facts += [RelevantFact(report, fact) for fact in fact_kind.facts_in(report_facts)]
    return relevant_facts


def _reports_for_pair(pair: CompanyYearPair, stored_reports: list[Report]) -> list[Report]:
    # The same Company, ignoring case.
    company_reports = [
        r for r in stored_reports if r.company_name.casefold() == pair.company_name.casefold()
    ]
    if not company_reports:
        return []
    # The year asked; if the Question names none, the Company's latest stored year.
    if pair.reporting_year is not None:
        year = pair.reporting_year
    else:
        year = max(r.reporting_year for r in company_reports)
    # Usually one report; more if the user kept both of two uploads for that Company and year.
    return [r for r in company_reports if r.reporting_year == year]
