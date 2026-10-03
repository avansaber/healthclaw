"""Audit rows name the table and the record (healthclaw-vet).

Covers m707: every audit() call in scripts/vet.py must use the
foundation shape audit(conn, SKILL, action, table, record_id), and the
stored rows must be keyed by the record id, never the company id.
"""
import ast
import os

from vet_helpers import call_action, ns, is_ok, load_db_query, seed_patient

mod = load_db_query()

SKILL_NAME = "healthclaw-vet"
ACTION_PREFIX = "vet-"
TABLE_PREFIX = "healthclaw_"
PRODUCT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vet.py")


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
    patient_id = seed_patient(conn, env["company_id"], "Ziggy", "Quillpaw")
    add_animal = call_action(mod.vet_add_animal_patient, conn, ns(
        company_id=env["company_id"],
        patient_id=patient_id,
        species="feline",
        breed="Shorthair",
        color="grey",
        weight_kg="4.25",
        microchip_id="CHIP-AUDIT-001",
        spay_neuter_status="neutered",
        reproductive_status=None,
        limit=50, offset=0,
    ))
    assert is_ok(add_animal), add_animal
    rows = _rows_by_entity(conn, add_animal["id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"], rows[0]["entity_type"]) == (
        "healthclaw-vet", "vet-add-animal-patient", "healthclaw_animal_patient")

    add_board = call_action(mod.vet_add_boarding, conn, ns(
        company_id=env["company_id"],
        animal_patient_id=env["animal_patient_id"],
        check_in_date="2026-03-15",
        check_out_date="2026-03-20",
        kennel_number="K-99",
        feeding_instructions="Twice daily",
        medication_schedule=None,
        special_needs=None,
        daily_rate="45.00",
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(add_board), add_board
    update_board = call_action(mod.vet_update_boarding, conn, ns(
        boarding_id=add_board["id"],
        check_out_date="2026-03-20",
        kennel_number=None,
        feeding_instructions=None,
        medication_schedule=None,
        special_needs=None,
        daily_rate=None,
        status="checked_out",
        notes="Picked up for audit check",
        limit=50, offset=0,
    ))
    assert is_ok(update_board), update_board
    rows = _rows_by_entity(conn, add_board["id"])
    assert len(rows) == 2
    triples = [(row["skill"], row["action"], row["entity_type"]) for row in rows]
    assert triples.count((
        "healthclaw-vet", "vet-add-boarding", "healthclaw_boarding")) == 1
    assert triples.count((
        "healthclaw-vet", "vet-update-boarding", "healthclaw_boarding")) == 1


def test_no_audit_row_is_keyed_by_company(conn, env):
    add_board = call_action(mod.vet_add_boarding, conn, ns(
        company_id=env["company_id"],
        animal_patient_id=env["animal_patient_id"],
        check_in_date="2026-03-16",
        check_out_date=None,
        kennel_number="K-98",
        feeding_instructions=None,
        medication_schedule=None,
        special_needs=None,
        daily_rate=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(add_board), add_board
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
