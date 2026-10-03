"""Behavioural tests for health-update-medication.

Action driven:
  - health-update-medication (adv_pharmacy.py update_medication)

The handler rewrites one healthclaw_medication master row. Money lives in that
row's unit_price TEXT column as an exact Decimal string; the action never
reaches the general ledger, so there are no ledger legs to assert (gl_entry
stays empty) and every monetary assertion below compares exact strings,
never float.
"""
from decimal import Decimal

from health_helpers import call_action, ns, is_error, is_ok, load_db_query

from erpclaw_lib.query import Field, P, Q, Table, fn

mod = load_db_query()


def _read_row(conn, table, row_id):
    """Read one stored row back through a PyPika-built query."""
    t = Table(table)
    row = conn.execute(
        Q.from_(t).select(t.star).where(Field("id") == P()).get_sql(),
        (row_id,),
    ).fetchone()
    assert row is not None, f"expected a row in {table} id={row_id}"
    return dict(row)


def _table_count(conn, table):
    t = Table(table)
    return conn.execute(
        Q.from_(t).select(fn.Count("*")).get_sql()).fetchone()[0]


def _refusal_message(result):
    return result.get("message", "") + result.get("error", "")


def _add_medication(conn, env):
    result = call_action(mod.health_add_medication, conn, ns(
        company_id=env["company_id"],
        name="Lisinopril",
        generic_name="Lisinopril",
        ndc_code=None,
        dea_schedule=None,
        dosage_form=None,
        strength=None,
        manufacturer=None,
        unit_price="9.99",
        quantity_on_hand="100",
        reorder_level="10",
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(result), result
    return result["id"]


def test_update_medication_rewrites_the_stored_row(conn, env):
    med_id = _add_medication(conn, env)
    before = _read_row(conn, "healthclaw_medication", med_id)
    assert before["unit_price"] == "9.99"
    assert before["quantity_on_hand"] == 100
    assert before["notes"] is None

    result = call_action(mod.health_update_medication, conn, ns(
        medication_id=med_id,
        company_id=env["company_id"],
        name=None, generic_name=None, ndc_code=None,
        dea_schedule=None, dosage_form=None, strength=None,
        manufacturer=None,
        unit_price="12.50",
        quantity_on_hand="80",
        reorder_level=None,
        notes="Contract price update",
        limit=50, offset=0,
    ))
    assert is_ok(result), result
    assert set(result["updated_fields"]) == {
        "unit_price", "quantity_on_hand", "notes"}

    after = _read_row(conn, "healthclaw_medication", med_id)
    assert after["unit_price"] == "12.50"
    assert Decimal(after["unit_price"]) == Decimal("12.50")
    assert after["quantity_on_hand"] == 80
    assert after["notes"] == "Contract price update"
    for col in ("id", "company_id", "name", "generic_name", "dea_schedule",
                "dosage_form", "strength", "manufacturer", "reorder_level",
                "is_active", "created_at"):
        assert after[col] == before[col], col

    fetched = call_action(mod.health_get_medication, conn, ns(
        medication_id=med_id, limit=50, offset=0))
    assert is_ok(fetched), fetched
    assert fetched["unit_price"] == "12.50"
    assert fetched["quantity_on_hand"] == 80

    # Master-data write only: this action posts no general-ledger legs.
    assert _table_count(conn, "gl_entry") == 0


def test_update_medication_refusal_writes_nothing(conn, env):
    med_id = _add_medication(conn, env)
    before = _read_row(conn, "healthclaw_medication", med_id)
    count_before = _table_count(conn, "healthclaw_medication")

    result = call_action(mod.health_update_medication, conn, ns(
        medication_id=med_id,
        company_id=env["company_id"],
        name=None, generic_name=None, ndc_code=None,
        dea_schedule="VI",
        dosage_form=None, strength=None,
        manufacturer=None,
        unit_price=None, quantity_on_hand=None, reorder_level=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_error(result)
    assert _refusal_message(result) == (
        "Invalid health-dea-schedule: VI. Must be one of: "
        "I, II, III, IV, V, non-scheduled")
    assert _read_row(conn, "healthclaw_medication", med_id) == before
    assert _table_count(conn, "healthclaw_medication") == count_before
