"""M421 depth: behavioural evidence for 12 shape-or-routing-only actions.

Each action below already had a test that checked the response envelope
(keys / reachability) without observing the database. Every test here
reads the stored rows back from the database and compares exact values,
pins what must NOT have changed, and pins that the action does not reach
the ledger. Money is compared as exact Decimal strings, never approximate.

Actions covered (literal router names):
  health-add-procedure-code, health-add-prior-auth, health-add-referral,
  health-add-payment-posting, health-adv-add-charge, health-adv-add-claim,
  health-adv-add-lab-order, health-adv-add-lab-result, health-adv-add-lab-test,
  health-adv-add-payment-posting, health-adv-add-prescription,
  health-adv-get-charge

No ledger leg: none of these 12 handlers posts to the general ledger or the
payment ledger; each happy-path test pins both counts at zero so a later
ledger-writing change cannot slip past this file.
"""
import json
import os
import sys
from decimal import Decimal

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from health_helpers import call_action, is_error, is_ok, load_db_query, ns  # noqa: E402

ACTIONS = load_db_query().ACTIONS


def _msg(r):
    return r.get("message", "") + r.get("error", "")


def _dump(conn, table):
    return [dict(x) for x in conn.execute(
        "SELECT * FROM %s ORDER BY id" % table).fetchall()]


def _snap(conn, tables):
    return {t: _dump(conn, t) for t in tables}


def _count(conn, table):
    return conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]


def _no_ledger(conn):
    # No ledger leg: these actions write only their own domain tables.
    assert _count(conn, "gl_entry") == 0
    assert _count(conn, "payment_ledger_entry") == 0


def _insurance(conn, env, member="MEM-M421"):
    r = call_action(ACTIONS["health-add-patient-insurance"], conn, ns(
        patient_id=env["patient_id"], company_id=env["company_id"],
        insurance_type="primary", payer_name="Acme Health",
        payer_id=None, plan_name=None, plan_type=None, group_number=None,
        member_id=member, subscriber_name=None, subscriber_dob=None,
        subscriber_relationship=None, copay_amount=None, deductible=None,
        deductible_met=None, out_of_pocket_max=None,
        effective_date="2026-01-01", termination_date=None,
        preauth_required=None, status=None))
    assert is_ok(r), r
    return r["id"]


def _core_claim(conn, env, insurance_id, total_charge="250.00"):
    r = call_action(ACTIONS["health-add-claim"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        encounter_id=env["encounter_id"], insurance_id=insurance_id,
        claim_date="2026-03-20", total_charge=total_charge,
        total_allowed=None, total_paid=None, patient_responsibility=None,
        adjustment_amount=None, billing_provider_id=None,
        rendering_provider_id=None, place_of_service=None, claim_type=None,
        filing_indicator=None, prior_auth_id=None, sales_invoice_id=None,
        notes=None))
    assert is_ok(r), r
    return r["id"]


def _adv_charge(conn, env, unit_fee="125.00", quantity="2", cpt="99213"):
    r = call_action(ACTIONS["health-adv-add-charge"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], procedure_code_id=None,
        service_date="2026-03-15", cpt_code=cpt, icd10_codes='["J06.9"]',
        description="Office visit", quantity=quantity, unit_fee=unit_fee,
        notes=None))
    assert is_ok(r), r
    return r["id"]


def _adv_lab_test(conn, env, name="CBC Panel", code="CBC"):
    r = call_action(ACTIONS["health-adv-add-lab-test"], conn, ns(
        company_id=env["company_id"], test_name=name, test_code=code,
        loinc_code="58410-2", category="hematology", specimen_type="blood",
        reference_range="4.5-11.0", unit="K/uL", turnaround_hours="24",
        base_price="89.50", notes=None))
    assert is_ok(r), r
    return r["id"]


def _adv_lab_order(conn, env, lab_test_id, notes="Fasting lipid panel"):
    r = call_action(ACTIONS["health-adv-add-lab-order"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        ordering_provider=env["provider_id"], lab_test_id=lab_test_id,
        order_date="2026-03-15", priority="stat", clinical_notes=notes,
        fasting_required=None, notes=None))
    assert is_ok(r), r
    return r["id"]


