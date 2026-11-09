"""Finds a Report's Passages for a query: embeds them, then searches with a cached index."""

from uuid import UUID

from report_analyst.domain import Passage
from report_analyst.embedder import Embedder, Vectors
from report_analyst.index import HybridIndex
from report_analyst.reports.repository import ReportRepository


# Indexes stay in memory between requests, keyed by report and when its Passages were saved, so
# a replaced or retried report is loaded afresh. Unbounded; fine for tens of reports.
_INDEX_CACHE: dict[tuple[UUID, int], tuple[list[Passage], HybridIndex]] = {}


class Retriever:
    """Embeds a Report's Passages while it's processed, and searches them afterwards."""

    def __init__(self, repository: ReportRepository, embedder: Embedder) -> None:
        """Create the retriever.

        Args:
            repository: Where the Passages and their embeddings are stored.
            embedder: Embeds Passages and queries.
        """
        self._repository = repository
        self._embedder = embedder

    def embed(self, passages: list[Passage]) -> Vectors:
        """Embed Passages for search, as `search` will compare them.

        Args:
            passages: The Passages.

        Returns:
            One row per Passage, in the same order.
        """
        return self._embedder.embed_passages([p.search_text for p in passages])

    def search(self, report_id: UUID, query: str, limit: int = 8) -> list[Passage]:
        """Find the Passages of a report that best match a query.

        Args:
            report_id: The report. An unknown report, or one not processed yet, gives no
                Passages.
            query: What to look for, e.g. a question or a topic.
            limit: How many Passages to return.

        Returns:
            Up to `limit` Passages, best first.
        """
        if (cached := self._load_index(report_id)) is None:
            return []
        passages, index = cached
        row_numbers = index.search(query, self._embedder.embed_query(query)[0], limit)
        return [passages[i] for i in row_numbers]

    def _load_index(self, report_id: UUID) -> tuple[list[Passage], HybridIndex] | None:
        version = self._repository.passages_version(report_id)
        if version is None:
            return None
        cache_key = (report_id, version)
        if cache_key not in _INDEX_CACHE:
            passages = self._repository.passages(report_id)
            if not passages:
                return None
            index = HybridIndex(
                [p.search_text for p in passages], self._repository.embeddings(report_id)
            )
            _INDEX_CACHE[cache_key] = (passages, index)
        return _INDEX_CACHE[cache_key]
