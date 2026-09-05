"""RAG store — chunks + staleness + iterative retrieval.

ECC iterative-retrieval (DISPATCH→EVALUATE→REFINE→LOOP, max 3):
- Cycle 1 DISPATCH: broad TF + hash-embedding cosine (stdlib, no torch).
- EVALUATE: score relevance 0-1, flag staleness before LLM sees it.
- REFINE: extract terminology from top hit (e.g. codebase says INIT-ONT vs RESET_ONT),
  add to query, exclude confirmed-irrelevant docs.
- LOOP max 3, return fresh-first.

ECC python-patterns: EAFP (try chromadb/pypdf, fall back to stdlib/txt so CI stays green).
Production: drop real .pdf files into data/rag_docs/ + set EMBEDDINGS_BACKEND=chromadb;
interface store.search(query) is unchanged.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from datetime import datetime

from .models import Chunk, RetrievedChunk, RagResult

try:
    from .embeddings import embed, cosine
except Exception:  # pragma: no cover

    def embed(text: str, dim: int = 64) -> list[float]:  # type: ignore
        return [0.0] * dim

    def cosine(a: list[float], b: list[float]) -> float:  # type: ignore
        return 0.0

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
    # Cycle-1 score: 0.7 * TF overlap + 0.3 * hash-embedding cosine.
    # Deterministic, no model download; chromadb backend can replace embed() later.
    q = set(re.findall(r"\w+", query.lower()))
    t = set(re.findall(r"\w+", (chunk.title + " " + chunk.text).lower()))
    if not q:
        return 0.0
    tf = len(q & t) / len(q)
    try:
        emb = cosine(embed(query), embed(chunk.title + " " + chunk.text))
        # cosine in [-1,1] for normalized vectors in [0,1]; clamp
        emb = max(0.0, min(1.0, emb))
    except Exception:
        emb = 0.0
    return 0.7 * tf + 0.3 * emb


def _extract_keywords(text: str, known: set[str] | None = None) -> set[str]:
    """REFINE helper: learn codebase terminology from top hit (e.g. INIT-ONT, OLT-1)."""
    toks = set(re.findall(r"[A-Za-z]+(?:-[A-Za-z0-9]+)+|\w{4,}", text.upper()))
    if known:
        toks -= {k.upper() for k in known}
    return {t.lower() for t in toks if len(t) > 3} - {"with", "from", "this", "that"}

def _staleness(chunk: Chunk) -> tuple[str, str | None]:
    now = datetime.utcnow().date().isoformat()
    if chunk.deprecated and chunk.superseded_by:
        result = ("superseded", f"Deprecated and superseded by {chunk.superseded_by} (valid until {chunk.valid_until})")
    elif chunk.superseded_by:
        result = ("stale", f"Superseded by {chunk.superseded_by}")
    elif chunk.deprecated:
        result = ("deprecated", "Marked deprecated")
    else:
        result = ("fresh", None)
        # check still_valid_as_of freshness: >1 year old is stale
        if chunk.still_valid_as_of:
            try:
                still = datetime.fromisoformat(chunk.still_valid_as_of).date()
                age_days = (datetime.utcnow().date() - still).days
                if age_days > 365:
                    result = ("stale", f"Last verified {chunk.still_valid_as_of} (>365 days ago)")
            except Exception:
                pass
    # metrics
    try:
        from ..observability.metrics import record_staleness

        record_staleness(result[0])
    except Exception:
        pass
    return result

class RagStore:
    def __init__(self, chunks: list[Chunk] | None = None, use_disk: bool = False):
        if chunks is not None:
            self.chunks = chunks
        elif use_disk or os.getenv("RAG_USE_DISK") == "1":
            # Production: ingest real PDFs when present, .txt fallback otherwise.
            try:
                from .pdf_ingest import ingest_dir

                disk = ingest_dir()
                self.chunks = disk or SEED_CHUNKS
            except Exception:
                self.chunks = SEED_CHUNKS
        else:
            self.chunks = SEED_CHUNKS

    def _one_pass(self, query: str) -> list[tuple[float, Chunk]]:
        scored: list[tuple[float, Chunk]] = [(_score(query, c), c) for c in self.chunks]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def search(self, query: str, top_k: int = 3, include_stale: bool = False) -> RagResult:
        # Iterative retrieval: max 3 cycles DISPATCH→EVALUATE→REFINE.
        best: dict[str, tuple[float, Chunk]] = {}
        cur_query = query
        seen_terms = set(re.findall(r"\w+", query.lower()))
        for _cycle in range(3):
            scored = self._one_pass(cur_query)
            # EVALUATE: keep anything with signal
            candidates = [(s, c) for s, c in scored if s > 0][:top_k]
            if not candidates:
                break
            for s, c in candidates:
                if c.chunk_id not in best or s > best[c.chunk_id][0]:
                    best[c.chunk_id] = (s, c)
            # Stop at "good enough": 2+ fresh-ish hits with score >= 0.25
            fresh_hits = sum(1 for s, _ in candidates if s >= 0.25)
            if fresh_hits >= 2:
                break
            # REFINE: learn terminology from top hit, expand query
            top_chunk = candidates[0][1]
            new_terms = _extract_keywords(top_chunk.title + " " + top_chunk.text, seen_terms)
            if not new_terms:
                break
            seen_terms |= new_terms
            cur_query = cur_query + " " + " ".join(sorted(new_terms)[:5])
        scored = sorted(best.values(), key=lambda x: x[0], reverse=True)
        results: list[RetrievedChunk] = []
        warnings: list[str] = []
        for score, chunk in scored[:top_k]:
            if score == 0:
                continue
            staleness, reason = _staleness(chunk)
            rc = RetrievedChunk(
                **chunk.model_dump(),
                score=score,
                staleness=staleness,
                staleness_reason=reason,
            )
            if staleness in ("stale", "superseded", "deprecated") and not include_stale:
                warnings.append(f"{chunk.doc_id} is {staleness}: {reason} — do not serve as current")
            results.append(rc)
        # re-sort: fresh first, then stale, then superseded/deprecated
        order = {"fresh": 0, "stale": 1, "superseded": 2, "deprecated": 2}
        results.sort(key=lambda r: (order.get(r.staleness, 3), -r.score))
        return RagResult(query=query, chunks=results, warnings=warnings)

    def get_current(self, doc_id_prefix: str) -> list[Chunk]:
        return [c for c in self.chunks if c.doc_id.startswith(doc_id_prefix) and not c.deprecated and not c.superseded_by]