def _medication(conn, env, name="Amoxicillin 500mg Capsule"):
    r = call_action(ACTIONS["health-add-medication"], conn, ns(
        company_id=env["company_id"], name=name, dea_schedule="non-scheduled",
        unit_price="0.85", quantity_on_hand="100", reorder_level="10",
        generic_name="amoxicillin", ndc_code=None, dosage_form="capsule",
        strength="500mg", manufacturer=None, notes=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


# ---------------------------------------------------------------------------
# health-add-procedure-code
# ---------------------------------------------------------------------------

def test_m421_procedure_code_writes_exact_row(conn, env):
    before = _snap(conn, ["healthclaw_procedure_code"])
    assert before["healthclaw_procedure_code"] == []
    ctrl = call_action(ACTIONS["health-add-procedure-code"], conn, ns(
        company_id=env["company_id"], code="99212", description="Control visit",
        code_type="CPT", category="E/M", default_fee="10.00", notes=None))
    assert is_ok(ctrl), ctrl
    ctrl_row = dict(conn.execute(
        "SELECT company_id, code, code_type, description, category, "
        "default_fee, is_active FROM healthclaw_procedure_code WHERE id = ?",
        (ctrl["id"],)).fetchone())

    r = call_action(ACTIONS["health-add-procedure-code"], conn, ns(
        company_id=env["company_id"], code="99213",
        description="Office outpatient visit 15 min", code_type="CPT",
        category="E/M", default_fee="149.99", notes=None))
    assert is_ok(r), r
    assert r["code"] == "99213"
    assert r["code_type"] == "CPT"
    assert r["default_fee"] == "149.99"
    assert Decimal(r["default_fee"]) == Decimal("149.99")
    row = conn.execute(
        "SELECT company_id, code, code_type, description, category, "
        "default_fee, is_active FROM healthclaw_procedure_code WHERE id = ?",
        (r["id"],)).fetchone()
    assert dict(row) == {
        "company_id": env["company_id"], "code": "99213", "code_type": "CPT",
        "description": "Office outpatient visit 15 min", "category": "E/M",
        "default_fee": "149.99", "is_active": 1,
    }
    assert Decimal(row["default_fee"]) == Decimal("149.99")
    assert _count(conn, "healthclaw_procedure_code") == 2
    assert dict(conn.execute(
        "SELECT company_id, code, code_type, description, category, "
        "default_fee, is_active FROM healthclaw_procedure_code WHERE id = ?",
        (ctrl["id"],)).fetchone()) == ctrl_row
    _no_ledger(conn)


def test_m421_procedure_code_refusal_writes_nothing(conn, env):
    before = _snap(conn, ["healthclaw_procedure_code", "gl_entry",
                          "payment_ledger_entry"])
    r = call_action(ACTIONS["health-add-procedure-code"], conn, ns(
        company_id=env["company_id"], code=None, description="No code",
        code_type=None, category=None, default_fee=None, notes=None))
    assert is_error(r)
    assert _msg(r) == "--code is required"
    assert _snap(conn, ["healthclaw_procedure_code", "gl_entry",
                        "payment_ledger_entry"]) == before


# ---------------------------------------------------------------------------
# health-adv-add-charge
# ---------------------------------------------------------------------------

def test_m421_adv_charge_writes_exact_row(conn, env):
    control = _adv_charge(conn, env, unit_fee="10.00", quantity="1", cpt="99212")
    control_row = dict(conn.execute(
        "SELECT * FROM healthclaw_charge WHERE id = ?",
        (control,)).fetchone())
    r = call_action(ACTIONS["health-adv-add-charge"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], procedure_code_id=None,
        service_date="2026-03-15", cpt_code="99213",
        icd10_codes='["J06.9"]', description="Office visit",
        quantity="2", unit_fee="125.00", notes=None))
    assert is_ok(r), r
    assert r["total_fee"] == "250.00"
    assert r["charge_status"] == "unbilled"
    assert Decimal(r["total_fee"]) == Decimal("250.00")
    row = conn.execute(
        "SELECT company_id, patient_id, provider_id, service_date, cpt_code, "
        "icd10_codes, description, quantity, unit_fee, total_fee, "
        "charge_status FROM healthclaw_charge WHERE id = ?",
        (r["id"],)).fetchone()
    assert dict(row) == {
        "company_id": env["company_id"], "patient_id": env["patient_id"],
        "provider_id": env["provider_id"], "service_date": "2026-03-15",
        "cpt_code": "99213", "icd10_codes": '["J06.9"]',
        "description": "Office visit", "quantity": 2,
        "unit_fee": "125.00", "total_fee": "250.00",
        "charge_status": "unbilled",
    }
    assert Decimal(row["unit_fee"]) == Decimal("125.00")
    assert Decimal(row["total_fee"]) == Decimal("250.00")
    assert dict(conn.execute("SELECT * FROM healthclaw_charge WHERE id = ?",
                             (control,)).fetchone()) == control_row
    _no_ledger(conn)


def test_m421_adv_charge_refusal_writes_nothing(conn, env):
    control = _adv_charge(conn, env, unit_fee="10.00", quantity="1")
    before = _snap(conn, ["healthclaw_charge", "gl_entry",
                          "payment_ledger_entry"])
    r = call_action(ACTIONS["health-adv-add-charge"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], procedure_code_id=None,
        service_date=None, cpt_code="99213", icd10_codes=None,
        description=None, quantity="1", unit_fee="10.00", notes=None))
    assert is_error(r)
    assert _msg(r) == "--service-date is required"
    assert _snap(conn, ["healthclaw_charge", "gl_entry",
                        "payment_ledger_entry"]) == before
    assert conn.execute("SELECT charge_status FROM healthclaw_charge "
                        "WHERE id = ?", (control,)).fetchone()[0] == "unbilled"


# ---------------------------------------------------------------------------
# health-adv-get-charge
# ---------------------------------------------------------------------------

