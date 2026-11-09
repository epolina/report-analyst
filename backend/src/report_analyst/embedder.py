"""Embeds text with a local model through fastembed (ONNX, no PyTorch). Knows nothing of reports."""

import numpy as np
import numpy.typing as npt

from fastembed import TextEmbedding
from pathlib import Path


# A batch is padded to its longest text, so texts are embedded shortest first and small batches
# pad less. ~16 passages/s on an 8-core Mac, ~1.5x faster than in document order.
_BATCH_SIZE = 16

type Vectors = npt.NDArray[np.float32]
"""One unit-length row per text, so a dot product is the cosine similarity."""


class Embedder:
    """A local embedding model, e.g. BAAI/bge-small-en-v1.5 (384 dimensions)."""

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        """Load the model from `cache_dir`.

        Args:
            model_name: The fastembed model name.
            cache_dir: Where the model files are: the repo's `models/fastembed`.
        """
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))

    def embed_passages(self, texts: list[str]) -> Vectors:
        """Embed texts to be searched.

        Args:
            texts: The texts. Text past the model's limit (512 tokens for bge) is ignored.

        Returns:
            One row per text, in order; an empty array for no texts.
        """
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        shortest_first = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        sorted_vectors = np.stack(
            list(
                self._model.passage_embed(
                    [texts[i] for i in shortest_first], batch_size=_BATCH_SIZE
                )
            )
        )
        vectors = np.empty_like(sorted_vectors)
        vectors[shortest_first] = sorted_vectors  # back in the order of `texts`
        return _to_unit_length(vectors)

    def embed_query(self, query: str) -> Vectors:
        """Embed a search query. bge models add their query instruction here.

        Args:
            query: The query.

        Returns:
            A single row.
        """
        return _to_unit_length(np.stack(list(self._model.query_embed(query))))


def _to_unit_length(vectors: npt.NDArray[np.floating]) -> Vectors:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    unit: Vectors = (vectors / np.maximum(norms, 1e-12)).astype(np.float32)
    return unit
