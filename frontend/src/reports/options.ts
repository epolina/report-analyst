// What the report filters and the chat scope offer, so the two always read the same.
import type { Report } from "../api";

export const ALL_COMPANIES = "All companies";
export const ANY_YEAR = "Any year";
export const ADD_REPORT = "Add a report PDF";

export const unique = <T>(xs: T[]) => [...new Set(xs)];
export const companiesOf = (reports: Report[]) => unique(reports.map((r) => r.company_name)).sort();
export const yearsOf = (reports: Report[]) => unique(reports.map((r) => r.reporting_year)).sort((a, b) => b - a);
