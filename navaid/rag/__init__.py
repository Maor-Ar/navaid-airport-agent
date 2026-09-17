"""DuckDB FTS + airport-keyed notes. RAG never ranks. No embedding model."""

from navaid.rag.loader import load_notes, parse_note_markdown
from navaid.rag.search import search_corpus
from navaid.rag.types import RetrievedChunk

__all__ = [
    "RetrievedChunk",
    "load_notes",
    "parse_note_markdown",
    "search_corpus",
]
