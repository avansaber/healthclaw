"""Audit rows name the table and the record (healthclaw-homehealth).

Covers m707: every audit() call in scripts/homehealth.py must use the
foundation shape audit(conn, SKILL, action, table, record_id), and the
stored rows must be keyed by the record id, never the company id.
"""
import ast
import os

from homehealth_helpers import call_action, ns, is_ok, load_db_query

mod = load_db_query()

SKILL_NAME = "healthclaw-homehealth"
ACTION_PREFIX = "homehealth-"
TABLE_PREFIX = "healthclaw_"
PRODUCT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "homehealth.py")


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
    add_plan = call_action(mod.homehealth_add_care_plan, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        certifying_physician_id=env["physician_id"],
        start_of_care="2026-03-01",
        certification_period_start="2026-03-01",
        certification_period_end="2026-05-01",
        frequency=None,
        goals=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(add_plan), add_plan
    rows = _rows_by_entity(conn, add_plan["id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"], rows[0]["entity_type"]) == (
        "healthclaw-homehealth", "homehealth-add-care-plan", "healthclaw_care_plan")

    add_visit = call_action(mod.homehealth_add_home_visit, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        clinician_id=env["clinician_id"],
        visit_date="2026-03-15",
        visit_type="skilled_nursing",
        start_time="09:00",
        end_time="10:30",
        travel_time_minutes="20",
        mileage="12.50",
        visit_status=None,
        notes="Audit trail visit",
        limit=50, offset=0,
    ))
    assert is_ok(add_visit), add_visit
    update_visit = call_action(mod.homehealth_update_home_visit, conn, ns(
        home_visit_id=add_visit["id"],
        visit_date=None,
        visit_type=None,
        start_time=None,
        end_time=None,
        travel_time_minutes=None,
        mileage=None,
        visit_status="completed",
        notes="Visit completed for audit check",
        limit=50, offset=0,
    ))
    assert is_ok(update_visit), update_visit
    rows = _rows_by_entity(conn, add_visit["id"])
    assert len(rows) == 2
    triples = [(row["skill"], row["action"], row["entity_type"]) for row in rows]
    assert triples.count((
        "healthclaw-homehealth", "homehealth-add-home-visit",
        "healthclaw_home_visit")) == 1
    assert triples.count((
        "healthclaw-homehealth", "homehealth-update-home-visit",
        "healthclaw_home_visit")) == 1


def test_no_audit_row_is_keyed_by_company(conn, env):
    add_visit = call_action(mod.homehealth_add_home_visit, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        clinician_id=env["clinician_id"],
        visit_date="2026-03-16",
        visit_type="pt",
        start_time=None,
        end_time=None,
        travel_time_minutes=None,
        mileage=None,
        visit_status=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(add_visit), add_visit
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
