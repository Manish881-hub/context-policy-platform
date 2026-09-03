"""Seams: SemanticLayer.introspect, guardrails.validate, generator.generate, policy+guardrail tool."""
import tempfile
from pathlib import Path
from src.sql.semantic_layer import SemanticLayer
from src.sql.guardrails import validate_sql, execute_readonly
from src.sql.generator import SqlGenerator
from src.provisioning.db import init_db

def test_semantic_layer_introspects(tmp_db):
    sl = SemanticLayer(db_path=tmp_db)
    info = sl.introspect()
    assert "SUBS_TBL" in info
    assert "WIFI_PSK" in info["SUBS_TBL"]
    assert info["SUBS_TBL"]["WIFI_PSK"]["sensitive"] is True
    # samples present
    assert len(info["SUBS_TBL"]["WIFI_PSK"]["samples"]) >= 1

def test_guardrail_blocks_drop():
    ok, reason = validate_sql("SELECT * FROM SUBS_TBL; DROP TABLE SUBS_TBL")
    assert ok is False
    assert "DROP" in reason

def test_guardrail_blocks_non_select():
    ok, _ = validate_sql("UPDATE SUBS_TBL SET WIFI_PSK='x'")
    assert ok is False

def test_guardrail_allows_select():
    ok, _ = validate_sql("SELECT SUBS_ID, LINE_STAT FROM SUBS_TBL WHERE SUBS_ID='S123'")
    assert ok is True

def test_generator_uses_semantic(tmp_db):
    gen = SqlGenerator(db_path=tmp_db)
    res = gen.generate("line status for S123", subscriber_id="S123")
    assert res["status"] == "success"
    assert "SUBS_TBL" in res["sql"]
    assert "LINE_STAT" in res["sql"]

def test_sql_tool_policy_and_guardrail(tmp_db):
    from src.tools.sql_tool import query_sql_tool
    # field_app allowed with checkin
    res = query_sql_tool(nl_query="line status for S123", queue_origin="field_app", gps_verified_on_site=True, field_checkin_active=True, site_id="SITE_A", subscriber_site_id="SITE_A", subscriber_id="S123", db_path=tmp_db)
    assert res.status == "success"
    assert "rows" in res.data
    # unauthorized denied
    res2 = query_sql_tool(nl_query="line status for S123", queue_origin="support_unauthorized", subscriber_id="S123", db_path=tmp_db)
    assert res2.status == "error"
    assert "DENIED" in res2.summary
    # injection via sql that would be rejected if generated: test direct guardrail
    ok, _ = validate_sql("SELECT * FROM SUBS_TBL; DELETE FROM SUBS_TBL")
    assert ok is False

def test_execute_readonly_limits(tmp_db):
    init_db(tmp_db)
    res = execute_readonly("SELECT * FROM SUBS_TBL", db_path=tmp_db)
    assert res["status"] == "success"
    assert "LIMIT 100" in res["sql"] or len(res["rows"]) <= 100
