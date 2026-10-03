"""Depth tests for m423-depth-healthclaw-4: 12 actions proven by database effect.

Every test below reads the stored rows back (via PyPika through
``erpclaw_lib.query``) and compares exact values. Response-shape assertions
alone cannot pass these tests: each behavioural test fails if the action's
write is removed, and each refusal test proves the database is byte-identical
after a rejected call.

None of the 12 actions reaches the general ledger or the payment ledger, so
every writing test pins ``gl_entry`` / ``payment_ledger_entry`` at zero and a
comment records that no ledger assertion can hold for that action.

Actions covered (stored-row vs read-only signal noted per test):
  stored-row : health-cancel-appointment, health-cancel-dispensing,
               health-fill-prescription
  read-only  : health-get-dispensing, health-get-lab-result, health-get-lab-test,
               health-charge-reconciliation-report,
               health-check-enrollment-revalidation,
               health-check-expiring-credentials,
               health-collections-aging-report,
               health-controlled-substance-report, health-denial-rate-report
  (read-only actions are proven by seeding exact rows, running the report/get,
  and asserting the exact derived values plus that nothing was written.)
"""
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from health_helpers import call_action, is_error, is_ok, load_db_query, ns  # noqa: E402

from erpclaw_lib.query import Field, P, Q, Table, fn  # noqa: E402

mod = load_db_query()
ACTIONS = mod.ACTIONS


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SNAPSHOT_TABLES = (
    "healthclaw_appointment",
    "healthclaw_encounter",
    "healthclaw_charge",
    "healthclaw_claim",
    "healthclaw_claim_line",
    "healthclaw_payment_posting",
    "healthclaw_dispensing",
    "healthclaw_dispense_log",
    "healthclaw_prescription",
    "healthclaw_medication",
    "healthclaw_controlled_substance_log",
    "healthclaw_lab_test",
    "healthclaw_lab_result",
    "healthclaw_lab_order",
    "healthclaw_provider_credential",
    "healthclaw_payer",
    "healthclaw_payer_enrollment",
    "healthclaw_patient",
    "audit_log",
    "gl_entry",
    "payment_ledger_entry",
)


def _msg(result):
    return result.get("message", "") + result.get("error", "")


def _snapshot(conn):
    """Full row dump of every table these actions could touch."""
    snap = {}
    for name in SNAPSHOT_TABLES:
        t = Table(name)
        rows = conn.execute(
            Q.from_(t).select(t.star).orderby(t.id).get_sql(), ()
        ).fetchall()
        snap[name] = [dict(r) for r in rows]
    return snap


def _row(conn, table, row_id):
    t = Table(table)
    row = conn.execute(
        Q.from_(t).select(t.star).where(Field("id") == P()).get_sql(),
        (row_id,),
    ).fetchone()
    assert row is not None, f"expected row {row_id} in {table}"
    return dict(row)


def _count(conn, table):
    t = Table(table)
    return conn.execute(Q.from_(t).select(fn.Count("*")).get_sql(), ()).fetchone()[0]


def _no_ledger_rows(conn):
    # None of the 12 actions posts to the GL or payment ledger; pin that.
    assert _count(conn, "gl_entry") == 0
    assert _count(conn, "payment_ledger_entry") == 0


def _add_appointment(conn, env, **over):
    kw = dict(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], appointment_date="2026-03-25",
        start_time="14:00", end_time="14:30", duration_minutes="30",
        appointment_type="new_patient", chief_complaint=None, location=None,
        notes=None, cancellation_reason=None, new_provider_id=None,
        limit=50, offset=0, search=None, status=None,
    )
    kw.update(over)
    return call_action(ACTIONS["health-add-appointment"], conn, ns(**kw))


def _add_payer(conn, env, name="Depth Payer"):
    result = call_action(ACTIONS["health-add-payer"], conn, ns(
        company_id=env["company_id"], name=name, payer_type="commercial",
        edi_payer_id=None, electronic_filing_id=None, address=None, city=None,
        state=None, zip_code=None, phone=None, claims_address=None,
        claims_city=None, claims_state=None, claims_zip=None,
        submission_method=None, timely_filing_days=None, era_enrollment=None,
        notes=None, limit=50, offset=0,
    ))
    assert is_ok(result), result
    return result["id"]


def _add_medication(conn, env, name="Depth Med", dea="non-scheduled", qty=100,
                    price="5.00"):
    result = call_action(ACTIONS["health-add-medication"], conn, ns(
        company_id=env["company_id"], name=name, generic_name=None,
        ndc_code=None, dea_schedule=dea, dosage_form=None, strength=None,
        manufacturer=None, unit_price=price, quantity_on_hand=str(qty),
        reorder_level="10", notes=None,
    ))
    assert is_ok(result), result
    return result["id"]