def test_m421_adv_get_charge_returns_stored_row(conn, env):
    cid = _adv_charge(conn, env, unit_fee="125.00", quantity="2")
    stored = dict(conn.execute("SELECT * FROM healthclaw_charge WHERE id = ?",
                               (cid,)).fetchone())
    before = _snap(conn, ["healthclaw_charge"])
    r = call_action(ACTIONS["health-adv-get-charge"], conn,
                    ns(charge_id=cid))
    assert is_ok(r), r
    assert r["id"] == cid
    assert r["company_id"] == stored["company_id"] == env["company_id"]
    assert r["patient_id"] == stored["patient_id"] == env["patient_id"]
    assert r["provider_id"] == stored["provider_id"] == env["provider_id"]
    assert r["service_date"] == stored["service_date"] == "2026-03-15"
    assert r["cpt_code"] == stored["cpt_code"] == "99213"
    assert r["quantity"] == stored["quantity"] == 2
    assert r["unit_fee"] == stored["unit_fee"] == "125.00"
    assert r["total_fee"] == stored["total_fee"] == "250.00"
    assert r["charge_status"] == stored["charge_status"] == "unbilled"
    assert Decimal(r["total_fee"]) == Decimal("250.00")
    assert r["icd10_codes"] == ["J06.9"]
    assert _snap(conn, ["healthclaw_charge"]) == before
    _no_ledger(conn)


def test_m421_adv_get_charge_refusal_writes_nothing(conn, env):
    cid = _adv_charge(conn, env)
    before = _snap(conn, ["healthclaw_charge", "gl_entry",
                          "payment_ledger_entry"])
    r = call_action(ACTIONS["health-adv-get-charge"], conn, ns(charge_id=None))
    assert is_error(r)
    assert _msg(r) == "--charge-id is required"
    r = call_action(ACTIONS["health-adv-get-charge"], conn,
                    ns(charge_id="no-such-charge"))
    assert is_error(r)
    assert _msg(r) == "Charge no-such-charge not found"
    assert _snap(conn, ["healthclaw_charge", "gl_entry",
                        "payment_ledger_entry"]) == before
    assert conn.execute("SELECT COUNT(*) FROM healthclaw_charge").fetchone()[0] == 1
    assert cid is not None


# ---------------------------------------------------------------------------
# health-adv-add-claim
# ---------------------------------------------------------------------------

def test_m421_adv_claim_writes_exact_row(conn, env):
    c1 = _adv_charge(conn, env, unit_fee="125.00", quantity="2")
    c2 = _adv_charge(conn, env, unit_fee="40.00", quantity="1")
    untouched = _adv_charge(conn, env, unit_fee="10.00", quantity="1")
    r = call_action(ACTIONS["health-adv-add-claim"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        payer_name="Acme Health", payer_id_number="ACME-EDI-01",
        policy_number="POL-5520", group_number="GRP-77",
        claim_number="EXT-9001", claim_date="2026-03-20",
        charge_ids=json.dumps([c1, c2]), notes=None))
    assert is_ok(r), r
    assert r["total_charged"] == "290.00"
    assert r["claim_status"] == "draft"
    assert Decimal(r["total_charged"]) == Decimal("290.00")
    row = conn.execute(
        "SELECT company_id, patient_id, payer_name, payer_id_number, "
        "policy_number, group_number, claim_number, claim_date, "
        "total_charged, total_allowed, total_paid, total_adjustment, "
        "patient_responsibility, claim_status FROM healthclaw_claim "
        "WHERE id = ?", (r["id"],)).fetchone()
    assert dict(row) == {
        "company_id": env["company_id"], "patient_id": env["patient_id"],
        "payer_name": "Acme Health", "payer_id_number": "ACME-EDI-01",
        "policy_number": "POL-5520", "group_number": "GRP-77",
        "claim_number": "EXT-9001", "claim_date": "2026-03-20",
        "total_charged": "290.00", "total_allowed": "0.00",
        "total_paid": "0.00", "total_adjustment": "0.00",
        "patient_responsibility": "0.00", "claim_status": "draft",
    }
    assert Decimal(row["total_charged"]) == Decimal("290.00")
    assert json.loads(conn.execute(
        "SELECT charge_ids FROM healthclaw_claim WHERE id = ?",
        (r["id"],)).fetchone()[0]) == [c1, c2]
    statuses = {x["id"]: (x["charge_status"], x["total_fee"]) for x in conn.execute(
        "SELECT id, charge_status, total_fee FROM healthclaw_charge").fetchall()}
    assert statuses == {c1: ("unbilled", "250.00"), c2: ("unbilled", "40.00"),
                        untouched: ("unbilled", "10.00")}
    _no_ledger(conn)


def test_m421_adv_claim_refusal_writes_nothing(conn, env):
    c1 = _adv_charge(conn, env, unit_fee="125.00", quantity="2")
    before = _snap(conn, ["healthclaw_claim", "healthclaw_charge", "gl_entry",
                          "payment_ledger_entry"])
    r = call_action(ACTIONS["health-adv-add-claim"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        payer_name="Acme Health", payer_id_number=None, policy_number=None,
        group_number=None, claim_number=None, claim_date=None,
        charge_ids=json.dumps([c1]), notes=None))
    assert is_error(r)
    assert _msg(r) == "--claim-date is required"
    r = call_action(ACTIONS["health-adv-add-claim"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        payer_name="Acme Health", payer_id_number=None, policy_number=None,
        group_number=None, claim_number=None, claim_date="2026-03-20",
        charge_ids="not-json", notes=None))
    assert is_error(r)
    assert _msg(r) == "--charge-ids must be valid JSON array"
    assert _snap(conn, ["healthclaw_claim", "healthclaw_charge", "gl_entry",
                        "payment_ledger_entry"]) == before


# ---------------------------------------------------------------------------
# health-adv-add-lab-test
# ---------------------------------------------------------------------------

