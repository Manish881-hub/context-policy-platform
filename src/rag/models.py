"""RAG models — staleness first, not embeddings.

2011 PDFs need metadata beyond vector:
- superseded_by: which doc/chunk replaces this
- still_valid_as_of: last time a human verified this procedure still matches live system
- deprecated: hard flag
"""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    text: str
    source_path: str = Field(description="e.g. data/rag_docs/2011_ont_reset.pdf#page3")
    # staleness metadata — the hard part
    created_at: str = Field(description="original doc date, e.g. 2011-03-15")
    still_valid_as_of: str | None = None  # last human verification
    superseded_by: str | None = None      # doc_id that supersedes this
    deprecated: bool = False
    valid_until: str | None = None
    tags: list[str] = Field(default_factory=list)


class RetrievedChunk(Chunk):
    score: float = 0.0
    staleness: str = Field(description="fresh|stale|superseded|deprecated|conflicts_with_live")
    staleness_reason: str | None = None
    # live-state conflict flag
    conflicts_with_live: bool = False
    conflict_details: str | None = None


class RagResult(BaseModel):
    query: str
    chunks: list[RetrievedChunk]
    warnings: list[str] = Field(default_factory=list)
