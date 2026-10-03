"""Depth tests: what the 12 read/submit/report actions actually do to the DB.

The pre-existing tests for these actions
(testing/integration/contract/test_healthclaw_contract.py) only prove each
kebab-case name routes; health-adv-submit-claim and health-batch-submit-claims
additionally have behavioural tests in
test_payment_posting_claim_submit_behaviour.py. The tests below deepen the
whole set of 12: each drives its action BY LITERAL NAME through the aggregate
router registry, then reads the database back and compares exact values.

Per-action depth (stored row vs ledger effect):
  - health-adv-get-claim: stored healthclaw_claim row (read).
  - health-adv-get-lab-order: stored healthclaw_lab_order row (read).
  - health-adv-list-charges: stored healthclaw_charge rows (read).
  - health-adv-list-claims: stored healthclaw_claim rows (read).
  - health-adv-list-lab-orders: stored healthclaw_lab_order rows (read).
  - health-adv-list-lab-results: stored healthclaw_lab_result rows (read).
  - health-adv-list-lab-tests: stored healthclaw_lab_test rows (read).
  - health-adv-list-payment-postings: stored healthclaw_payment_posting rows (read).
  - health-adv-list-prescriptions: stored healthclaw_prescription rows (read).
  - health-adv-submit-claim: stored healthclaw_claim + healthclaw_charge rows (write).
  - health-aging-report: stored healthclaw_charge rows, aggregated (read).
  - health-batch-submit-claims: stored healthclaw_claim rows (write).
None of the 12 reaches the general ledger or the payment ledger, so every
happy-path test pins gl_entry/payment_ledger_entry at zero with a comment
instead of asserting legs that cannot exist. Money is compared as exact
Decimal strings; float never appears.
"""
import json
import os
import sys
from datetime import date, timedelta, timezone
from datetime import datetime as _datetime
from decimal import Decimal

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from health_helpers import (build_env, call_action, is_error, is_ok,  # noqa: E402
                            load_db_query, ns, seed_company, seed_patient)

ACTIONS = load_db_query().ACTIONS

CLAIM_TABLES = ["healthclaw_claim", "healthclaw_charge",
                "healthclaw_claim_line", "healthclaw_payment_posting",
                "audit_log"]
LAB_TABLES = ["healthclaw_lab_test", "healthclaw_lab_order",
              "healthclaw_lab_result", "audit_log"]
RX_TABLES = ["healthclaw_prescription", "healthclaw_medication", "audit_log"]
CHARGE_TABLES = ["healthclaw_charge", "audit_log"]


def _msg(r):
    return r.get("message", "") + r.get("error", "")


def _dump(conn, table):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM %s ORDER BY id" % table).fetchall()]


def _snapshot(conn, tables):
    return {t: _dump(conn, t) for t in tables}


def _ledger_is_empty(conn):
    # None of the 12 actions covered here posts to the general ledger or the
    # payment ledger, so there are no debit/credit legs to balance; pin that.
    assert conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM payment_ledger_entry").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Setup closures (each drives an existing owner action, then returns the id)
# ---------------------------------------------------------------------------

def _charge(conn, env, unit_fee="125.00", quantity="2",
            service_date="2026-03-15", company=None, patient=None,
            provider=None):
    r = call_action(ACTIONS["health-adv-add-charge"], conn, ns(
        company_id=company or env["company_id"],
        patient_id=patient or env["patient_id"],
        provider_id=provider or env["provider_id"], procedure_code_id=None,
        service_date=service_date, cpt_code="99213", icd10_codes=None,
        description=None, quantity=quantity, unit_fee=unit_fee, notes=None))
    assert is_ok(r), r
    return r["id"]


def _adv_claim(conn, env, charge_ids, payer_name="Acme Health",
               claim_date="2026-03-20", company=None, patient=None):
    r = call_action(ACTIONS["health-adv-add-claim"], conn, ns(
        company_id=company or env["company_id"],
        patient_id=patient or env["patient_id"], payer_name=payer_name,
        payer_id_number=None, policy_number=None, group_number=None,
        claim_number=None, claim_date=claim_date,
        charge_ids=json.dumps(charge_ids), notes=None))
    assert is_ok(r), r
    return r["id"]


def _lab_test(conn, env, name="CBC", category="hematology",
              base_price="45.50", company=None):
    r = call_action(ACTIONS["health-adv-add-lab-test"], conn, ns(
        company_id=company or env["company_id"], test_name=name,
        test_code=name, loinc_code=None, category=category,
        specimen_type="blood", reference_range="4.5-11.0", unit="x10^9/L",
        turnaround_hours=24, base_price=base_price, notes=None))
    assert is_ok(r), r
    return r["id"]


def _lab_order(conn, env, lab_test_id, order_date="2026-03-10",
               priority="routine", company=None, patient=None):
    r = call_action(ACTIONS["health-adv-add-lab-order"], conn, ns(
        company_id=company or env["company_id"],
        patient_id=patient or env["patient_id"],
        ordering_provider="Dr. Test Provider", lab_test_id=lab_test_id,
        order_date=order_date, priority=priority,
        clinical_notes="rule out anemia", fasting_required=1, notes=None))
    assert is_ok(r), r
    return r["id"]


def _lab_result(conn, env, lab_order_id, value="12.1", abnormal=1,
                critical=0, company=None):
    r = call_action(ACTIONS["health-adv-add-lab-result"], conn, ns(
        company_id=company or env["company_id"], lab_order_id=lab_order_id,
        result_value=value, result_unit="x10^9/L",
        reference_range="4.5-11.0", is_abnormal=abnormal,
        is_critical=critical, performed_by="Tech", verified_by="Dr",
        result_date="2026-03-11", result_notes=None))
    assert is_ok(r), r
    return r["id"]


