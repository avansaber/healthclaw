"""Audit rows name the table and the record (healthclaw-mental).

Covers m707: every audit() call in scripts/mental.py must use the
foundation shape audit(conn, SKILL, action, table, record_id), and the
stored rows must be keyed by the record id, never the company id.
"""
import ast
import os

from mental_helpers import call_action, ns, is_ok, load_db_query

mod = load_db_query()

SKILL_NAME = "healthclaw-mental"
ACTION_PREFIX = "mentalhealth-"
TABLE_PREFIX = "healthclaw_"
PRODUCT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mental.py")


def _audit_calls(path):
    with open(path) as handle:
        tree = ast.parse(handle.read())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "audit":
                found.append(node)
    return found


def _rows_by_entity(conn, entity_id):
    from erpclaw_lib.query import Q, P, Table
    table = Table("audit_log")
    query = Q.from_(table).select(
        table.skill, table.action, table.entity_type, table.entity_id,
        table.new_values).where(table.entity_id == P())
    return conn.execute(query.get_sql(), (entity_id,)).fetchall()


def test_every_audit_call_has_the_foundation_shape():
    calls = _audit_calls(PRODUCT_FILE)
    assert len(calls) >= 1
    for call in calls:
        assert len(call.args) >= 5
        second = call.args[1]
        assert (isinstance(second, ast.Name) and second.id == "SKILL") or (
            isinstance(second, ast.Constant) and second.value == SKILL_NAME)
        third = call.args[2]
        assert (isinstance(third, ast.Constant) and isinstance(third.value, str)
                and third.value.startswith(ACTION_PREFIX))
        fourth = call.args[3]
        assert (isinstance(fourth, ast.Constant) and isinstance(fourth.value, str)
                and fourth.value.startswith(TABLE_PREFIX)
                and fourth.value == fourth.value.lower()
                and fourth.value.replace("_", "").isalnum())


def test_audit_rows_are_keyed_by_record_id(conn, env):
    add_assessment = call_action(mod.mentalhealth_add_assessment, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        instrument="PHQ-9",
        administered_date="2026-03-15",
        administered_by_id=env["provider_id"],
        responses="[1,1,2,1,0,1,2,0,1]",
        score=None,
        severity=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(add_assessment), add_assessment
    rows = _rows_by_entity(conn, add_assessment["id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"], rows[0]["entity_type"]) == (
        "healthclaw-mental", "mentalhealth-add-assessment", "healthclaw_assessment")

    add_session = call_action(mod.mentalhealth_add_therapy_session, conn, ns(
        encounter_id=env["encounter_id"],
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        provider_id=env["provider_id"],
        session_type="individual",
        modality="cbt",
        duration_minutes="50",
        session_number="1",
        notes="Audit trail session",
        status=None,
        limit=50, offset=0,
    ))
    assert is_ok(add_session), add_session
    update_session = call_action(mod.mentalhealth_update_therapy_session, conn, ns(
        therapy_session_id=add_session["id"],
        session_type=None,
        modality=None,
        duration_minutes=None,
        notes="Follow-up note for audit check",
        status="cancelled",
        limit=50, offset=0,
    ))
    assert is_ok(update_session), update_session
    rows = _rows_by_entity(conn, add_session["id"])
    assert len(rows) == 2
    triples = [(row["skill"], row["action"], row["entity_type"]) for row in rows]
    assert triples.count((
        "healthclaw-mental", "mentalhealth-add-therapy-session",
        "healthclaw_therapy_session")) == 1
    assert triples.count((
        "healthclaw-mental", "mentalhealth-update-therapy-session",
        "healthclaw_therapy_session")) == 1


def test_no_audit_row_is_keyed_by_company(conn, env):
    add_assessment = call_action(mod.mentalhealth_add_assessment, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        instrument="GAD-7",
        administered_date="2026-03-16",
        administered_by_id=None,
        responses="[2,2,3,2,2,3,2]",
        score=None,
        severity=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(add_assessment), add_assessment
    company_rows = _rows_by_entity(conn, env["company_id"])
    assert [row for row in company_rows if row["skill"] == SKILL_NAME] == []
    from erpclaw_lib.query import Q, P, Table
    table = Table("audit_log")
    query = Q.from_(table).select(
        table.skill, table.action, table.entity_type,
        table.entity_id).where(table.entity_id != P())
    all_rows = conn.execute(query.get_sql(), ("__none__",)).fetchall()
    assert len(all_rows) >= 1
    assert [row for row in all_rows if row["skill"].startswith(TABLE_PREFIX)] == []
