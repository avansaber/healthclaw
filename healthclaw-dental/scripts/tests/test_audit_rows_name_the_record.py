"""Audit rows name the table and the record (healthclaw-dental).

Covers m707: every audit() call in scripts/dental.py must use the
foundation shape audit(conn, SKILL, action, table, record_id), and the
stored rows must be keyed by the record id, never the company id.
"""
import ast
import os

from dental_helpers import call_action, ns, is_ok, load_db_query

mod = load_db_query()

SKILL_NAME = "healthclaw-dental"
ACTION_PREFIX = "dental-"
TABLE_PREFIX = "healthclaw_"
PRODUCT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dental.py")


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
    add_chart = call_action(mod.dental_add_tooth_chart_entry, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        tooth_number="14",
        condition="cavity",
        noted_date="2026-03-15",
        tooth_system=None,
        surface="MO",
        condition_detail="Class II",
        noted_by_id=env["provider_id"],
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(add_chart), add_chart
    rows = _rows_by_entity(conn, add_chart["id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"], rows[0]["entity_type"]) == (
        "healthclaw-dental", "dental-add-tooth-chart-entry", "healthclaw_tooth_chart")

    add_plan = call_action(mod.dental_add_treatment_plan, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        provider_id=env["provider_id"],
        plan_name="Audit Trail Plan",
        plan_date="2026-03-15",
        phases=None,
        estimated_total="1500.00",
        insurance_estimate="900.00",
        patient_estimate="600.00",
        notes=None,
        status=None,
        limit=50, offset=0,
    ))
    assert is_ok(add_plan), add_plan
    update_plan = call_action(mod.dental_update_treatment_plan, conn, ns(
        treatment_plan_id=add_plan["id"],
        plan_name=None,
        status="accepted",
        estimated_total=None,
        insurance_estimate=None,
        patient_estimate=None,
        phases=None,
        notes="Accepted for audit check",
        limit=50, offset=0,
    ))
    assert is_ok(update_plan), update_plan
    rows = _rows_by_entity(conn, add_plan["id"])
    assert len(rows) == 2
    triples = [(row["skill"], row["action"], row["entity_type"]) for row in rows]
    assert triples.count((
        "healthclaw-dental", "dental-add-treatment-plan", "healthclaw_treatment_plan")) == 1
    assert triples.count((
        "healthclaw-dental", "dental-update-treatment-plan", "healthclaw_treatment_plan")) == 1


def test_no_audit_row_is_keyed_by_company(conn, env):
    add_chart = call_action(mod.dental_add_tooth_chart_entry, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        tooth_number="19",
        condition="decay",
        noted_date="2026-03-15",
        tooth_system=None,
        surface="MOD",
        condition_detail=None,
        noted_by_id=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(add_chart), add_chart
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