def test_m421_adv_lab_test_writes_exact_row(conn, env):
    ctrl = _adv_lab_test(conn, env, name="Control Panel", code="CTRL")
    ctrl_row = dict(conn.execute("SELECT * FROM healthclaw_lab_test "
                                 "WHERE id = ?", (ctrl,)).fetchone())
    r = call_action(ACTIONS["health-adv-add-lab-test"], conn, ns(
        company_id=env["company_id"], test_name="Complete Blood Count",
        test_code="CBC", loinc_code="58410-2", category="hematology",
        specimen_type="blood", reference_range="4.5-11.0", unit="K/uL",
        turnaround_hours="24", base_price="89.50", notes=None))
    assert is_ok(r), r
    assert r["test_name"] == "Complete Blood Count"
    assert r["base_price"] == "89.50"
    assert Decimal(r["base_price"]) == Decimal("89.50")
    row = conn.execute(
        "SELECT company_id, test_name, test_code, loinc_code, category, "
        "specimen_type, reference_range, unit, turnaround_hours, base_price, "
        "is_active FROM healthclaw_lab_test WHERE id = ?",
        (r["id"],)).fetchone()
    assert dict(row) == {
        "company_id": env["company_id"], "test_name": "Complete Blood Count",
        "test_code": "CBC", "loinc_code": "58410-2",
        "category": "hematology", "specimen_type": "blood",
        "reference_range": "4.5-11.0", "unit": "K/uL",
        "turnaround_hours": 24, "base_price": "89.50", "is_active": 1,
    }
    assert Decimal(row["base_price"]) == Decimal("89.50")
    assert dict(conn.execute("SELECT * FROM healthclaw_lab_test WHERE id = ?",
                             (ctrl,)).fetchone()) == ctrl_row
    _no_ledger(conn)


def test_m421_adv_lab_test_refusal_writes_nothing(conn, env):
    before = _snap(conn, ["healthclaw_lab_test", "gl_entry",
                          "payment_ledger_entry"])
    r = call_action(ACTIONS["health-adv-add-lab-test"], conn, ns(
        company_id=env["company_id"], test_name=None, test_code="CBC",
        loinc_code=None, category=None, specimen_type=None,
        reference_range=None, unit=None, turnaround_hours=None,
        base_price=None, notes=None))
    assert is_error(r)
    assert _msg(r) == "--test-name is required"
    assert _snap(conn, ["healthclaw_lab_test", "gl_entry",
                        "payment_ledger_entry"]) == before


# ---------------------------------------------------------------------------
# health-adv-add-lab-order
# ---------------------------------------------------------------------------

def test_m421_adv_lab_order_writes_exact_row(conn, env):
    lab_test = _adv_lab_test(conn, env)
    seeded_before = dict(conn.execute(
        "SELECT id, order_status FROM healthclaw_lab_order WHERE id = ?",
        (env["lab_order_id"],)).fetchone())
    count_before = _count(conn, "healthclaw_lab_order")
    r = call_action(ACTIONS["health-adv-add-lab-order"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        ordering_provider=env["provider_id"], lab_test_id=lab_test,
        order_date="2026-03-15", priority="stat",
        clinical_notes="Fasting lipid panel", fasting_required=None,
        notes=None))
    assert is_ok(r), r
    assert r["lab_test_id"] == lab_test
    assert r["priority"] == "stat"
    assert r["order_status"] == "ordered"
    row = conn.execute(
        "SELECT company_id, patient_id, ordering_provider, lab_test_id, "
        "order_date, priority, order_status, clinical_notes, "
        "fasting_required FROM healthclaw_lab_order WHERE id = ?",
        (r["id"],)).fetchone()
    assert dict(row) == {
        "company_id": env["company_id"], "patient_id": env["patient_id"],
        "ordering_provider": env["provider_id"], "lab_test_id": lab_test,
        "order_date": "2026-03-15", "priority": "stat",
        "order_status": "ordered", "clinical_notes": "Fasting lipid panel",
        "fasting_required": 0,
    }
    assert _count(conn, "healthclaw_lab_order") == count_before + 1
    assert dict(conn.execute(
        "SELECT id, order_status FROM healthclaw_lab_order WHERE id = ?",
        (env["lab_order_id"],)).fetchone()) == seeded_before
    _no_ledger(conn)


def test_m421_adv_lab_order_refusal_writes_nothing(conn, env):
    lab_test = _adv_lab_test(conn, env)
    before = _snap(conn, ["healthclaw_lab_order", "gl_entry",
                          "payment_ledger_entry"])
    r = call_action(ACTIONS["health-adv-add-lab-order"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        ordering_provider=env["provider_id"], lab_test_id=lab_test,
        order_date=None, priority=None, clinical_notes=None,
        fasting_required=None, notes=None))
    assert is_error(r)
    assert _msg(r) == "--order-date is required"
    r = call_action(ACTIONS["health-adv-add-lab-order"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        ordering_provider=env["provider_id"], lab_test_id="no-such-test",
        order_date="2026-03-15", priority=None, clinical_notes=None,
        fasting_required=None, notes=None))
    assert is_error(r)
    assert _msg(r) == "Lab test no-such-test not found"
    assert _snap(conn, ["healthclaw_lab_order", "gl_entry",
                        "payment_ledger_entry"]) == before