def _medication(conn, env, name="Amoxicillin", unit_price="12.75",
                company=None):
    r = call_action(ACTIONS["health-add-medication"], conn, ns(
        company_id=company or env["company_id"], name=name,
        generic_name=None, ndc_code=None, dea_schedule=None,
        dosage_form=None, strength=None, manufacturer=None,
        unit_price=unit_price, quantity_on_hand=None, reorder_level=None,
        notes=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _prescription(conn, env, medication_id, rx_number="RX-1", dosage="500mg",
                  frequency="BID", prescribed_date="2026-03-12",
                  company=None, patient=None):
    r = call_action(ACTIONS["health-adv-add-prescription"], conn, ns(
        company_id=company or env["company_id"],
        patient_id=patient or env["patient_id"],
        prescriber_id=env["provider_id"], medication_id=medication_id,
        rx_number=rx_number, dosage=dosage, frequency=frequency, route=None,
        quantity_prescribed=20, refills_authorized=1, dea_number=None,
        prescribed_date=prescribed_date, expiry_date=None, notes=None))
    assert is_ok(r), r
    return r["id"]


def _adv_posting(conn, env, claim_id, allowed="200.00", paid="150.00",
                 adjustment="30.00", responsibility="20.00",
                 payer="Acme Health", posting_date="2026-04-01",
                 method="check", check="CHK-1"):
    r = call_action(ACTIONS["health-adv-add-payment-posting"], conn, ns(
        company_id=env["company_id"], claim_id=claim_id, charge_id=None,
        patient_id=env["patient_id"], payer_name=payer,
        posting_date=posting_date, allowed_amount=allowed,
        paid_amount=paid, adjustment=adjustment,
        patient_responsibility=responsibility, payment_method=method,
        check_number=check, notes=None))
    assert is_ok(r), r
    return r["id"]


# ---------------------------------------------------------------------------
# health-adv-get-claim: returns the exact stored claim row (read-only)
# ---------------------------------------------------------------------------

def test_adv_get_claim_returns_the_exact_stored_row(conn, env):
    c1 = _charge(conn, env, "125.00", "2")
    c2 = _charge(conn, env, "40.00", "1")
    untouched = _charge(conn, env, "10.00", "1")
    claim_id = _adv_claim(conn, env, [c1, c2])
    before = _snapshot(conn, CLAIM_TABLES)

    r = call_action(ACTIONS["health-adv-get-claim"], conn,
                    ns(claim_id=claim_id))
    assert is_ok(r), r
    assert r["charge_ids"] == [c1, c2]
    assert r["total_charged"] == "290.00"
    assert Decimal(r["total_charged"]) == Decimal("250.00") + Decimal("40.00")
    assert (r["claim_status"], r["claim_date"],
            r["payer_name"]) == ("draft", "2026-03-20", "Acme Health")

    row = dict(conn.execute(
        "SELECT company_id, patient_id, payer_name, claim_date, charge_ids, "
        "total_charged, total_allowed, total_paid, total_adjustment, "
        "patient_responsibility, claim_status FROM healthclaw_claim "
        "WHERE id = ?", (claim_id,)).fetchone())
    assert row["charge_ids"] == json.dumps([c1, c2])
    assert (row["total_charged"], row["total_allowed"], row["total_paid"],
            row["total_adjustment"], row["patient_responsibility"],
            row["claim_status"]) == ("290.00", "0.00", "0.00", "0.00",
                                     "0.00", "draft")
    assert (row["company_id"], row["patient_id"]) == (env["company_id"],
                                                     env["patient_id"])
    assert r["total_charged"] == row["total_charged"]

    statuses = {x["id"]: x["charge_status"] for x in conn.execute(
        "SELECT id, charge_status FROM healthclaw_charge").fetchall()}
    assert statuses == {c1: "unbilled", c2: "unbilled",
                        untouched: "unbilled"}
    # A get writes nothing, not even an audit row.
    assert _snapshot(conn, CLAIM_TABLES) == before
    # Does not reach the ledger: no legs to balance.
    _ledger_is_empty(conn)


def test_adv_get_claim_refusals_leave_the_db_identical(conn, env):
    c1 = _charge(conn, env, "125.00", "2")
    claim_id = _adv_claim(conn, env, [c1])
    before = _snapshot(conn, CLAIM_TABLES)

    r = call_action(ACTIONS["health-adv-get-claim"], conn, ns(claim_id=None))
    assert is_error(r)
    assert _msg(r) == "--claim-id is required"

    r = call_action(ACTIONS["health-adv-get-claim"], conn,
                    ns(claim_id="no-such-claim"))
    assert is_error(r)
    assert _msg(r) == "Claim no-such-claim not found"

    assert _snapshot(conn, CLAIM_TABLES) == before
    assert conn.execute("SELECT claim_status FROM healthclaw_claim "
                        "WHERE id = ?", (claim_id,)).fetchone()[0] == "draft"


# ---------------------------------------------------------------------------
# health-adv-get-lab-order: returns the exact stored lab order row (read-only)
# ---------------------------------------------------------------------------

def test_adv_get_lab_order_returns_the_exact_stored_row(conn, env):
    test_id = _lab_test(conn, env)
    order_id = _lab_order(conn, env, test_id, priority="urgent")
    before = _snapshot(conn, LAB_TABLES)

    r = call_action(ACTIONS["health-adv-get-lab-order"], conn,
                    ns(lab_order_id=order_id))
    assert is_ok(r), r

    row = dict(conn.execute(
        "SELECT company_id, patient_id, ordering_provider, lab_test_id, "
        "order_date, priority, order_status, clinical_notes, "
        "fasting_required FROM healthclaw_lab_order WHERE id = ?",
        (order_id,)).fetchone())
    assert row == {"company_id": env["company_id"],
                   "patient_id": env["patient_id"],
                   "ordering_provider": "Dr. Test Provider",
                   "lab_test_id": test_id, "order_date": "2026-03-10",
                   "priority": "urgent", "order_status": "ordered",
                   "clinical_notes": "rule out anemia",
                   "fasting_required": 1}
    for key, value in row.items():
        assert r[key] == value, key
    # A get writes nothing, not even an audit row.
    assert _snapshot(conn, LAB_TABLES) == before
    # Does not reach the ledger: no legs to balance.
    _ledger_is_empty(conn)


def test_adv_get_lab_order_refusals_leave_the_db_identical(conn, env):
    test_id = _lab_test(conn, env)
    order_id = _lab_order(conn, env, test_id)
    before = _snapshot(conn, LAB_TABLES)

    r = call_action(ACTIONS["health-adv-get-lab-order"], conn,
                    ns(lab_order_id=None))
    assert is_error(r)
    assert _msg(r) == "--lab-order-id is required"

    r = call_action(ACTIONS["health-adv-get-lab-order"], conn,
                    ns(lab_order_id="no-such-order"))
    assert is_error(r)
    assert _msg(r) == "Lab order no-such-order not found"

    assert _snapshot(conn, LAB_TABLES) == before
    assert conn.execute("SELECT order_status FROM healthclaw_lab_order "
                        "WHERE id = ?", (order_id,)).fetchone()[0] == "ordered"


# ---------------------------------------------------------------------------
# health-adv-list-charges: returns exactly the matching stored rows (read-only)
# ---------------------------------------------------------------------------

def test_adv_list_charges_returns_exact_rows_and_money(conn, env):
    c1 = _charge(conn, env, "125.00", "2", service_date="2026-03-15")
    c2 = _charge(conn, env, "40.00", "1", service_date="2026-03-16")
    other = build_env(conn)
    other_charge = _charge(conn, other, "10.00", "1")
    before = _snapshot(conn, CHARGE_TABLES)

    r = call_action(ACTIONS["health-adv-list-charges"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        charge_status=None, search=None, limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert {row["id"] for row in r["rows"]} == {c1, c2}
    assert other_charge not in {row["id"] for row in r["rows"]}
    by_id = {row["id"]: row for row in r["rows"]}
    assert (by_id[c1]["total_fee"], by_id[c2]["total_fee"]) == ("250.00",
                                                               "40.00")
    assert Decimal(by_id[c1]["total_fee"]) == Decimal("125.00") * 2
    assert Decimal(by_id[c2]["total_fee"]) == Decimal("40.00") * 1
    for row in r["rows"]:
        stored = dict(conn.execute(
            "SELECT patient_id, service_date, cpt_code, quantity, unit_fee, "
            "total_fee, charge_status, company_id FROM healthclaw_charge "
            "WHERE id = ?", (row["id"],)).fetchone())
        assert stored["company_id"] == env["company_id"]
        assert row["total_fee"] == stored["total_fee"]
        assert row["charge_status"] == stored["charge_status"] == "unbilled"

    r = call_action(ACTIONS["health-adv-list-charges"], conn, ns(
        company_id=env["company_id"], patient_id=None,
        charge_status="unbilled", search=None, limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 2

    # Read-only: the list wrote nothing, not even an audit row.
    assert _snapshot(conn, CHARGE_TABLES) == before
    # Does not reach the ledger: no legs to balance.
    _ledger_is_empty(conn)


def test_adv_list_charges_empty_filter_reads_nothing_and_writes_nothing(
        conn, env):
    # list-charges validates no input, so there is no refusal path; an
    # unmatched filter must return an empty page and leave the DB identical.
    c1 = _charge(conn, env, "125.00", "2")
    before = _snapshot(conn, CHARGE_TABLES)

    r = call_action(ACTIONS["health-adv-list-charges"], conn, ns(
        company_id=env["company_id"], patient_id=None,
        charge_status="paid", search=None, limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["rows"], r["has_more"]) == (0, [], False)

    assert _snapshot(conn, CHARGE_TABLES) == before
    assert conn.execute("SELECT charge_status FROM healthclaw_charge "
                        "WHERE id = ?", (c1,)).fetchone()[0] == "unbilled"


# ---------------------------------------------------------------------------
# health-adv-list-claims: returns exactly the matching stored rows (read-only)
# ---------------------------------------------------------------------------

def test_adv_list_claims_returns_exact_rows_and_money(conn, env):
    ch1 = _charge(conn, env, "125.00", "2")
    ch2 = _charge(conn, env, "40.00", "1")
    draft_id = _adv_claim(conn, env, [ch1, ch2], payer_name="Acme Health")
    other_id = _adv_claim(conn, env, [], payer_name="Beta Payer")
    other = build_env(conn)
    foreign_id = _adv_claim(conn, other, [], payer_name="Acme Health")
    assert is_ok(call_action(ACTIONS["health-adv-submit-claim"], conn,
                             ns(claim_id=draft_id)))
    before = _snapshot(conn, CLAIM_TABLES)

    r = call_action(ACTIONS["health-adv-list-claims"], conn, ns(
        company_id=env["company_id"], patient_id=None, claim_status="draft",
        payer_name=None, search=None, limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 1
    assert r["rows"][0]["id"] == other_id
    assert r["rows"][0]["total_charged"] == "0.00"

    r = call_action(ACTIONS["health-adv-list-claims"], conn, ns(
        company_id=env["company_id"], patient_id=None, claim_status=None,
        payer_name="Acme Health", search=None, limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 1
    row = r["rows"][0]
    assert row["id"] == draft_id
    assert row["claim_status"] == "submitted"
    assert row["total_charged"] == "290.00"
    assert Decimal(row["total_charged"]) == Decimal("250.00") + Decimal("40.00")
    # list-claims returns the raw stored JSON string (only get-claim parses it).
    assert row["charge_ids"] == json.dumps([ch1, ch2])
    assert foreign_id not in {x["id"] for x in r["rows"]}

    # Read-only: the lists wrote nothing, not even an audit row.
    assert _snapshot(conn, CLAIM_TABLES) == before
    # Does not reach the ledger: no legs to balance.
    _ledger_is_empty(conn)


def test_adv_list_claims_empty_filter_reads_nothing_and_writes_nothing(
        conn, env):
    # list-claims validates no input, so there is no refusal path; an
    # unmatched filter must return an empty page and leave the DB identical.
    claim_id = _adv_claim(conn, env, [])
    before = _snapshot(conn, CLAIM_TABLES)

    r = call_action(ACTIONS["health-adv-list-claims"], conn, ns(
        company_id=env["company_id"], patient_id=None,
        claim_status="denied", payer_name=None, search=None, limit=50,
        offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["rows"], r["has_more"]) == (0, [], False)

    assert _snapshot(conn, CLAIM_TABLES) == before
    assert conn.execute("SELECT claim_status FROM healthclaw_claim "
                        "WHERE id = ?", (claim_id,)).fetchone()[0] == "draft"


# ---------------------------------------------------------------------------
# health-adv-list-lab-orders: returns exactly the matching stored rows
# ---------------------------------------------------------------------------

def test_adv_list_lab_orders_returns_exact_rows(conn, env):
    test_id = _lab_test(conn, env)
    o1 = _lab_order(conn, env, test_id, order_date="2026-03-10")
    o2 = _lab_order(conn, env, test_id, order_date="2026-03-11")
    _lab_result(conn, env, o2)
    other = build_env(conn)
    foreign_id = _lab_order(conn, other, test_id, order_date="2026-03-12")
    before = _snapshot(conn, LAB_TABLES)

    r = call_action(ACTIONS["health-adv-list-lab-orders"], conn, ns(
        company_id=env["company_id"], patient_id=None,
        lab_test_id=test_id, order_status=None, priority=None, search=None,
        limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert {row["id"] for row in r["rows"]} == {o1, o2}
    assert foreign_id not in {row["id"] for row in r["rows"]}
    by_id = {row["id"]: row for row in r["rows"]}
    assert (by_id[o1]["order_status"],
            by_id[o2]["order_status"]) == ("ordered", "completed")
    assert by_id[o1]["lab_test_id"] == test_id
    for row in r["rows"]:
        stored = dict(conn.execute(
            "SELECT company_id, patient_id, lab_test_id, order_date, "
            "priority, order_status FROM healthclaw_lab_order WHERE id = ?",
            (row["id"],)).fetchone())
        assert stored["company_id"] == env["company_id"]
        assert row["order_status"] == stored["order_status"]
        assert row["order_date"] == stored["order_date"]

    r = call_action(ACTIONS["health-adv-list-lab-orders"], conn, ns(
        company_id=env["company_id"], patient_id=None,
        lab_test_id=test_id, order_status="ordered", priority=None,
        search=None, limit=50, offset=0))
    assert is_ok(r), r
    assert [row["id"] for row in r["rows"]] == [o1]

    # Read-only: the lists wrote nothing, not even an audit row.
    assert _snapshot(conn, LAB_TABLES) == before
    # Does not reach the ledger: no legs to balance.
    _ledger_is_empty(conn)


def test_adv_list_lab_orders_empty_filter_reads_nothing_and_writes_nothing(
        conn, env):
    # list-lab-orders validates no input, so there is no refusal path; an
    # unmatched filter must return an empty page and leave the DB identical.
    test_id = _lab_test(conn, env)
    order_id = _lab_order(conn, env, test_id)
    before = _snapshot(conn, LAB_TABLES)

    r = call_action(ACTIONS["health-adv-list-lab-orders"], conn, ns(
        company_id=env["company_id"], patient_id=None, lab_test_id=test_id,
        order_status="cancelled", priority=None, search=None, limit=50,
        offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["rows"], r["has_more"]) == (0, [], False)

    assert _snapshot(conn, LAB_TABLES) == before
    assert conn.execute("SELECT order_status FROM healthclaw_lab_order "
                        "WHERE id = ?", (order_id,)).fetchone()[0] == "ordered"


# ---------------------------------------------------------------------------
# health-adv-list-lab-results: returns exactly the matching stored rows
# ---------------------------------------------------------------------------

def test_adv_list_lab_results_returns_exact_rows(conn, env):
    test_id = _lab_test(conn, env)
    order_id = _lab_order(conn, env, test_id)
    r1 = _lab_result(conn, env, order_id, value="12.1", abnormal=1)
    r2 = _lab_result(conn, env, order_id, value="5.4", abnormal=0)
    before = _snapshot(conn, LAB_TABLES)

    r = call_action(ACTIONS["health-adv-list-lab-results"], conn, ns(
        company_id=env["company_id"], patient_id=None,
        lab_order_id=order_id, lab_test_id=None, is_abnormal=None,
        is_critical=None, limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 2
    by_id = {row["id"]: row for row in r["rows"]}
    assert set(by_id) == {r1, r2}
    assert (by_id[r1]["result_value"], by_id[r1]["is_abnormal"],
            by_id[r1]["is_critical"]) == ("12.1", 1, 0)
    assert (by_id[r2]["result_value"],
            by_id[r2]["is_abnormal"]) == ("5.4", 0)
    stored = dict(conn.execute(
        "SELECT lab_order_id, lab_test_id, patient_id, result_value, "
        "result_unit, reference_range, is_abnormal, is_critical "
        "FROM healthclaw_lab_result WHERE id = ?", (r1,)).fetchone())
    assert stored == {"lab_order_id": order_id, "lab_test_id": test_id,
                      "patient_id": env["patient_id"],
                      "result_value": "12.1", "result_unit": "x10^9/L",
                      "reference_range": "4.5-11.0", "is_abnormal": 1,
                      "is_critical": 0}
    assert by_id[r1]["result_value"] == stored["result_value"]

    r = call_action(ACTIONS["health-adv-list-lab-results"], conn, ns(
        company_id=env["company_id"], patient_id=None,
        lab_order_id=order_id, lab_test_id=None, is_abnormal=1,
        is_critical=None, limit=50, offset=0))
    assert is_ok(r), r
    assert [row["id"] for row in r["rows"]] == [r1]

    # Read-only: the lists wrote nothing, not even an audit row.
    assert _snapshot(conn, LAB_TABLES) == before
    # Does not reach the ledger: no legs to balance.
    _ledger_is_empty(conn)


def test_adv_list_lab_results_empty_filter_reads_nothing_and_writes_nothing(
        conn, env):
    # list-lab-results validates no input, so there is no refusal path; an
    # unmatched filter must return an empty page and leave the DB identical.
    test_id = _lab_test(conn, env)
    order_id = _lab_order(conn, env, test_id)
    result_id = _lab_result(conn, env, order_id)
    before = _snapshot(conn, LAB_TABLES)

    r = call_action(ACTIONS["health-adv-list-lab-results"], conn, ns(
        company_id=env["company_id"], patient_id=None,
        lab_order_id=order_id, lab_test_id=None, is_abnormal=None,
        is_critical=1, limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["rows"], r["has_more"]) == (0, [], False)

    assert _snapshot(conn, LAB_TABLES) == before
    assert conn.execute("SELECT is_critical FROM healthclaw_lab_result "
                        "WHERE id = ?", (result_id,)).fetchone()[0] == 0


# ---------------------------------------------------------------------------
# health-adv-list-lab-tests: returns exactly the matching stored rows
# ---------------------------------------------------------------------------

def test_adv_list_lab_tests_returns_exact_rows_and_money(conn, env):
    t1 = _lab_test(conn, env, name="CBC", category="hematology",
                   base_price="45.50")
    t2 = _lab_test(conn, env, name="BMP", category="chemistry",
                   base_price="12.00")
    other = build_env(conn)
    foreign_id = _lab_test(conn, other, name="CBC Panel",
                           category="hematology", base_price="99.99")
    before = _snapshot(conn, LAB_TABLES)

    r = call_action(ACTIONS["health-adv-list-lab-tests"], conn, ns(
        company_id=env["company_id"], category="hematology", search=None,
        limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 1
    row = r["rows"][0]
    assert row["id"] == t1
    assert row["base_price"] == "45.50"
    assert Decimal(row["base_price"]) == Decimal("45.50")
    assert foreign_id not in {x["id"] for x in r["rows"]}

    r = call_action(ACTIONS["health-adv-list-lab-tests"], conn, ns(
        company_id=env["company_id"], category=None, search=None, limit=50,
        offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert {x["id"] for x in r["rows"]} == {t1, t2}
    stored = dict(conn.execute(
        "SELECT test_name, category, base_price FROM healthclaw_lab_test "
        "WHERE id = ?", (t2,)).fetchone())
    assert stored == {"test_name": "BMP", "category": "chemistry",
                      "base_price": "12.00"}

    # Read-only: the lists wrote nothing, not even an audit row.
    assert _snapshot(conn, LAB_TABLES) == before
    # Does not reach the ledger: no legs to balance.
    _ledger_is_empty(conn)


def test_adv_list_lab_tests_empty_filter_reads_nothing_and_writes_nothing(
        conn, env):
    # list-lab-tests validates no input, so there is no refusal path; an
    # unmatched filter must return an empty page and leave the DB identical.
    _lab_test(conn, env, name="CBC", category="hematology")
    before = _snapshot(conn, LAB_TABLES)

    r = call_action(ACTIONS["health-adv-list-lab-tests"], conn, ns(
        company_id=env["company_id"], category="microbiology", search=None,
        limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["rows"], r["has_more"]) == (0, [], False)

    assert _snapshot(conn, LAB_TABLES) == before


# ---------------------------------------------------------------------------
# health-adv-list-payment-postings: returns exactly the matching stored rows
# ---------------------------------------------------------------------------

def test_adv_list_payment_postings_returns_exact_rows_and_money(conn, env):
    ch = _charge(conn, env, "250.00", "1")
    claim_id = _adv_claim(conn, env, [ch])
    p1 = _adv_posting(conn, env, claim_id, allowed="200.00", paid="150.00",
                      adjustment="30.00", responsibility="20.00",
                      posting_date="2026-04-01")
    p2 = _adv_posting(conn, env, claim_id, allowed="50.00", paid="40.00",
                      adjustment="5.00", responsibility="5.00",
                      posting_date="2026-04-02")
    before = _snapshot(conn, CLAIM_TABLES)

    r = call_action(ACTIONS["health-adv-list-payment-postings"], conn, ns(
        company_id=env["company_id"], claim_id=claim_id, patient_id=None,
        payer_name=None, limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 2
    by_id = {row["id"]: row for row in r["rows"]}
    assert set(by_id) == {p1, p2}
    assert (by_id[p1]["paid_amount"], by_id[p1]["adjustment"],
            by_id[p1]["allowed_amount"],
            by_id[p1]["patient_responsibility"]) == ("150.00", "30.00",
                                                    "200.00", "20.00")
    assert (by_id[p2]["paid_amount"],
            by_id[p2]["patient_responsibility"]) == ("40.00", "5.00")
    stored = dict(conn.execute(
        "SELECT claim_id, patient_id, payer_name, posting_date, "
        "allowed_amount, paid_amount, adjustment, patient_responsibility, "
        "payment_method, check_number FROM healthclaw_payment_posting "
        "WHERE id = ?", (p1,)).fetchone())
    assert stored == {"claim_id": claim_id, "patient_id": env["patient_id"],
                      "payer_name": "Acme Health",
                      "posting_date": "2026-04-01",
                      "allowed_amount": "200.00", "paid_amount": "150.00",
                      "adjustment": "30.00",
                      "patient_responsibility": "20.00",
                      "payment_method": "check", "check_number": "CHK-1"}
    for key in ("paid_amount", "adjustment", "allowed_amount",
                "patient_responsibility"):
        assert by_id[p1][key] == stored[key]
    # The two postings accumulated onto the claim in exact Decimal strings.
    totals = dict(conn.execute(
        "SELECT total_allowed, total_paid, total_adjustment, "
        "patient_responsibility FROM healthclaw_claim WHERE id = ?",
        (claim_id,)).fetchone())
    assert (totals["total_allowed"], totals["total_paid"],
            totals["total_adjustment"],
            totals["patient_responsibility"]) == ("250.00", "190.00",
                                                 "35.00", "25.00")
    assert Decimal(totals["total_paid"]) == Decimal("150.00") + Decimal("40.00")

    # Read-only: the list wrote nothing, not even an audit row.
    assert _snapshot(conn, CLAIM_TABLES) == before
    # Postings update claim money columns but never reach the ledger.
    _ledger_is_empty(conn)


def test_adv_list_payment_postings_empty_filter_writes_nothing(conn, env):
    # list-payment-postings validates no input, so there is no refusal path;
    # an unmatched filter must return an empty page and leave the DB identical.
    ch = _charge(conn, env, "250.00", "1")
    claim_id = _adv_claim(conn, env, [ch])
    posting_id = _adv_posting(conn, env, claim_id)
    before = _snapshot(conn, CLAIM_TABLES)

    r = call_action(ACTIONS["health-adv-list-payment-postings"], conn, ns(
        company_id=env["company_id"], claim_id=None, patient_id=None,
        payer_name="No Such Payer", limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["rows"], r["has_more"]) == (0, [], False)

    assert _snapshot(conn, CLAIM_TABLES) == before
    assert conn.execute("SELECT paid_amount FROM healthclaw_payment_posting "
                        "WHERE id = ?", (posting_id,)).fetchone()[0] == "150.00"


# ---------------------------------------------------------------------------
# health-adv-list-prescriptions: returns exactly the matching stored rows
# ---------------------------------------------------------------------------

def test_adv_list_prescriptions_returns_exact_rows(conn, env):
    med_id = _medication(conn, env)
    patient_b = seed_patient(conn, env["company_id"], "Bob", "Jones")
    rx1 = _prescription(conn, env, med_id, rx_number="RX-1")
    rx2 = _prescription(conn, env, med_id, rx_number="RX-2", dosage="250mg",
                        frequency="QD", prescribed_date="2026-03-13",
                        patient=patient_b)
    other = build_env(conn)
    foreign_med = _medication(conn, other, name="Ibuprofen")
    foreign_rx = _prescription(conn, other, foreign_med, rx_number="RX-9")
    before = _snapshot(conn, RX_TABLES)

    r = call_action(ACTIONS["health-adv-list-prescriptions"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        medication_id=None, rx_status=None, search=None, limit=50,
        offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 1
    row = r["rows"][0]
    assert row["id"] == rx1
    assert (row["dosage"], row["frequency"], row["route"],
            row["quantity_prescribed"], row["refills_authorized"],
            row["refills_used"], row["rx_status"]) == ("500mg", "BID",
                                                      "oral", 20, 1, 0,
                                                      "active")
    stored = dict(conn.execute(
        "SELECT company_id, patient_id, medication_id, rx_number, dosage, "
        "frequency, route, quantity_prescribed, refills_authorized, "
        "refills_used, rx_status, prescribed_date "
        "FROM healthclaw_prescription WHERE id = ?", (rx1,)).fetchone())
    assert stored == {"company_id": env["company_id"],
                      "patient_id": env["patient_id"],
                      "medication_id": med_id, "rx_number": "RX-1",
                      "dosage": "500mg", "frequency": "BID", "route": "oral",
                      "quantity_prescribed": 20, "refills_authorized": 1,
                      "refills_used": 0, "rx_status": "active",
                      "prescribed_date": "2026-03-12"}
    assert row["prescribed_date"] == stored["prescribed_date"]

    r = call_action(ACTIONS["health-adv-list-prescriptions"], conn, ns(
        company_id=env["company_id"], patient_id=None, medication_id=None,
        rx_status="active", search=None, limit=50, offset=0))
    assert is_ok(r), r
    assert {x["id"] for x in r["rows"]} == {rx1, rx2}
    assert foreign_rx not in {x["id"] for x in r["rows"]}

    # Read-only: the lists wrote nothing, not even an audit row.
    assert _snapshot(conn, RX_TABLES) == before
    # Does not reach the ledger: no legs to balance.
    _ledger_is_empty(conn)


def test_adv_list_prescriptions_empty_filter_writes_nothing(conn, env):
    # list-prescriptions validates no input, so there is no refusal path; an
    # unmatched filter must return an empty page and leave the DB identical.
    med_id = _medication(conn, env)
    rx_id = _prescription(conn, env, med_id)
    before = _snapshot(conn, RX_TABLES)

    r = call_action(ACTIONS["health-adv-list-prescriptions"], conn, ns(
        company_id=env["company_id"], patient_id=None, medication_id=None,
        rx_status="void", search=None, limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["rows"], r["has_more"]) == (0, [], False)

    assert _snapshot(conn, RX_TABLES) == before
    assert conn.execute("SELECT rx_status FROM healthclaw_prescription "
                        "WHERE id = ?", (rx_id,)).fetchone()[0] == "active"


# ---------------------------------------------------------------------------
# health-adv-submit-claim: flips status, bills charges, touches no money
# ---------------------------------------------------------------------------

def test_adv_submit_claim_moves_status_and_bills_but_moves_no_money(
        conn, env):
    c1 = _charge(conn, env, "125.00", "2")
    c2 = _charge(conn, env, "40.00", "1")
    untouched = _charge(conn, env, "10.00", "1")
    claim_id = _adv_claim(conn, env, [c1, c2])
    money_before = dict(conn.execute(
        "SELECT total_charged, total_allowed, total_paid, total_adjustment, "
        "patient_responsibility FROM healthclaw_claim WHERE id = ?",
        (claim_id,)).fetchone())

    r = call_action(ACTIONS["health-adv-submit-claim"], conn,
                    ns(claim_id=claim_id))
    assert is_ok(r), r
    assert (r["claim_status"], r["charges_billed"]) == ("submitted", 2)

    row = dict(conn.execute(
        "SELECT claim_status, submitted_date, total_charged, total_allowed, "
        "total_paid, total_adjustment, patient_responsibility "
        "FROM healthclaw_claim WHERE id = ?", (claim_id,)).fetchone())
    assert row["claim_status"] == "submitted"
    assert row["submitted_date"] == r["submitted_date"]
    assert row["submitted_date"].endswith("Z")
    # Submitting moves no money: every money column is exactly what it was.
    assert {k: row[k] for k in money_before} == money_before
    assert (row["total_charged"], row["total_allowed"],
            row["total_paid"]) == ("290.00", "0.00", "0.00")
    statuses = {x["id"]: (x["charge_status"], x["total_fee"])
                for x in conn.execute(
                    "SELECT id, charge_status, total_fee "
                    "FROM healthclaw_charge").fetchall()}
    assert statuses == {c1: ("billed", "250.00"), c2: ("billed", "40.00"),
                        untouched: ("unbilled", "10.00")}
    # Status flip, not a ledger posting: no legs to balance.
    _ledger_is_empty(conn)


def test_adv_submit_claim_refusals_leave_the_db_identical(conn, env):
    c1 = _charge(conn, env, "125.00", "2")
    claim_id = _adv_claim(conn, env, [c1])
    before = _snapshot(conn, CLAIM_TABLES)

    r = call_action(ACTIONS["health-adv-submit-claim"], conn,
                    ns(claim_id="no-such-claim"))
    assert is_error(r)
    assert _msg(r) == "Claim no-such-claim not found"

    r = call_action(ACTIONS["health-adv-submit-claim"], conn,
                    ns(claim_id=None))
    assert is_error(r)
    assert _msg(r) == "--claim-id is required"

    assert _snapshot(conn, CLAIM_TABLES) == before
    assert conn.execute("SELECT claim_status FROM healthclaw_claim "
                        "WHERE id = ?", (claim_id,)).fetchone()[0] == "draft"
    assert conn.execute("SELECT charge_status FROM healthclaw_charge "
                        "WHERE id = ?", (c1,)).fetchone()[0] == "unbilled"


# ---------------------------------------------------------------------------
# health-aging-report: aggregates the exact stored charge money (read-only)
# ---------------------------------------------------------------------------

def _aged_charge(conn, env, days_ago, amount, status="unbilled"):
    today = _datetime.now(timezone.utc).date()
    service_date = (today - timedelta(days=days_ago)).isoformat()
    charge_id = _charge(conn, env, amount, "1", service_date=service_date)
    if status != "unbilled":
        conn.execute("UPDATE healthclaw_charge SET charge_status = ? "
                     "WHERE id = ?", (status, charge_id))
        conn.commit()
    return charge_id, service_date, days_ago


def test_aging_report_buckets_exact_stored_money(conn, env):
    in_30, _, d30 = _aged_charge(conn, env, 10, "100.00")
    in_60, _, d60 = _aged_charge(conn, env, 45, "200.50")
    in_90, _, d90 = _aged_charge(conn, env, 75, "75.25", status="billed")
    in_120, _, d120 = _aged_charge(conn, env, 105, "300.00")
    in_old, _, dold = _aged_charge(conn, env, 150, "50.00")
    paid_id, _, _ = _aged_charge(conn, env, 150, "999.99", status="paid")
    void_id, _, _ = _aged_charge(conn, env, 150, "888.88", status="void")
    before = _snapshot(conn, CHARGE_TABLES)

    r = call_action(ACTIONS["health-aging-report"], conn,
                    ns(company_id=env["company_id"]))
    assert is_ok(r), r
    # Billed charges age too; paid and void ones are excluded, to the cent.
    assert r["total_charges"] == 5
    assert r["total_outstanding"] == "725.75"
    assert Decimal(r["total_outstanding"]) == (Decimal("100.00")
                                              + Decimal("200.50")
                                              + Decimal("75.25")
                                              + Decimal("300.00")
                                              + Decimal("50.00"))
    assert r["buckets"]["0-30"] == {"count": 1, "total": "100.00"}
    assert r["buckets"]["31-60"] == {"count": 1, "total": "200.50"}
    assert r["buckets"]["61-90"] == {"count": 1, "total": "75.25"}
    assert r["buckets"]["91-120"] == {"count": 1, "total": "300.00"}
    assert r["buckets"]["120+"] == {"count": 1, "total": "50.00"}
    details = {entry["id"]: entry
               for entries in r["details"].values() for entry in entries}
    assert set(details) == {in_30, in_60, in_90, in_120, in_old}
    assert paid_id not in details and void_id not in details
    for charge_id, _service_date, days in ((in_30, None, d30),
                                           (in_60, None, d60),
                                           (in_90, None, d90),
                                           (in_120, None, d120),
                                           (in_old, None, dold)):
        entry = details[charge_id]
        assert entry["days_outstanding"] == days
        stored_fee = conn.execute(
            "SELECT total_fee FROM healthclaw_charge WHERE id = ?",
            (charge_id,)).fetchone()[0]
        assert entry["total_fee"] == stored_fee
        assert Decimal(entry["total_fee"]) == Decimal(stored_fee)

    # Read-only: the report wrote nothing, not even an audit row.
    assert _snapshot(conn, CHARGE_TABLES) == before
    # An aggregate over stored money, not a ledger posting: nothing to balance.
    _ledger_is_empty(conn)


def test_aging_report_empty_company_reports_zeros_and_writes_nothing(
        conn, env):
    # aging-report validates no input, so there is no refusal path: even an
    # unknown company reports zeros instead of refusing. Pin that truthfully.
    _aged_charge(conn, env, 10, "100.00")
    before = _snapshot(conn, CHARGE_TABLES)
    company_id = seed_company(conn)

    for probe in (company_id, "no-such-company"):
        r = call_action(ACTIONS["health-aging-report"], conn,
                        ns(company_id=probe))
        assert is_ok(r), r
        assert (r["total_outstanding"], r["total_charges"]) == ("0.00", 0)
        assert r["details"] == {}
        assert all(bucket == {"count": 0, "total": "0.00"}
                   for bucket in r["buckets"].values())

    assert _snapshot(conn, CHARGE_TABLES) == before


# ---------------------------------------------------------------------------
# health-batch-submit-claims: submits drafts that carry claim lines
# ---------------------------------------------------------------------------

def _core_claim_with_line(conn, env):
    r = call_action(ACTIONS["health-add-patient-insurance"], conn, ns(
        patient_id=env["patient_id"], company_id=env["company_id"],
        insurance_type="primary", payer_name="Acme Health", payer_id=None,
        plan_name=None, plan_type=None, group_number=None, member_id="MEM-7",
        subscriber_name=None, subscriber_dob=None,
        subscriber_relationship=None, copay_amount=None, deductible=None,
        deductible_met=None, out_of_pocket_max=None,
        effective_date="2026-01-01", termination_date=None,
        preauth_required=None, status=None))
    assert is_ok(r), r
    insurance_id = r["id"]
    r = call_action(ACTIONS["health-add-claim"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        encounter_id=env["encounter_id"], insurance_id=insurance_id,
        claim_date="2026-03-20", total_charge="250.00"))
    assert is_ok(r), r
    claim_id = r["id"]
    charge_id = _charge(conn, env, "250.00", "1")
    r = call_action(ACTIONS["health-add-claim-line"], conn, ns(
        claim_id=claim_id, charge_id=charge_id, cpt_code="99213",
        line_number="1", modifiers=None, diagnosis_pointers="1", units="1",
        charge_amount="250.00", allowed_amount=None, paid_amount=None,
        adjustment_amount=None, patient_amount=None, denial_reason=None,
        remark_codes=None))
    assert is_ok(r), r
    return claim_id


def test_batch_submit_claims_submits_only_drafts_with_lines(conn, env):
    # BATCH-FINDING (deliberately not fixed): claims created by
    # health-adv-add-claim carry their charges as a charge_ids JSON array and
    # never gain healthclaw_claim_line rows, so health-batch-submit-claims
    # always files them under "No claim lines" and leaves them draft. The
    # assertions below pin that real behaviour.
    adv_charge = _charge(conn, env, "250.00", "1")
    adv_claim_id = _adv_claim(conn, env, [adv_charge])
    core_claim_id = _core_claim_with_line(conn, env)
    money_before = {
        cid: dict(conn.execute(
            "SELECT total_charged, total_allowed, total_paid FROM "
            "healthclaw_claim WHERE id = ?", (cid,)).fetchone())
        for cid in (adv_claim_id, core_claim_id)}
    assert money_before[adv_claim_id]["total_charged"] == "250.00"

    r = call_action(ACTIONS["health-batch-submit-claims"], conn,
                    ns(company_id=env["company_id"]))
    assert is_ok(r), r
    assert (r["submitted_count"], r["failed_count"]) == (1, 1)
    assert r["submitted_claim_ids"] == [core_claim_id]
    assert r["failures"] == [{"claim_id": adv_claim_id,
                              "reason": "No claim lines"}]

    status = {x["id"]: (x["claim_status"], x["submitted_date"])
              for x in conn.execute(
                  "SELECT id, claim_status, submitted_date "
                  "FROM healthclaw_claim").fetchall()}
    assert status[adv_claim_id][0] == "draft"
    assert status[core_claim_id][0] == "submitted"
    # BATCH-FINDING (deliberately not fixed): unlike health-adv-submit-claim,
    # the batch path never stamps submitted_date; both rows keep NULL.
    assert status[adv_claim_id][1] is None
    assert status[core_claim_id][1] is None
    # The batch moves status only: money columns are exactly what they were.
    for cid, totals in money_before.items():
        assert dict(conn.execute(
            "SELECT total_charged, total_allowed, total_paid FROM "
            "healthclaw_claim WHERE id = ?", (cid,)).fetchone()) == totals
    # Status flips, not ledger postings: no legs to balance.
    _ledger_is_empty(conn)


def test_batch_submit_claims_refusals_leave_the_db_identical(conn, env):
    claim_id = _core_claim_with_line(conn, env)
    before = _snapshot(conn, CLAIM_TABLES)

    r = call_action(ACTIONS["health-batch-submit-claims"], conn,
                    ns(company_id="no-such-company"))
    assert is_error(r)
    assert _msg(r) == "Company no-such-company not found"

    r = call_action(ACTIONS["health-batch-submit-claims"], conn,
                    ns(company_id=None))
    assert is_error(r)
    assert _msg(r) == "--company-id is required"

    assert _snapshot(conn, CLAIM_TABLES) == before
    assert conn.execute("SELECT claim_status FROM healthclaw_claim "
                        "WHERE id = ?", (claim_id,)).fetchone()[0] == "draft"