def _add_prescription(conn, env, med_id, qty=30, dea_number=None):
    result = call_action(ACTIONS["health-adv-add-prescription"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        prescriber_id=env["provider_id"], medication_id=med_id,
        rx_number=None, dosage="10mg", frequency="daily", route=None,
        quantity_prescribed=str(qty), refills_authorized="0",
        dea_number=dea_number, prescribed_date="2026-03-15",
        expiry_date=None, notes=None,
    ))
    assert is_ok(result), result
    return result["id"]


def _add_dispensing(conn, env, rx_id, qty="30"):
    result = call_action(ACTIONS["health-add-dispensing"], conn, ns(
        company_id=env["company_id"], prescription_id=rx_id,
        patient_id=env["patient_id"], dispensed_by_id=env["provider_id"],
        dispensed_date="2026-03-20", quantity=qty, formulary_item_id=None,
        item_id=None, lot_number=None, expiration_date=None, ndc_code=None,
        directions=None, refill_number=None, notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(result), result
    return result["id"]


# ===========================================================================
# 1. health-cancel-appointment (stored-row signal)
# ===========================================================================

def test_cancel_appointment_flips_status_and_stores_reason(conn, env):
    add_res = _add_appointment(conn, env)
    assert is_ok(add_res), add_res
    before = _row(conn, "healthclaw_appointment", add_res["id"])
    assert before["status"] == "scheduled"
    assert before["cancellation_reason"] is None

    result = call_action(ACTIONS["health-cancel-appointment"], conn, ns(
        appointment_id=add_res["id"], cancellation_reason="Patient request",
        limit=50, offset=0,
    ))
    assert is_ok(result), result
    assert result["id"] == add_res["id"]
    assert result["document_status"] == "cancelled"

    after = _row(conn, "healthclaw_appointment", add_res["id"])
    assert after["status"] == "cancelled"
    assert after["cancellation_reason"] == "Patient request"
    for col in ("patient_id", "provider_id", "appointment_date",
                "start_time", "end_time", "company_id"):
        assert after[col] == before[col], col
    # This action never reaches the ledger, so no ledger legs can be asserted.
    _no_ledger_rows(conn)


def test_cancel_appointment_refusals_write_nothing(conn, env):
    add_res = _add_appointment(conn, env)
    assert is_ok(add_res), add_res

    before = _snapshot(conn)
    result = call_action(ACTIONS["health-cancel-appointment"], conn, ns(
        appointment_id=None, cancellation_reason="x", limit=50, offset=0,
    ))
    assert is_error(result)
    assert _msg(result) == "--appointment-id is required"
    assert _snapshot(conn) == before

    assert is_ok(call_action(ACTIONS["health-cancel-appointment"], conn, ns(
        appointment_id=add_res["id"], cancellation_reason="first",
        limit=50, offset=0,
    )))
    cancelled = _snapshot(conn)
    result = call_action(ACTIONS["health-cancel-appointment"], conn, ns(
        appointment_id=add_res["id"], cancellation_reason="second",
        limit=50, offset=0,
    ))
    assert is_error(result)
    assert _msg(result) == "Cannot cancel appointment with status 'cancelled'."
    assert _snapshot(conn) == cancelled
    assert _row(conn, "healthclaw_appointment", add_res["id"])["cancellation_reason"] == "first"


# ===========================================================================
# 2. health-cancel-dispensing (stored-row signal)
# ===========================================================================

def test_cancel_dispensing_voids_the_stored_row(conn, env):
    med_id = _add_medication(conn, env)
    rx_id = _add_prescription(conn, env, med_id)
    disp_id = _add_dispensing(conn, env, rx_id)
    before = _row(conn, "healthclaw_dispensing", disp_id)
    assert before["status"] == "dispensed"
    assert Decimal(str(before["quantity"])) == Decimal("30")

    result = call_action(ACTIONS["health-cancel-dispensing"], conn, ns(
        dispensing_id=disp_id, limit=50, offset=0,
    ))
    assert is_ok(result), result
    assert result["id"] == disp_id
    assert result["document_status"] == "voided"

    after = _row(conn, "healthclaw_dispensing", disp_id)
    assert after["status"] == "voided"
    for col in ("prescription_id", "patient_id", "dispensed_by_id",
                "dispensed_date", "quantity", "company_id"):
        assert after[col] == before[col], col
    # This action never reaches the ledger, so no ledger legs can be asserted.
    _no_ledger_rows(conn)


def test_cancel_dispensing_refusals_write_nothing(conn, env):
    med_id = _add_medication(conn, env)
    rx_id = _add_prescription(conn, env, med_id)
    disp_id = _add_dispensing(conn, env, rx_id)

    before = _snapshot(conn)
    result = call_action(ACTIONS["health-cancel-dispensing"], conn, ns(
        dispensing_id=None, limit=50, offset=0,
    ))
    assert is_error(result)
    assert _msg(result) == "--dispensing-id is required"
    assert _snapshot(conn) == before

    assert is_ok(call_action(ACTIONS["health-cancel-dispensing"], conn, ns(
        dispensing_id=disp_id, limit=50, offset=0,
    )))
    voided = _snapshot(conn)
    result = call_action(ACTIONS["health-cancel-dispensing"], conn, ns(
        dispensing_id=disp_id, limit=50, offset=0,
    ))
    assert is_error(result)
    assert _msg(result) == "Cannot void dispensing with status 'voided'. Must be 'dispensed'."
    assert _snapshot(conn) == voided


# ===========================================================================
# 3. health-fill-prescription (stored-row signal)
# ===========================================================================

def test_fill_prescription_writes_log_decrements_stock_fills_rx(conn, env):
    med_id = _add_medication(conn, env, qty=100)
    rx_id = _add_prescription(conn, env, med_id, qty=30)
    assert _row(conn, "healthclaw_prescription", rx_id)["rx_status"] == "active"
    assert _count(conn, "healthclaw_dispense_log") == 0
    assert _count(conn, "healthclaw_controlled_substance_log") == 0

    result = call_action(ACTIONS["health-fill-prescription"], conn, ns(
        prescription_id=rx_id, dispensed_by="Dr. Test Provider",
        quantity_dispensed="30", lot_number=None, expiration_date=None,
        witness=None, notes=None,
    ))
    assert is_ok(result), result
    assert result["quantity_dispensed"] == 30
    assert result["rx_status"] == "filled"

    rx = _row(conn, "healthclaw_prescription", rx_id)
    assert rx["rx_status"] == "filled"
    logs = conn.execute(
        Q.from_(Table("healthclaw_dispense_log")).select(
            Table("healthclaw_dispense_log").star).get_sql(), ()
    ).fetchall()
    assert len(logs) == 1
    log = dict(logs[0])
    assert log["id"] == result["dispense_log_id"]
    assert log["prescription_id"] == rx_id
    assert log["medication_id"] == med_id
    assert int(log["quantity_dispensed"]) == 30
    assert log["dispensed_by"] == "Dr. Test Provider"
    med = _row(conn, "healthclaw_medication", med_id)
    assert int(med["quantity_on_hand"]) == 70
    assert Decimal(str(med["unit_price"])) == Decimal("5.00")
    # Non-scheduled medication: no controlled-substance log may appear.
    assert _count(conn, "healthclaw_controlled_substance_log") == 0
    # This action never reaches the ledger, so no ledger legs can be asserted.
    _no_ledger_rows(conn)


def test_fill_prescription_refusals_write_nothing(conn, env):
    med_id = _add_medication(conn, env, qty=100)
    rx_id = _add_prescription(conn, env, med_id, qty=30)

    before = _snapshot(conn)
    result = call_action(ACTIONS["health-fill-prescription"], conn, ns(
        prescription_id=rx_id, dispensed_by=None, quantity_dispensed="30",
        lot_number=None, expiration_date=None, witness=None, notes=None,
    ))
    assert is_error(result)
    assert _msg(result) == "--dispensed-by is required"
    assert _snapshot(conn) == before

    assert is_ok(call_action(ACTIONS["health-fill-prescription"], conn, ns(
        prescription_id=rx_id, dispensed_by="Dr. Test Provider",
        quantity_dispensed="30", lot_number=None, expiration_date=None,
        witness=None, notes=None,
    )))
    filled = _snapshot(conn)
    result = call_action(ACTIONS["health-fill-prescription"], conn, ns(
        prescription_id=rx_id, dispensed_by="Dr. Test Provider",
        quantity_dispensed="30", lot_number=None, expiration_date=None,
        witness=None, notes=None,
    ))
    assert is_error(result)
    assert _msg(result) == "Cannot fill prescription with status: filled"
    assert _snapshot(conn) == filled
    assert _row(conn, "healthclaw_medication", med_id)["quantity_on_hand"] == 70


# ===========================================================================
# 4. health-get-dispensing (read-only signal: exact stored row, zero writes)
# ===========================================================================

def test_get_dispensing_returns_the_exact_stored_row(conn, env):
    med_id = _add_medication(conn, env)
    rx_id = _add_prescription(conn, env, med_id)
    disp_id = _add_dispensing(conn, env, rx_id)
    stored = _row(conn, "healthclaw_dispensing", disp_id)

    before = _snapshot(conn)
    result = call_action(ACTIONS["health-get-dispensing"], conn, ns(
        dispensing_id=disp_id, limit=50, offset=0,
    ))
    assert is_ok(result), result
    for col in ("id", "prescription_id", "patient_id", "dispensed_by_id",
                "dispensed_date", "quantity", "company_id"):
        assert str(result[col]) == str(stored[col]), col
    # NOTE: the response envelope renames the row's `status` to
    # `document_status`; the stored value itself is asserted exactly here.
    assert result["document_status"] == stored["status"] == "dispensed"
    assert Decimal(str(result["quantity"])) == Decimal("30.00")
    assert result["patient_name"] == "Jane Smith"
    assert _snapshot(conn) == before
    # Read-only action: no ledger assertion can hold; pin ledgers stay empty.
    _no_ledger_rows(conn)


def test_get_dispensing_refusals_write_nothing(conn, env):
    before = _snapshot(conn)
    result = call_action(ACTIONS["health-get-dispensing"], conn, ns(
        dispensing_id=None, limit=50, offset=0,
    ))
    assert is_error(result)
    assert _msg(result) == "--dispensing-id is required"
    assert _snapshot(conn) == before

    result = call_action(ACTIONS["health-get-dispensing"], conn, ns(
        dispensing_id="no-such-dispensing", limit=50, offset=0,
    ))
    assert is_error(result)
    assert _msg(result) == "Dispensing no-such-dispensing not found"
    assert _snapshot(conn) == before


# ===========================================================================
# 5. health-get-lab-test (read-only signal: exact stored row, zero writes)
# ===========================================================================

def _add_core_lab_test(conn, env, code="CBC", name="Complete Blood Count"):
    result = call_action(ACTIONS["health-add-lab-test"], conn, ns(
        lab_order_id=env["lab_order_id"], test_code=code, test_name=name,
        cpt_code=None, component_name=None, notes=None, status=None,
        limit=50, offset=0,
    ))
    assert is_ok(result), result
    return result["id"]


def test_get_lab_test_returns_the_exact_stored_row(conn, env):
    test_id = _add_core_lab_test(conn, env)
    stored = _row(conn, "healthclaw_lab_test", test_id)

    before = _snapshot(conn)
    result = call_action(ACTIONS["health-get-lab-test"], conn, ns(
        lab_test_id=test_id, limit=50, offset=0,
    ))
    assert is_ok(result), result
    for col in ("id", "lab_order_id", "test_code", "test_name"):
        assert str(result[col]) == str(stored[col]), col
    # NOTE: the response envelope renames the row's `status` to
    # `document_status`; the stored value itself is asserted exactly here.
    assert result["document_status"] == stored["status"] == "pending"
    assert result["test_code"] == "CBC"
    assert result["test_name"] == "Complete Blood Count"
    assert _snapshot(conn) == before
    # Read-only action: no ledger assertion can hold; pin ledgers stay empty.
    _no_ledger_rows(conn)


def test_get_lab_test_refusals_write_nothing(conn, env):
    before = _snapshot(conn)
    result = call_action(ACTIONS["health-get-lab-test"], conn, ns(
        lab_test_id=None, limit=50, offset=0,
    ))
    assert is_error(result)
    assert _msg(result) == "--lab-test-id is required"
    assert _snapshot(conn) == before

    result = call_action(ACTIONS["health-get-lab-test"], conn, ns(
        lab_test_id="no-such-test", limit=50, offset=0,
    ))
    assert is_error(result)
    assert _msg(result) == "Lab test no-such-test not found"
    assert _snapshot(conn) == before


# ===========================================================================
# 6. health-get-lab-result (read-only signal: exact stored row, zero writes)
# ===========================================================================

def _add_core_lab_result(conn, env, test_id):
    result = call_action(ACTIONS["health-add-lab-result"], conn, ns(
        lab_test_id=test_id, component_name="Hemoglobin",
        result_value="13.5", result_date="2026-03-20", flag="normal",
        unit="g/dL", reference_low=None, reference_high=None,
        performed_by_id=None, verified_by_id=None, notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(result), result
    return result["id"]


def test_get_lab_result_returns_the_exact_stored_row(conn, env):
    test_id = _add_core_lab_test(conn, env)
    result_id = _add_core_lab_result(conn, env, test_id)
    stored = _row(conn, "healthclaw_lab_result", result_id)

    before = _snapshot(conn)
    result = call_action(ACTIONS["health-get-lab-result"], conn, ns(
        lab_result_id=result_id, limit=50, offset=0,
    ))
    assert is_ok(result), result
    for col in ("id", "lab_test_id", "component_name", "value", "unit",
                "flag", "result_date"):
        assert str(result[col]) == str(stored[col]), col
    assert result["component_name"] == "Hemoglobin"
    assert result["value"] == "13.5"
    assert result["flag"] == "normal"
    assert _snapshot(conn) == before
    # Read-only action: no ledger assertion can hold; pin ledgers stay empty.
    _no_ledger_rows(conn)


def test_get_lab_result_refusals_write_nothing(conn, env):
    before = _snapshot(conn)
    result = call_action(ACTIONS["health-get-lab-result"], conn, ns(
        lab_result_id=None, limit=50, offset=0,
    ))
    assert is_error(result)
    assert _msg(result) == "--lab-result-id is required"
    assert _snapshot(conn) == before

    result = call_action(ACTIONS["health-get-lab-result"], conn, ns(
        lab_result_id="no-such-result", limit=50, offset=0,
    ))
    assert is_error(result)
    assert _msg(result) == "Lab result no-such-result not found"
    assert _snapshot(conn) == before


# ===========================================================================
# 7. health-charge-reconciliation-report (read-only signal)
# ===========================================================================

def _complete_encounter(conn, env, enc_id):
    result = call_action(ACTIONS["health-update-encounter"], conn, ns(
        encounter_id=enc_id, encounter_status="completed",
        encounter_type=None, chief_complaint=None, department=None, room=None,
        admission_date=None, discharge_date=None, discharge_disposition=None,
        notes=None, company_id=env["company_id"], limit=50, offset=0,
    ))
    assert is_ok(result), result


def _add_core_charge(conn, env, enc_id, amount, patient_id=None):
    result = call_action(ACTIONS["health-add-charge"], conn, ns(
        company_id=env["company_id"], encounter_id=enc_id,
        patient_id=patient_id or env["patient_id"],
        provider_id=env["provider_id"], cpt_code="99213",
        charge_amount=amount, service_date="2026-03-15", procedure_id=None,
        fee_schedule_id=None, units="1", modifier=None, modifiers=None,
        diagnosis_ids=None, place_of_service="11",
        rendering_provider_id=None, charge_status=None, notes=None,
        allowed_amount=amount, limit=50, offset=0,
    ))
    assert is_ok(result), result
    return result["id"]


def test_charge_reconciliation_flags_only_the_chargeless_encounter(conn, env):
    from health_helpers import seed_encounter as _seed_enc  # noqa: E402
    second_enc = _seed_enc(conn, env["company_id"], env["patient_id"],
                           env["provider_id"])
    _complete_encounter(conn, env, env["encounter_id"])
    _complete_encounter(conn, env, second_enc)
    _add_core_charge(conn, env, second_enc, "150.00")

    before = _snapshot(conn)
    result = call_action(
        ACTIONS["health-charge-reconciliation-report"], conn, ns(
            company_id=env["company_id"], date_from=None, date_to=None,
            limit=50, offset=0,
        ))
    assert is_ok(result), result
    assert result["total_completed_encounters"] == 2
    assert result["encounters_without_charges"] == 1
    assert [m["encounter_id"] for m in result["missing_charges"]] == [env["encounter_id"]]
    assert result["missing_charges"][0]["charge_count"] == 0
    assert _snapshot(conn) == before

    # Covering the encounter clears the flag: the report tracks stored rows.
    _add_core_charge(conn, env, env["encounter_id"], "75.00")
    result = call_action(
        ACTIONS["health-charge-reconciliation-report"], conn, ns(
            company_id=env["company_id"], date_from=None, date_to=None,
            limit=50, offset=0,
        ))
    assert is_ok(result), result
    assert result["encounters_without_charges"] == 0
    assert result["missing_charges"] == []
    # Read-only action: no ledger assertion can hold; pin ledgers stay empty.
    _no_ledger_rows(conn)


def test_charge_reconciliation_refusals_write_nothing(conn, env):
    before = _snapshot(conn)
    result = call_action(
        ACTIONS["health-charge-reconciliation-report"], conn, ns(
            company_id=None, date_from=None, date_to=None,
            limit=50, offset=0,
        ))
    assert is_error(result)
    assert _msg(result) == "--company-id is required"
    assert _snapshot(conn) == before

    result = call_action(
        ACTIONS["health-charge-reconciliation-report"], conn, ns(
            company_id="no-such-company", date_from=None, date_to=None,
            limit=50, offset=0,
        ))
    assert is_error(result)
    assert _msg(result) == "Company no-such-company not found"
    assert _snapshot(conn) == before


# ===========================================================================
# 8. health-check-enrollment-revalidation (read-only signal)
# ===========================================================================

def _add_enrollment(conn, env, payer_id, status, reval_date):
    result = call_action(ACTIONS["health-add-payer-enrollment"], conn, ns(
        company_id=env["company_id"], provider_id=env["provider_id"],
        payer_id=payer_id, enrollment_status=status, effective_date=None,
        termination_date=None, revalidation_date=reval_date,
        provider_number="PN-1", group_npi=None, notes=None,
    ))
    assert is_ok(result), result
    return result["id"]


def test_enrollment_revalidation_splits_due_and_overdue(conn, env):
    payer_id = _add_payer(conn, env)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert today > "2020-01-01"
    overdue_id = _add_enrollment(conn, env, payer_id, "active", "2020-01-01")
    due_id = _add_enrollment(conn, env, payer_id, "active",
                             _plus_days(30))
    far_id = _add_enrollment(conn, env, payer_id, "active", "2032-01-01")
    pending_id = _add_enrollment(conn, env, payer_id, "pending",
                                 _plus_days(10))

    before = _snapshot(conn)
    result = call_action(
        ACTIONS["health-check-enrollment-revalidation"], conn, ns(
            company_id=env["company_id"], days="365", limit=50, offset=0,
        ))
    assert is_ok(result), result
    assert result["overdue_count"] == 1
    assert result["due_count"] == 1
    assert [e["id"] for e in result["overdue"]] == [overdue_id]
    assert [e["id"] for e in result["due"]] == [due_id]
    assert result["overdue"][0]["revalidation_date"] == "2020-01-01"
    assert result["overdue"][0]["provider_id"] == env["provider_id"]
    assert result["overdue"][0]["payer_id"] == payer_id
    seen = {e["id"] for e in result["due"]} | {e["id"] for e in result["overdue"]}
    assert far_id not in seen and pending_id not in seen
    assert _snapshot(conn) == before
    # Read-only action: no ledger assertion can hold; pin ledgers stay empty.
    _no_ledger_rows(conn)


def _plus_days(n):
    from datetime import timedelta as _td  # noqa: E402
    return (datetime.now(timezone.utc) + _td(days=n)).strftime("%Y-%m-%d")


def test_enrollment_revalidation_refusals_write_nothing(conn, env):
    before = _snapshot(conn)
    result = call_action(
        ACTIONS["health-check-enrollment-revalidation"], conn, ns(
            company_id=None, days="90", limit=50, offset=0,
        ))
    assert is_error(result)
    assert _msg(result) == "--company-id is required"
    assert _snapshot(conn) == before

    result = call_action(
        ACTIONS["health-check-enrollment-revalidation"], conn, ns(
            company_id="no-such-company", days="90", limit=50, offset=0,
        ))
    assert is_error(result)
    assert _msg(result) == "Company no-such-company not found"
    assert _snapshot(conn) == before


# ===========================================================================
# 9. health-check-expiring-credentials (read-only signal)
# ===========================================================================

def _add_credential(conn, env, cred_type, number, exp_date):
    result = call_action(ACTIONS["health-add-provider-credential"], conn, ns(
        company_id=env["company_id"], provider_id=env["provider_id"],
        credential_type=cred_type, credential_number=number,
        issuing_authority="State Board", issue_date="2020-01-01",
        expiration_date=exp_date, verification_date=None, verified_by=None,
        notes=None, status=None, days=None, limit=50, offset=0,
    ))
    assert is_ok(result), result
    return result["id"]


def test_expiring_credentials_splits_expiring_and_expired(conn, env):
    expired_id = _add_credential(conn, env, "medical_license", "LIC-OLD",
                                 "2020-01-01")
    soon_id = _add_credential(conn, env, "npi", "NPI-SOON", _plus_days(30))
    far_id = _add_credential(conn, env, "dea", "DEA-FAR", "2032-01-01")

    before = _snapshot(conn)
    result = call_action(
        ACTIONS["health-check-expiring-credentials"], conn, ns(
            company_id=env["company_id"], days="365", provider_id=None,
            credential_type=None, status=None, limit=50, offset=0,
        ))
    assert is_ok(result), result
    assert result["expired_count"] == 1
    assert result["expiring_count"] == 1
    assert [e["id"] for e in result["already_expired"]] == [expired_id]
    assert [e["id"] for e in result["expiring"]] == [soon_id]
    assert result["expiring"][0]["credential_type"] == "npi"
    assert result["expiring"][0]["credential_number"] == "NPI-SOON"
    assert result["expiring"][0]["provider_id"] == env["provider_id"]
    seen = {e["id"] for e in result["expiring"]} | \
        {e["id"] for e in result["already_expired"]}
    assert far_id not in seen
    assert _snapshot(conn) == before
    # Read-only action: no ledger assertion can hold; pin ledgers stay empty.
    _no_ledger_rows(conn)


def test_expiring_credentials_refusals_write_nothing(conn, env):
    before = _snapshot(conn)
    result = call_action(
        ACTIONS["health-check-expiring-credentials"], conn, ns(
            company_id=None, days="90", provider_id=None,
            credential_type=None, status=None, limit=50, offset=0,
        ))
    assert is_error(result)
    assert _msg(result) == "--company-id is required"
    assert _snapshot(conn) == before


# ===========================================================================
# 10. health-collections-aging-report (read-only signal, money exact)
# ===========================================================================

def _add_posting(conn, env, amount, patient_id=None):
    result = call_action(ACTIONS["health-add-payment-posting"], conn, ns(
        company_id=env["company_id"],
        patient_id=patient_id or env["patient_id"],
        posting_type="patient_payment", posting_date="2026-04-01",
        amount=amount, claim_id=None, payment_entry_id=None,
        payment_method="cash", check_number=None, payer_name=None,
        eob_date=None, notes=None,
    ))
    assert is_ok(result), result
    return result["id"]


def test_collections_aging_reports_exact_balances(conn, env):
    from health_helpers import seed_patient as _seed_pat  # noqa: E402
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _add_core_charge(conn, env, env["encounter_id"], "500.00")
    conn.execute(
        "UPDATE healthclaw_charge SET service_date = ? WHERE encounter_id = ?",
        (today, env["encounter_id"]),
    )
    conn.commit()
    _add_posting(conn, env, "200.00")

    other_patient = _seed_pat(conn, env["company_id"], "Paid", "Up")
    _add_core_charge(conn, env, env["encounter_id"], "100.00",
                     patient_id=other_patient)
    _add_posting(conn, env, "100.00", patient_id=other_patient)

    before = _snapshot(conn)
    result = call_action(
        ACTIONS["health-collections-aging-report"], conn, ns(
            company_id=env["company_id"], limit=50, offset=0,
        ))
    assert is_ok(result), result
    assert Decimal(str(result["total_ar"])) == Decimal("300.00")
    assert result["total_ar"] == "300.00"
    assert result["patient_count"] == 1
    row = result["aging"][0]
    assert row["patient_id"] == env["patient_id"]
    assert row["patient_name"] == "Jane Smith"
    assert Decimal(str(row["total_charges"])) == Decimal("500.00")
    assert Decimal(str(row["total_payments"])) == Decimal("200.00")
    assert Decimal(str(row["balance_due"])) == Decimal("300.00")
    assert (row["total_charges"], row["total_payments"],
            row["balance_due"]) == ("500.00", "200.00", "300.00")
    assert row["current"] == "500.00"
    assert (row["31_60_days"], row["61_90_days"], row["91_120_days"],
            row["120_plus_days"]) == ("0.00", "0.00", "0.00", "0.00")
    assert _snapshot(conn) == before
    # Read-only action: no ledger assertion can hold; pin ledgers stay empty.
    _no_ledger_rows(conn)


def test_collections_aging_refusals_write_nothing(conn, env):
    _add_core_charge(conn, env, env["encounter_id"], "500.00")
    before = _snapshot(conn)
    result = call_action(
        ACTIONS["health-collections-aging-report"], conn, ns(
            company_id="no-such-company", limit=50, offset=0,
        ))
    assert is_error(result)
    assert _msg(result) == "Company no-such-company not found"
    assert _snapshot(conn) == before


# ===========================================================================
# 11. health-controlled-substance-report (read-only signal)
# ===========================================================================

def test_controlled_substance_report_lists_the_fill_log(conn, env):
    med_id = _add_medication(conn, env, name="Codeine-APAP", dea="III",
                             qty=100, price="5.00")
    rx_id = _add_prescription(conn, env, med_id, qty=30,
                              dea_number="AB1234567")
    fill = call_action(ACTIONS["health-fill-prescription"], conn, ns(
        prescription_id=rx_id, dispensed_by="Dr. Test Provider",
        quantity_dispensed="30", lot_number=None, expiration_date=None,
        witness=None, notes=None,
    ))
    assert is_ok(fill), fill
    assert _count(conn, "healthclaw_controlled_substance_log") == 1

    before = _snapshot(conn)
    result = call_action(
        ACTIONS["health-controlled-substance-report"], conn, ns(
            company_id=env["company_id"], date_from=None, date_to=None,
            limit=50, offset=0,
        ))
    assert is_ok(result), result
    assert result["total_entries"] == 1
    entry = result["entries"][0]
    assert entry["medication_id"] == med_id
    assert entry["prescription_id"] == rx_id
    assert entry["action_type"] == "dispensed"
    assert int(entry["quantity"]) == 30
    assert entry["medication_name"] == "Codeine-APAP"
    assert entry["dea_schedule"] == "III"
    assert result["summary_by_action"] == {
        "dispensed": {"count": 1, "total_quantity": 30}}
    assert _snapshot(conn) == before
    # Read-only action: no ledger assertion can hold; pin ledgers stay empty.
    _no_ledger_rows(conn)


def test_controlled_substance_report_empty_filter_writes_nothing(conn, env):
    # FINDING (documented, not fixed): this action validates no input, so it
    # exposes no refusal path. An unknown-company filter returns zeros rather
    # than an error; the test pins that truthful empty result and zero writes.
    med_id = _add_medication(conn, env, name="Codeine-APAP", dea="III",
                             qty=100)
    rx_id = _add_prescription(conn, env, med_id, qty=30,
                              dea_number="AB1234567")
    assert is_ok(call_action(ACTIONS["health-fill-prescription"], conn, ns(
        prescription_id=rx_id, dispensed_by="Dr. Test Provider",
        quantity_dispensed="30", lot_number=None, expiration_date=None,
        witness=None, notes=None,
    )))

    before = _snapshot(conn)
    result = call_action(
        ACTIONS["health-controlled-substance-report"], conn, ns(
            company_id="no-such-company", date_from=None, date_to=None,
            limit=50, offset=0,
        ))
    assert is_ok(result), result
    assert result["total_entries"] == 0
    assert result["entries"] == []
    assert _snapshot(conn) == before


# ===========================================================================
# 12. health-denial-rate-report (read-only signal, money exact)
# ===========================================================================

def _add_adv_charge(conn, env, unit_fee, quantity):
    result = call_action(ACTIONS["health-adv-add-charge"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], procedure_code_id=None,
        service_date="2026-03-15", cpt_code="99213", icd10_codes=None,
        description=None, quantity=quantity, unit_fee=unit_fee, notes=None,
    ))
    assert is_ok(result), result
    return result["id"]


def _add_adv_claim(conn, env, charge_ids, payer="Acme Health"):
    import json as _json  # noqa: E402
    result = call_action(ACTIONS["health-adv-add-claim"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        payer_name=payer, payer_id_number=None, policy_number=None,
        group_number=None, claim_number=None, claim_date="2026-03-20",
        charge_ids=_json.dumps(charge_ids), notes=None,
    ))
    assert is_ok(result), result
    return result["id"]


def test_denial_rate_report_counts_denied_amount_exactly(conn, env):
    import json as _json  # noqa: E402
    c1 = _add_adv_charge(conn, env, "125.00", "2")
    c2 = _add_adv_charge(conn, env, "40.00", "1")
    c3 = _add_adv_charge(conn, env, "10.00", "1")
    denied_id = _add_adv_claim(conn, env, [c1, c2])
    draft_id = _add_adv_claim(conn, env, [c3])
    assert conn.execute(
        "SELECT total_charged FROM healthclaw_claim WHERE id = ?",
        (denied_id,)).fetchone()[0] == "290.00"

    denial = call_action(ACTIONS["health-record-denial"], conn, ns(
        claim_id=denied_id, denial_category="CO", denial_code="CO-97",
        denial_reason="Bundled", denial_date="2026-04-10",
    ))
    assert is_ok(denial), denial

    before = _snapshot(conn)
    result = call_action(ACTIONS["health-denial-rate-report"], conn, ns(
        company_id=env["company_id"], limit=50, offset=0,
    ))
    assert is_ok(result), result
    assert result["total_claims"] == 2
    assert result["denied_count"] == 1
    assert Decimal(str(result["denied_amount"])) == Decimal("290.00")
    assert result["denied_amount"] == "290.00"
    assert result["denial_rate_pct"] == 50.0
    assert {"reason": "Bundled", "count": 1} in result["denial_reasons"]
    assert {"payer_name": "Acme Health", "count": 1} in result["denied_by_payer"]
    assert _json.loads(conn.execute(
        "SELECT charge_ids FROM healthclaw_claim WHERE id = ?",
        (draft_id,)).fetchone()[0]) == [c3]
    assert _snapshot(conn) == before
    # Read-only action: no ledger assertion can hold; pin ledgers stay empty.
    _no_ledger_rows(conn)


def test_denial_rate_report_empty_filter_writes_nothing(conn, env):
    # FINDING (documented, not fixed): this action validates no input, so it
    # exposes no refusal path. An unknown-company filter returns zeros rather
    # than an error; the test pins that truthful empty result and zero writes.
    c1 = _add_adv_charge(conn, env, "125.00", "2")
    denied_id = _add_adv_claim(conn, env, [c1])
    assert is_ok(call_action(ACTIONS["health-record-denial"], conn, ns(
        claim_id=denied_id, denial_category="CO", denial_code="CO-97",
        denial_reason="Bundled", denial_date="2026-04-10",
    )))

    before = _snapshot(conn)
    result = call_action(ACTIONS["health-denial-rate-report"], conn, ns(
        company_id="no-such-company", limit=50, offset=0,
    ))
    assert is_ok(result), result
    assert result["total_claims"] == 0
    assert result["denied_count"] == 0
    assert Decimal(str(result["denied_amount"])) == Decimal("0.00")
    assert _snapshot(conn) == before
