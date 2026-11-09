from uuid import uuid4

from report_analyst.chat.filtering_fields import CompanyYearPair
from report_analyst.chat.relevant_facts import find_reports
from report_analyst.domain import Report, ReportStatus


def report(company_name: str, reporting_year: int) -> Report:
    return Report(
        report_id=uuid4(),
        company_name=company_name,
        reporting_year=reporting_year,
        sha256=str(uuid4()),
        page_count=1,
        status=ReportStatus.SUCCESS,
    )


SHELL_2023, SHELL_2024, ABN_2025 = (
    report("Shell", 2023),
    report("Shell", 2024),
    report("ABN AMRO", 2025),
)
STORED = [SHELL_2023, SHELL_2024, ABN_2025]


def pair(company_name: str, reporting_year: int | None = None) -> CompanyYearPair:
    return CompanyYearPair(company_name=company_name, reporting_year=reporting_year)


def test_a_pair_finds_its_report_ignoring_case() -> None:
    found = find_reports([pair("shell", 2023)], STORED)

    assert (found.reports, found.missing_pairs) == ([SHELL_2023], [])


def test_a_company_without_a_year_is_its_latest_report() -> None:
    assert find_reports([pair("Shell")], STORED).reports == [SHELL_2024]


def test_reports_come_in_the_order_asked_each_once() -> None:
    found = find_reports([pair("ABN AMRO", 2025), pair("Shell", 2024), pair("Shell")], STORED)

    assert found.reports == [ABN_2025, SHELL_2024]


def test_pairs_with_no_stored_report_are_returned_not_raised() -> None:
    found = find_reports([pair("Shell", 2024), pair("ABN AMRO", 2023), pair("Heineken")], STORED)

    assert found.reports == [SHELL_2024]
    assert [p.as_string() for p in found.missing_pairs] == ["ABN AMRO 2023", "Heineken"]


def test_two_reports_kept_for_one_company_and_year_are_both_found() -> None:
    kept_both = report("Shell", 2024)

    assert find_reports([pair("Shell", 2024)], [*STORED, kept_both]).reports == [
        SHELL_2024,
        kept_both,
    ]