# ---------------------------------------------------------------------------
# health-adv-add-lab-result
# ---------------------------------------------------------------------------

def test_m421_adv_lab_result_writes_row_and_completes_order(conn, env):
    lab_test = _adv_lab_test(conn, env)
    order = _adv_lab_order(conn, env, lab_test, notes="Target panel")
    untouched = _adv_lab_order(conn, env, lab_test, notes="Control panel")
    order_before = dict(conn.execute(
        "SELECT order_status, completed_at FROM healthclaw_lab_order "
        "WHERE id = ?", (order,)).fetchone())
    assert order_before["order_status"] == "ordered"
    assert order_before["completed_at"] is None
    r = call_action(ACTIONS["health-adv-add-lab-result"], conn, ns(
        company_id=env["company_id"], lab_order_id=order,
        result_date="2026-03-16", result_value="5.4", result_unit="mg/dL",
        reference_range="3.5-5.5", is_abnormal=1, is_critical=0,
        performed_by="Lab Tech Ana", verified_by="Dr. Verify",
        result_notes="Slightly high", notes=None))
    assert is_ok(r), r
    assert r["lab_order_id"] == order
    row = conn.execute(
        "SELECT company_id, lab_order_id, lab_test_id, patient_id, "
        "result_value, result_unit, reference_range, is_abnormal, "
        "is_critical, performed_by, verified_by, result_date, "
        "result_notes FROM healthclaw_lab_result WHERE id = ?",
        (r["id"],)).fetchone()
    assert dict(row) == {
        "company_id": env["company_id"], "lab_order_id": order,
        "lab_test_id": lab_test, "patient_id": env["patient_id"],
        "result_value": "5.4", "result_unit": "mg/dL",
        "reference_range": "3.5-5.5", "is_abnormal": 1, "is_critical": 0,
        "performed_by": "Lab Tech Ana", "verified_by": "Dr. Verify",
        "result_date": "2026-03-16", "result_notes": "Slightly high",
    }
    order_after = dict(conn.execute(
        "SELECT order_status, completed_at FROM healthclaw_lab_order "
        "WHERE id = ?", (order,)).fetchone())
    assert order_after["order_status"] == "completed"
    assert order_after["completed_at"] not in (None, "")
    assert dict(conn.execute(
        "SELECT order_status, completed_at FROM healthclaw_lab_order "
        "WHERE id = ?", (untouched,)).fetchone()) == {
        "order_status": "ordered", "completed_at": None}
    _no_ledger(conn)


def test_m421_adv_lab_result_refusal_writes_nothing(conn, env):
    lab_test = _adv_lab_test(conn, env)
    order = _adv_lab_order(conn, env, lab_test)
    before = _snap(conn, ["healthclaw_lab_result", "healthclaw_lab_order",
                          "gl_entry", "payment_ledger_entry"])
    r = call_action(ACTIONS["health-adv-add-lab-result"], conn, ns(
        company_id=env["company_id"], lab_order_id=order, result_date=None,
        result_value="5.4", result_unit=None, reference_range=None,
        is_abnormal=None, is_critical=None, performed_by=None,
        verified_by=None, result_notes=None, notes=None))
    assert is_error(r)
    assert _msg(r) == "--result-date is required"
    r = call_action(ACTIONS["health-adv-add-lab-result"], conn, ns(
        company_id=env["company_id"], lab_order_id="no-such-order",
        result_date="2026-03-16", result_value=None, result_unit=None,
        reference_range=None, is_abnormal=None, is_critical=None,
        performed_by=None, verified_by=None, result_notes=None, notes=None))
    assert is_error(r)
    assert _msg(r) == "Lab order no-such-order not found"
    assert _snap(conn, ["healthclaw_lab_result", "healthclaw_lab_order",
                        "gl_entry", "payment_ledger_entry"]) == before


# ---------------------------------------------------------------------------
# health-adv-add-prescription
# ---------------------------------------------------------------------------

def test_m421_adv_prescription_writes_exact_row(conn, env):
    med = _medication(conn, env)
    r = call_action(ACTIONS["health-adv-add-prescription"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        prescriber_id=env["provider_id"], medication_id=med,
        rx_number="RX-M421-001", dosage="500mg", frequency="BID",
        route="oral", quantity_prescribed="20", refills_authorized="2",
        dea_number=None, prescribed_date="2026-03-15",
        expiry_date="2026-09-15", notes="Take with food"))
    assert is_ok(r), r
    assert r["medication_id"] == med
    assert r["rx_status"] == "active"
    row = conn.execute(
        "SELECT company_id, patient_id, prescriber_id, medication_id, "
        "rx_number, dosage, frequency, route, quantity_prescribed, "
        "refills_authorized, refills_used, rx_status, prescribed_date, "
        "expiry_date, notes FROM healthclaw_prescription WHERE id = ?",
        (r["id"],)).fetchone()
    assert dict(row) == {
        "company_id": env["company_id"], "patient_id": env["patient_id"],
        "prescriber_id": env["provider_id"], "medication_id": med,
        "rx_number": "RX-M421-001", "dosage": "500mg", "frequency": "BID",
        "route": "oral", "quantity_prescribed": 20, "refills_authorized": 2,
        "refills_used": 0, "rx_status": "active",
        "prescribed_date": "2026-03-15", "expiry_date": "2026-09-15",
        "notes": "Take with food",
    }
    med_row = dict(conn.execute(
        "SELECT quantity_on_hand FROM healthclaw_medication WHERE id = ?",
        (med,)).fetchone())
    assert med_row == {"quantity_on_hand": 100}
    _no_ledger(conn)


