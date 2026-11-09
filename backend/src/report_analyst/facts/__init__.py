"""Fact extraction: Claude reads candidate Passages and cites them by id. Import from here."""

from report_analyst.facts.extractor import FactExtractor, PassageSearch


__all__ = ["FactExtractor", "PassageSearch"]
