"""Hybrid search over plain texts: BM25 keywords plus embedding similarity, fused by rank."""

import math
import numpy as np
import numpy.typing as npt
import re

from collections import Counter

from report_analyst.embedder import Vectors


_WORD_PATTERN = re.compile(r"\w+")
_RRF_K = 60  # the usual constant: dampens how much the very top ranks dominate


def tokenize(text: str) -> list[str]:
    """Split text into lower-case words and numbers, plurals made singular.

    "Scope 3 emissions" → ["scope", "3", "emission"], so a question about "FTE" matches a
    report's "FTEs". Drops a final "s" from words over 3 letters, which also cuts "process"
    to "proces"; harmless, since queries and texts are cut alike. A real stemmer if it starts
    to miss.

    Args:
        text: The text.

    Returns:
        The tokens, in order.
    """
    return [
        w[:-1] if len(w) > 3 and w.endswith("s") else w for w in _WORD_PATTERN.findall(text.lower())
    ]


class BM25:
    """Scores documents against a query by shared words, weighted by how rare each word is."""

    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        """Index the documents.

        Args:
            documents: The texts to rank; at least one.
            k1: How quickly repeats of a word stop adding to the score.
            b: How much longer documents are penalised, from 0 (not) to 1 (fully).
        """
        self._word_counts = [Counter(tokenize(d)) for d in documents]
        self._document_lengths = np.array(
            [sum(c.values()) for c in self._word_counts], dtype=np.float64
        )
        self._average_length = float(self._document_lengths.mean())
        document_frequency = Counter(word for c in self._word_counts for word in c)
        n = len(documents)
        self._idf = {
            w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in document_frequency.items()
        }
        self._k1 = k1
        self._b = b

    def scores(self, query: str) -> npt.NDArray[np.float64]:
        """Score every document against a query.

        Args:
            query: The query.

        Returns:
            One score per document, in order; 0 for a document sharing no word with the query.
        """
        # Scans every document per query; ~1,600 per report is a few ms.
        length_norm = self._k1 * (
            1 - self._b + self._b * self._document_lengths / max(self._average_length, 1e-12)
        )
        scores = np.zeros(len(self._word_counts))
        for word in set(tokenize(query)):
            if (idf := self._idf.get(word)) is None:
                continue
            tf = np.array([c[word] for c in self._word_counts], dtype=np.float64)
            scores += idf * tf * (self._k1 + 1) / (tf + length_norm)
        return scores


class HybridIndex:
    """Ranks texts against a query twice, by BM25 and by cosine similarity, and fuses the ranks.

    Each list gives 1 / (60 + rank), summed. A text high in either list scores well, so exact
    terms ("FTE", "Scope 3") and paraphrases both come through.
    """

    def __init__(self, texts: list[str], vectors: Vectors) -> None:
        """Index the texts.

        Args:
            texts: The texts to search; at least one.
            vectors: One unit-length row per text, in the same order.
        """
        self._bm25 = BM25(texts)
        self._vectors = vectors

    def search(self, query: str, query_vector: Vectors, limit: int) -> list[int]:
        """Find the texts that best match a query.

        Args:
            query: The query, for keyword ranking.
            query_vector: The query embedded with the model the texts were embedded with.
            limit: How many to return.

        Returns:
            The row numbers of up to `limit` texts, best first.
        """
        fused = _reciprocal_rank_scores(self._vectors @ query_vector) + _reciprocal_rank_scores(
            self._bm25.scores(query), only_positive=True
        )
        return [int(i) for i in np.argsort(-fused, kind="stable")[:limit]]


def _reciprocal_rank_scores(
    scores: npt.NDArray[np.floating], only_positive: bool = False
) -> npt.NDArray[np.float64]:
    # Rank 1 is the highest score. With only_positive, a 0 score (no shared word) gets nothing.
    ranks = np.empty(len(scores))
    ranks[np.argsort(-scores, kind="stable")] = np.arange(1, len(scores) + 1)
    fused = 1 / (_RRF_K + ranks)
    if only_positive:
        fused[scores <= 0] = 0
    return fused
