"""Seam: RagStore.search + checker — not internal scoring."""
from pathlib import Path
import tempfile
from src.rag.store import RagStore
from src.rag.checker import check_conflicts
from src.provisioning.db import init_db

def test_staleness_flag_superseded():
    store = RagStore()
    res = store.search("ont reset", top_k=3)
    # should flag 2011 doc as superseded
    docs = {c.doc_id: c for c in res.chunks + [c for c in store.chunks if c.doc_id == "DOC-2011-ONT-RESET"]}
    # search will surface both, but stale check
    superseded = [c for c in res.chunks if c.doc_id == "DOC-2011-ONT-RESET"]
    assert superseded
    c = superseded[0]
    assert c.staleness in ("superseded", "deprecated", "conflicts_with_live")
    assert "superseded" in (c.staleness_reason or "").lower() or c.conflicts_with_live

def test_fresh_doc_not_flagged():
    store = RagStore()
    res = store.search("wifi retrieval policy adapter", top_k=3)
    fresh = [c for c in res.chunks if c.doc_id == "DOC-2023-WIFI-API"]
    assert fresh
    assert fresh[0].staleness == "fresh"

def test_conflicts_with_live_for_ont():
    store = RagStore()
    tmp = Path(tempfile.mktemp(suffix=".db"))
    init_db(tmp)
    res = store.search("ont reset", top_k=3)
    checked = check_conflicts(res.chunks, subscriber_id="S123", db_path=tmp)
    # 2011 doc mentions INIT-ONT but S123 is on OLT-1 v5 disabled
    conflicted = [c for c in checked if c.doc_id == "DOC-2011-ONT-RESET"]
    assert conflicted
    assert conflicted[0].conflicts_with_live is True
    assert conflicted[0].staleness == "conflicts_with_live"

def test_stale_doc_warns_do_not_serve(tmp_db):
    # Regression: DOC-2011-WIFI is superseded (stale) yet top-scoring — must warn,
    # never served silently next to fresh. Same bug class as docs/breakage.md.
    store = RagStore()
    res = store.search("wifi password retrieval no checkin", top_k=5)
    stale = [c for c in res.chunks if c.doc_id == "DOC-2011-WIFI"]
    assert stale and stale[0].staleness == "stale"
    assert any("DOC-2011-WIFI" in w and "do not serve as current" in w for w in res.warnings)
    from src.tools.rag_tool import query_docs_tool
    tool_res = query_docs_tool(query="wifi password retrieval no checkin", queue_origin="field_app", gps_verified_on_site=True, field_checkin_active=True, subscriber_id="S123", db_path=tmp_db)
    assert tool_res.status == "success"
    assert any("DOC-2011-WIFI" in w for w in tool_res.data["warnings"])

def test_rag_tool_policy_enforced(tmp_db):
    from src.tools.rag_tool import query_docs_tool
    # unauthorized queue should be denied before RAG search
    res = query_docs_tool(query="wifi procedure", queue_origin="support_unauthorized", subscriber_id="S123", db_path=tmp_db)
    assert res.status == "error"
    assert "DENIED" in res.summary
    # authorized field_app allowed
    res2 = query_docs_tool(query="ont reset", queue_origin="field_app", gps_verified_on_site=True, field_checkin_active=True, site_id="SITE_A", subscriber_site_id="SITE_A", subscriber_id="S123", db_path=tmp_db)
    assert res2.status == "success"
    assert res2.data is not None