def test_m421_adv_prescription_refusal_writes_nothing(conn, env):
    med = _medication(conn, env)
    before = _snap(conn, ["healthclaw_prescription", "healthclaw_medication",
                          "gl_entry", "payment_ledger_entry"])
    r = call_action(ACTIONS["health-adv-add-prescription"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        prescriber_id=env["provider_id"], medication_id=med,
        rx_number=None, dosage=None, frequency="BID", route=None,
        quantity_prescribed="20", refills_authorized="0", dea_number=None,
        prescribed_date="2026-03-15", expiry_date=None, notes=None))
    assert is_error(r)
    assert _msg(r) == "--dosage is required"
    assert _snap(conn, ["healthclaw_prescription", "healthclaw_medication",
                        "gl_entry", "payment_ledger_entry"]) == before


# ---------------------------------------------------------------------------
# health-add-referral
# ---------------------------------------------------------------------------

def _referral(conn, env, referred_to="Dr. Control", reason="Control reason"):
    r = call_action(ACTIONS["health-add-referral"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        referring_provider_id=env["provider_id"],
        referred_to_provider=referred_to,
        referred_to_specialty="Dermatology", referred_to_facility=None,
        referred_to_phone=None, referred_to_fax=None,
        referral_date="2026-03-15", expiration_date=None, reason=reason,
        encounter_id=None, diagnosis_id=None, priority="routine",
        insurance_id=None, prior_auth_required=None, prior_auth_id=None,
        referral_status=None, status=None, notes=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def test_m421_referral_writes_exact_row(conn, env):
    control = _referral(conn, env)
    control_row = dict(conn.execute("SELECT * FROM healthclaw_referral "
                                    "WHERE id = ?", (control,)).fetchone())
    r = call_action(ACTIONS["health-add-referral"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        referring_provider_id=env["provider_id"],
        referred_to_provider="Dr. Cardio Specialist",
        referred_to_specialty="Cardiology", referred_to_facility=None,
        referred_to_phone=None, referred_to_fax=None,
        referral_date="2026-03-15", expiration_date=None,
        reason="Chest pain evaluation", encounter_id=None, diagnosis_id=None,
        priority="routine", insurance_id=None, prior_auth_required=None,
        prior_auth_id=None, referral_status=None, status=None, notes=None,
        limit=50, offset=0))
    assert is_ok(r), r
    assert r["referred_to_provider"] == "Dr. Cardio Specialist"
    # NOTE: the response envelope uses the "status" key for ok/error, so the
    # handler's domain status is asserted on the stored row below instead.
    assert r["status"] == "ok"
    assert r["naming_series"].startswith("REF-")
    row = conn.execute(
        "SELECT company_id, patient_id, referring_provider_id, "
        "referred_to_provider, referred_to_specialty, referral_date, "
        "reason, priority, prior_auth_required, status, naming_series "
        "FROM healthclaw_referral WHERE id = ?", (r["id"],)).fetchone()
    assert dict(row) == {
        "company_id": env["company_id"], "patient_id": env["patient_id"],
        "referring_provider_id": env["provider_id"],
        "referred_to_provider": "Dr. Cardio Specialist",
        "referred_to_specialty": "Cardiology", "referral_date": "2026-03-15",
        "reason": "Chest pain evaluation", "priority": "routine",
        "prior_auth_required": 0, "status": "pending",
        "naming_series": r["naming_series"],
    }
    assert dict(conn.execute("SELECT * FROM healthclaw_referral WHERE id = ?",
                             (control,)).fetchone()) == control_row
    _no_ledger(conn)


def test_m421_referral_refusal_writes_nothing(conn, env):
    before = _snap(conn, ["healthclaw_referral", "gl_entry",
                          "payment_ledger_entry"])
    r = call_action(ACTIONS["health-add-referral"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        referring_provider_id=None, referred_to_provider="Dr. X",
        referred_to_specialty=None, referred_to_facility=None,
        referred_to_phone=None, referred_to_fax=None,
        referral_date="2026-03-15", expiration_date=None, reason="Eval",
        encounter_id=None, diagnosis_id=None, priority=None,
        insurance_id=None, prior_auth_required=None, prior_auth_id=None,
        referral_status=None, status=None, notes=None, limit=50, offset=0))
    assert is_error(r)
    assert _msg(r) == "--referring-provider-id is required"
    assert _snap(conn, ["healthclaw_referral", "gl_entry",
                        "payment_ledger_entry"]) == before


# ---------------------------------------------------------------------------
# health-add-prior-auth
# ---------------------------------------------------------------------------

def _prior_auth(conn, env, insurance_id, description="Office visit pre-auth"):
    r = call_action(ACTIONS["health-add-prior-auth"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        insurance_id=insurance_id,
        requesting_provider_id=env["provider_id"], service_type="procedure",
        cpt_codes="99213", icd10_codes="J06.9", description=description,
        units_requested="2", request_date="2026-03-15",
        effective_date="2026-03-15", expiration_date="2026-06-15",
        auth_number=None, auth_status=None, decision_date=None,
        units_approved=None, notes=None, status=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def test_m421_prior_auth_writes_exact_row(conn, env):
    ins = _insurance(conn, env)
    control = _prior_auth(conn, env, ins, description="Control auth")
    control_row = dict(conn.execute("SELECT * FROM healthclaw_prior_auth "
                                    "WHERE id = ?", (control,)).fetchone())
    r = call_action(ACTIONS["health-add-prior-auth"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        insurance_id=ins, requesting_provider_id=env["provider_id"],
        service_type="procedure", cpt_codes="99213", icd10_codes="J06.9",
        description="Office visit pre-auth", units_requested="2",
        request_date="2026-03-15", effective_date="2026-03-15",
        expiration_date="2026-06-15", auth_number=None, auth_status=None,
        decision_date=None, units_approved=None, notes=None, status=None,
        limit=50, offset=0))
    assert is_ok(r), r
    assert r["service_type"] == "procedure"
    # NOTE: the response envelope uses the "status" key for ok/error, so the
    # handler's domain status is asserted on the stored row below instead.
    assert r["status"] == "ok"
    assert r["naming_series"].startswith("AUTH-")
    row = conn.execute(
        "SELECT company_id, patient_id, insurance_id, "
        "requesting_provider_id, service_type, cpt_codes, icd10_codes, "
        "description, units_requested, units_approved, request_date, "
        "effective_date, expiration_date, decision_date, status, "
        "naming_series FROM healthclaw_prior_auth WHERE id = ?",
        (r["id"],)).fetchone()
    assert dict(row) == {
        "company_id": env["company_id"], "patient_id": env["patient_id"],
        "insurance_id": ins, "requesting_provider_id": env["provider_id"],
        "service_type": "procedure", "cpt_codes": "99213",
        "icd10_codes": "J06.9", "description": "Office visit pre-auth",
        "units_requested": 2, "units_approved": None,
        "request_date": "2026-03-15", "effective_date": "2026-03-15",
        "expiration_date": "2026-06-15", "decision_date": None,
        "status": "pending", "naming_series": r["naming_series"],
    }
    assert dict(conn.execute("SELECT * FROM healthclaw_prior_auth "
                             "WHERE id = ?", (control,)).fetchone()) == control_row
    _no_ledger(conn)


def test_m421_prior_auth_refusal_writes_nothing(conn, env):
    ins = _insurance(conn, env)
    before = _snap(conn, ["healthclaw_prior_auth", "gl_entry",
                          "payment_ledger_entry"])
    r = call_action(ACTIONS["health-add-prior-auth"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        insurance_id=ins, requesting_provider_id=env["provider_id"],
        service_type="procedure", cpt_codes="99213", icd10_codes="J06.9",
        description=None, units_requested="1", request_date="2026-03-15",
        effective_date=None, expiration_date=None, auth_number=None,
        auth_status=None, decision_date=None, units_approved=None,
        notes=None, status=None, limit=50, offset=0))
    assert is_error(r)
    assert _msg(r) == "--description is required"
    assert _snap(conn, ["healthclaw_prior_auth", "gl_entry",
                        "payment_ledger_entry"]) == before


# ---------------------------------------------------------------------------
# health-add-payment-posting (core billing)
# ---------------------------------------------------------------------------

def _core_posting(conn, env, claim_id, **over):
    kw = dict(company_id=env["company_id"], patient_id=env["patient_id"],
              posting_type="insurance_payment", posting_date="2026-04-01",
              amount="150.00", claim_id=claim_id, payment_entry_id=None,
              payment_method="check", check_number="CHK-7781",
              payer_name="Acme Health", eob_date="2026-03-30", notes=None)
    kw.update(over)
    return call_action(ACTIONS["health-add-payment-posting"], conn, ns(**kw))


def test_m421_core_posting_writes_exact_row(conn, env):
    claim_id = _core_claim(conn, env, _insurance(conn, env))
    claim_before = dict(conn.execute("SELECT * FROM healthclaw_claim "
                                     "WHERE id = ?", (claim_id,)).fetchone())
    r = _core_posting(conn, env, claim_id)
    assert is_ok(r), r
    assert r["amount"] == "150.00"
    assert Decimal(r["amount"]) == Decimal("150.00")
    row = conn.execute(
        "SELECT claim_id, patient_id, posting_type, posting_date, amount, "
        "check_number, payer_name, payment_method, eob_date, company_id "
        "FROM healthclaw_payment_posting WHERE id = ?", (r["id"],)).fetchone()
    assert dict(row) == {
        "claim_id": claim_id, "patient_id": env["patient_id"],
        "posting_type": "insurance_payment", "posting_date": "2026-04-01",
        "amount": "150.00", "check_number": "CHK-7781",
        "payer_name": "Acme Health", "payment_method": "check",
        "eob_date": "2026-03-30", "company_id": env["company_id"],
    }
    assert Decimal(row["amount"]) == Decimal("150.00")
    r2 = _core_posting(conn, env, claim_id, posting_type="patient_payment",
                       amount="25", payment_method="cash", check_number=None,
                       payer_name=None, eob_date=None)
    assert is_ok(r2), r2
    amounts = sorted(x["amount"] for x in conn.execute(
        "SELECT amount FROM healthclaw_payment_posting WHERE claim_id = ?",
        (claim_id,)).fetchall())
    assert amounts == ["150.00", "25.00"]
    assert Decimal(amounts[0]) == Decimal("150.00")
    assert Decimal(amounts[1]) == Decimal("25.00")
    assert dict(conn.execute("SELECT * FROM healthclaw_claim WHERE id = ?",
                             (claim_id,)).fetchone()) == claim_before
    _no_ledger(conn)


def test_m421_core_posting_refusal_writes_nothing(conn, env):
    claim_id = _core_claim(conn, env, _insurance(conn, env))
    before = _snap(conn, ["healthclaw_payment_posting", "healthclaw_claim",
                          "gl_entry", "payment_ledger_entry"])
    r = _core_posting(conn, env, claim_id, posting_type="bonus")
    assert is_error(r)
    assert _msg(r).startswith("Invalid health-posting-type: bonus.")
    r = _core_posting(conn, env, "no-such-claim")
    assert is_error(r)
    assert _msg(r) == "Claim no-such-claim not found"
    assert _snap(conn, ["healthclaw_payment_posting", "healthclaw_claim",
                        "gl_entry", "payment_ledger_entry"]) == before


# ---------------------------------------------------------------------------
# health-adv-add-payment-posting
# ---------------------------------------------------------------------------

def _adv_posting(conn, env, claim_id, charge_id, allowed, paid, adjustment,
                 patient_resp, **over):
    kw = dict(company_id=env["company_id"], claim_id=claim_id,
              patient_id=env["patient_id"], payer_name="Acme Health",
              posting_date="2026-04-01", charge_id=charge_id,
              allowed_amount=allowed, paid_amount=paid, adjustment=adjustment,
              patient_responsibility=patient_resp, payment_method="eft",
              check_number=None, notes=None)
    kw.update(over)
    return call_action(ACTIONS["health-adv-add-payment-posting"], conn, ns(**kw))


def _claim_totals(conn, claim_id):
    row = conn.execute(
        "SELECT total_allowed, total_paid, total_adjustment, "
        "patient_responsibility FROM healthclaw_claim WHERE id = ?",
        (claim_id,)).fetchone()
    return tuple(row)


def test_m421_adv_posting_writes_row_and_accumulates_totals(conn, env):
    claim_id = _core_claim(conn, env, _insurance(conn, env))
    charge_id = _adv_charge(conn, env)
    assert _claim_totals(conn, claim_id) == ("0.00", "0.00", "0.00", "0.00")
    r = _adv_posting(conn, env, claim_id, charge_id,
                     "200.00", "120.00", "50.00", "30.00")
    assert is_ok(r), r
    assert r["paid_amount"] == "120.00"
    assert r["adjustment"] == "50.00"
    assert Decimal(r["paid_amount"]) == Decimal("120.00")
    row = conn.execute(
        "SELECT claim_id, charge_id, patient_id, payer_name, posting_date, "
        "allowed_amount, paid_amount, adjustment, patient_responsibility, "
        "payment_method FROM healthclaw_payment_posting WHERE id = ?",
        (r["id"],)).fetchone()
    assert dict(row) == {
        "claim_id": claim_id, "charge_id": charge_id,
        "patient_id": env["patient_id"], "payer_name": "Acme Health",
        "posting_date": "2026-04-01", "allowed_amount": "200.00",
        "paid_amount": "120.00", "adjustment": "50.00",
        "patient_responsibility": "30.00", "payment_method": "eft",
    }
    assert Decimal(row["allowed_amount"]) == Decimal("200.00")
    assert _claim_totals(conn, claim_id) == ("200.00", "120.00", "50.00",
                                             "30.00")
    r2 = _adv_posting(conn, env, claim_id, None,
                      "50.00", "30.00", "10.00", "9.00")
    assert is_ok(r2), r2
    assert _claim_totals(conn, claim_id) == ("250.00", "150.00", "60.00",
                                             "39.00")
    assert conn.execute("SELECT claim_status FROM healthclaw_claim "
                        "WHERE id = ?", (claim_id,)).fetchone()[0] == "draft"
    _no_ledger(conn)


def test_m421_adv_posting_refusal_writes_nothing(conn, env):
    claim_id = _core_claim(conn, env, _insurance(conn, env))
    charge_id = _adv_charge(conn, env)
    assert is_ok(_adv_posting(conn, env, claim_id, charge_id,
                              "100.00", "80.00", "20.00", "0.00"))
    before = _snap(conn, ["healthclaw_payment_posting", "healthclaw_claim",
                          "gl_entry", "payment_ledger_entry"])
    totals_before = _claim_totals(conn, claim_id)
    r = _adv_posting(conn, env, "no-such-claim", charge_id,
                     "100.00", "80.00", "20.00", "0.00")
    assert is_error(r)
    assert _msg(r) == "Claim no-such-claim not found"
    r = _adv_posting(conn, env, claim_id, "no-such-charge",
                     "100.00", "80.00", "20.00", "0.00")
    assert is_error(r)
    assert _msg(r) == "Charge no-such-charge not found"
    r = _adv_posting(conn, env, claim_id, charge_id,
                     "100.00", "80.00", "20.00", "0.00", payer_name=None)
    assert is_error(r)
    assert _msg(r) == "--payer-name is required"
    assert _snap(conn, ["healthclaw_payment_posting", "healthclaw_claim",
                        "gl_entry", "payment_ledger_entry"]) == before
    assert _claim_totals(conn, claim_id) == totals_before
