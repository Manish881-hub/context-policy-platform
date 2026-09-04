"""Live-state conflict checker — the second hard part of RAG.

Retrieved 2011 procedure may say "INIT-ONT works for S123" but live provisioning DB
says S123 is on OLT-1 v5 where INIT-ONT is disabled. Serving stale doc confidently
would be wrong. Checker compares chunk text against live DB snapshot.
"""
from __future__ import annotations

from pathlib import Path

from ..provisioning.db import get_connection, run
from .models import RetrievedChunk

# Simple heuristics for demo — in prod, compare structured procedure fields to live telemetry.
def check_conflicts(chunks: list[RetrievedChunk], subscriber_id: str | None = None, db_path: Path | None = None) -> list[RetrievedChunk]:
    if not subscriber_id:
        return chunks
    # fetch live state
    live = None
    try:
        conn = get_connection(db_path)
        cur = run(conn, "SELECT SITE_CD, OLT_ID, LINE_STAT FROM SUBS_TBL WHERE SUBS_ID=?", (subscriber_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            live = dict(row)
    except Exception:
        live = None

    for c in chunks:
        if live and "INIT-ONT" in c.text and live.get("OLT_ID") == "OLT-1":
            # live OLT-1 v5 disables INIT-ONT — 2011 doc conflicts
            c.conflicts_with_live = True
            c.conflict_details = f"Chunk mentions INIT-ONT but live OLT {live['OLT_ID']} for {subscriber_id} is v5 where INIT-ONT disabled"
            c.staleness = "conflicts_with_live"
            c.staleness_reason = c.conflict_details
        if live and "no check-in or GPS required" in c.text.lower():
            c.conflicts_with_live = True
            c.conflict_details = f"Chunk assumes no check-in, but live policy requires GPS+checkin for {subscriber_id}"
            if c.staleness == "fresh":
                c.staleness = "conflicts_with_live"
    return chunks
