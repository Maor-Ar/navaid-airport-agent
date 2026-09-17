"""RAG result types. Chunks plus sources — never a rank or TEOI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


# Payload / dataclass fields that would leak scoring into retrieval.
_FORBIDDEN_RESULT_KEYS = frozenset({"rank", "teoi", "teoi_traces", "score"})


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One airport-keyed note returned by :func:`search_corpus`.

    ``fts_score`` is DuckDB BM25 relevance (or a LIKE fallback rank), not TEOI.
    It is omitted from :meth:`as_payload` so callers never confuse it with a rank.
    """

    chunk_id: str
    body: str
    airport: str | None
    doc_type: str
    as_of: date | None
    url: str | None
    title: str = ""
    fts_score: float | None = None

    def metadata(self) -> dict[str, Any]:
        return {
            "airport": self.airport,
            "doc_type": self.doc_type,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "url": self.url,
        }

    def source(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "doc_type": self.doc_type,
            "airport": self.airport,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "chunk_id": self.chunk_id,
        }

    def as_payload(self) -> dict[str, Any]:
        """Text chunk + sources + metadata. No rank, no TEOI."""

        payload = {
            "text": self.body,
            "sources": [self.source()],
            "metadata": self.metadata(),
        }
        overlap = _FORBIDDEN_RESULT_KEYS.intersection(payload)
        if overlap:
            raise RuntimeError(f"RAG payload leaked scoring keys: {sorted(overlap)}")
        return payload


__all__ = ["RetrievedChunk"]
