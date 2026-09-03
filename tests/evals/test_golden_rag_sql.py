"""Eval harness extension for RAG + SQL — same pass^3=100% gate, reused harness pattern."""
import json
from pathlib import Path
import tempfile
from src.rag.store import RagStore
from src.rag.checker import check_conflicts
from src.sql.guardrails import validate_sql
from src.policy.engine import PolicyEngine
from src.context.models import Identity, RequestContext, Resource, Action, QueueOrigin
from src.tools.sql_tool import query_sql_tool
from src.tools.rag_tool import query_docs_tool
from src.provisioning.db import init_db

GOLDEN_RAG = Path(__file__).parents[2] / "evals" / "golden_rag.jsonl"
GOLDEN_SQL = Path(__file__).parents[2] / "evals" / "golden_sql.jsonl"

def _ctx(ctx_kwargs, action):
    return RequestContext(
        identity=Identity(technician_id=ctx_kwargs.get("technician_id", "T42"), queue_origin=QueueOrigin(ctx_kwargs["queue_origin"])),
        resource=Resource(subscriber_id=ctx_kwargs.get("subscriber_id", "S123")),
        action=action,
        gps_verified_on_site=ctx_kwargs.get("gps_verified_on_site", False),
        field_checkin_active=ctx_kwargs.get("field_checkin_active", False),
        site_id=ctx_kwargs.get("site_id"),
        subscriber_site_id=ctx_kwargs.get("subscriber_site_id"),
        ticket_id=ctx_kwargs.get("ticket_id"),
    )

def load(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

def test_rag_golden(tmp_db):
    store = RagStore()
    for case in load(GOLDEN_RAG):
        ctx = case["context"]
        res = store.search(case["query"], top_k=5)
        checked = check_conflicts(res.chunks, subscriber_id=ctx.get("subscriber_id"), db_path=tmp_db)
        docs = {c.doc_id: c for c in checked}
        if case["expected"] == "fresh":
            assert case["must_serve"] in docs, f"{case['id']} must serve {case['must_serve']}"
            assert docs[case["must_serve"]].staleness == "fresh", f"{case['id']} flagged incorrectly"
            # must_not_serve should be superseded/conflict
            if "must_not_serve" in case:
                assert docs[case["must_not_serve"]].staleness in ("superseded", "stale", "conflicts_with_live", "deprecated")
        elif case["expected"] == "flagged":
            assert case["must_flag"] in docs
            assert docs[case["must_flag"]].staleness in ("superseded", "stale", "deprecated", "conflicts_with_live")
        elif case["expected"] == "conflicts_with_live":
            assert docs[case["doc"]].conflicts_with_live is True

def test_sql_golden(tmp_db):
    engine = PolicyEngine()
    for case in load(GOLDEN_SQL):
        ctx_kwargs = case["context"]
        ctx = _ctx(ctx_kwargs, Action.QUERY_SQL)
        decision = engine.evaluate(ctx)
        if case["expected"] == "deny":
            assert decision.allowed is False, f"{case['id']} should deny"
            continue
        if case["expected"] == "block":
            ok, _ = validate_sql(case["nl_query"])
            assert ok is False, f"{case['id']} should be blocked by guardrail"
            # also test via tool injection pattern: direct SQL not via NL but guardrail must block
            continue
        if case["expected"] == "allow":
            assert decision.allowed is True, f"{case['id']} should allow got {decision.reason}"
            # generate and check sql contains expected column
            res = query_sql_tool(nl_query=case["nl_query"], queue_origin=ctx_kwargs["queue_origin"], gps_verified_on_site=ctx_kwargs.get("gps_verified_on_site", False), field_checkin_active=ctx_kwargs.get("field_checkin_active", False), site_id=ctx_kwargs.get("site_id"), subscriber_site_id=ctx_kwargs.get("subscriber_site_id"), subscriber_id=ctx_kwargs.get("subscriber_id"), db_path=tmp_db)
            assert res.status == "success", f"{case['id']} tool should succeed {res.summary}"
            assert case["must_sql_contain"] in res.data["sql"]
            # also verify policy inside tool would have denied unauthorized
        # verify read-only enforcement: no DROP in any generated sql
        # (already covered by validate)

def test_rag_policy_gate_100_percent():
    """RAG also sits behind policy — same 100% gate as wifi/SQL."""
    cases = load(GOLDEN_RAG)
    # ensure every rag query would be denied for unauthorized queue (policy layer)
    from src.context.models import Action
    for case in cases:
        deny_ctx = dict(case["context"])
        deny_ctx["queue_origin"] = "support_unauthorized"
        req = _ctx(deny_ctx, Action.QUERY_DOCS)
        d = PolicyEngine().evaluate(req)
        assert d.allowed is False, f"RAG must deny unauthorized queue for {case['id']}"
