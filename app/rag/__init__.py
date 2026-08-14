"""Phase 5 — RAG over historical reports. Structure and style only, never numbers."""

from app.rag.chunking import Chunk, chunk_file, chunk_text  # noqa: F401
from app.rag.index import (  # noqa: F401
    Embedder,
    GeminiEmbedder,
    RedactionFailure,
    Retrieved,
    as_style_prompt,
    index_report,
    retrieve,
)
from app.rag.redaction import PLACEHOLDER, contains_figure, redact_numbers  # noqa: F401
