"""RAG store — chunks + staleness, not just embeddings.

We keep this dependency-light (no chromadb download in CI). Simple TF overlap scoring
+ metadata-aware ranking. Swap to chromadb/sentence-transformers later behind same interface:
  store.search(query) -> list[RetrievedChunk] with staleness already attached.

Key: every chunk carries superseded_by / still_valid_as_of; store flags stale before it reaches LLM.
"""
from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime

from .models import Chunk, RetrievedChunk, RagResult

DATA_DIR = Path(__file__).parents[2] / "data" / "rag_docs"

# Hard-coded seed chunks — in prod, parse PDFs + extract metadata during ingestion pipeline.
# This keeps tests deterministic without needing PDF parsing.
SEED_CHUNKS: list[Chunk] = [
    Chunk(
        chunk_id="C1-2011-ont",
        doc_id="DOC-2011-ONT-RESET",
        title="ONT Reset Procedure — 2011‑03‑15 (Rev A)",
        text="RTRV-ONT::ONT-001 then INIT-ONT::ONT-001 via Telnet 23. Wait 120s.",
        source_path="data/rag_docs/2011_ont_reset.pdf.txt",
        created_at="2011-03-15",
        still_valid_as_of="2011-03-15",
        superseded_by="DOC-2024-ONT-RESET",
        deprecated=True,
        valid_until="2024-01-10",
        tags=["ont", "reset", "telnet", "2011"],
    ),
    Chunk(
        chunk_id="C2-2011-wifi",
        doc_id="DOC-2011-WIFI",
        title="WiFi Credential Retrieval — 2011‑06‑20",
        text="Query DB: SELECT WIFI_SSID, WIFI_PSK FROM SUBS_TBL WHERE SUBS_ID='<id>' — no check-in or GPS required.",
        source_path="data/rag_docs/2011_wifi_retrieval.pdf.txt",
        created_at="2011-06-20",
        still_valid_as_of="2023-01-10",
        superseded_by="DOC-2023-WIFI-API",
        deprecated=False,
        tags=["wifi", "psk", "database"],
    ),
    Chunk(
        chunk_id="C3-2024-ont",
        doc_id="DOC-2024-ONT-RESET",
        title="ONT Reset Procedure — 2024‑01‑10 (Current)",
        text="Verify on-site via field app check-in + GPS, call adapter.reset_ont(ctx) with policy checks, confirm LINE_STAT before/after.",
        source_path="data/rag_docs/2024_ont_reset.pdf.txt",
        created_at="2024-01-10",
        still_valid_as_of="2026-08-01",
        superseded_by=None,
        deprecated=False,
        tags=["ont", "reset", "current"],
    ),
    Chunk(
        chunk_id="C4-2023-wifi",
        doc_id="DOC-2023-WIFI-API",
        title="WiFi Retrieval via Policy Adapter — 2023‑08‑15 (Current)",
        text="Call tools.get_wifi_credentials_tool with GPS_verified_on_site + field_checkin_active + site match OR support_authorized + ticket_id. Adapter re-checks.",
        source_path="data/rag_docs/2023_wifi_api.pdf.txt",
        created_at="2023-08-15",
        still_valid_as_of="2026-08-01",
        superseded_by=None,
        deprecated=False,
        tags=["wifi", "psk", "policy", "current"],
    ),
]

def _score(query: str, chunk: Chunk) -> float:
    # naive token overlap — deterministic, no model download
    q = set(re.findall(r"\w+", query.lower()))
    t = set(re.findall(r"\w+", (chunk.title + " " + chunk.text).lower()))
    if not q:
        return 0.0
    return len(q & t) / len(q)

def _staleness(chunk: Chunk) -> tuple[str, str | None]:
    now = datetime.utcnow().date().isoformat()
    if chunk.deprecated and chunk.superseded_by:
        return "superseded", f"Deprecated and superseded by {chunk.superseded_by} (valid until {chunk.valid_until})"
    if chunk.superseded_by:
        return "stale", f"Superseded by {chunk.superseded_by}"
    if chunk.deprecated:
        return "deprecated", "Marked deprecated"
    # check still_valid_as_of freshness: >1 year old is stale
    if chunk.still_valid_as_of:
        try:
            still = datetime.fromisoformat(chunk.still_valid_as_of).date()
            age_days = (datetime.utcnow().date() - still).days
            if age_days > 365:
                return "stale", f"Last verified {chunk.still_valid_as_of} (>365 days ago)"
        except Exception:
            pass
    return "fresh", None

class RagStore:
    def __init__(self, chunks: list[Chunk] | None = None):
        self.chunks = chunks or SEED_CHUNKS

    def search(self, query: str, top_k: int = 3, include_stale: bool = False) -> RagResult:
        scored: list[tuple[float, Chunk]] = [(_score(query, c), c) for c in self.chunks]
        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[RetrievedChunk] = []
        warnings: list[str] = []
        for score, chunk in scored[:top_k]:
            if score == 0:
                continue
            staleness, reason = _staleness(chunk)
            # by default, demote superseded/deprecated to bottom but still return with warning
            # if include_stale False, we still return but flagged — caller must not serve stale as current
            rc = RetrievedChunk(
                **chunk.model_dump(),
                score=score,
                staleness=staleness,
                staleness_reason=reason,
            )
            if staleness in ("superseded", "deprecated") and not include_stale:
                warnings.append(f"{chunk.doc_id} is {staleness}: {reason} — do not serve as current")
            results.append(rc)
        # re-sort: fresh first, then stale, then superseded/deprecated
        order = {"fresh": 0, "stale": 1, "superseded": 2, "deprecated": 2}
        results.sort(key=lambda r: (order.get(r.staleness, 3), -r.score))
        return RagResult(query=query, chunks=results, warnings=warnings)

    def get_current(self, doc_id_prefix: str) -> list[Chunk]:
        return [c for c in self.chunks if c.doc_id.startswith(doc_id_prefix) and not c.deprecated and not c.superseded_by]
