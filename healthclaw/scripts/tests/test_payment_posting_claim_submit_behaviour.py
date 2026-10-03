"""Payment postings and claim submission: the rows they write and the refusals.

Actions driven:
  - health-add-payment-posting      (billing.py add_payment_posting)
  - health-adv-add-payment-posting  (adv_billing.py add_payment_posting)
  - health-adv-submit-claim         (adv_billing.py submit_claim)
  - health-batch-submit-claims      (adv_reports_v2.py batch_submit_claims)

None of these handlers posts to the general ledger or the payment ledger;
each test that writes a posting also pins that no gl_entry or
payment_ledger_entry row appears.
"""
import json
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from health_helpers import (build_env, call_action, is_error, is_ok,  # noqa: E402
                            load_db_query, ns)

ACTIONS = load_db_query().ACTIONS

CLAIM_TOTALS = ("total_allowed", "total_paid", "total_adjustment",
                "patient_responsibility")


# ---------------------------------------------------------------------------
# Setup helpers (existing actions only)
# ---------------------------------------------------------------------------

def _insurance(conn, env):
    r = call_action(ACTIONS["health-add-patient-insurance"], conn, ns(
        patient_id=env["patient_id"], company_id=env["company_id"],
        insurance_type="primary", payer_name="Acme Health",
        payer_id=None, plan_name=None, plan_type=None, group_number=None,
        member_id="MEM-100", subscriber_name=None, subscriber_dob=None,
        subscriber_relationship=None, copay_amount=None, deductible=None,
        deductible_met=None, out_of_pocket_max=None,
        effective_date="2026-01-01", termination_date=None,
        preauth_required=None, status=None))
    assert is_ok(r), r
    return r["id"]


def _claim(conn, env, insurance_id):
    r = call_action(ACTIONS["health-add-claim"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        encounter_id=env["encounter_id"], insurance_id=insurance_id,
        claim_date="2026-03-20", total_charge="250.00"))
    assert is_ok(r), r
    return r["id"]


def _charge(conn, env, unit_fee="125.00", quantity="2"):
    r = call_action(ACTIONS["health-adv-add-charge"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], procedure_code_id=None,
        service_date="2026-03-15", cpt_code="99213", icd10_codes=None,
        description=None, quantity=quantity, unit_fee=unit_fee, notes=None))
    assert is_ok(r), r
    return r["id"]


def _claim_line(conn, claim_id, charge_id):
    r = call_action(ACTIONS["health-add-claim-line"], conn, ns(
        claim_id=claim_id, charge_id=charge_id, cpt_code="99213",
        line_number="1", modifiers=None, diagnosis_pointers="1", units="1",
        charge_amount="250.00", allowed_amount=None, paid_amount=None,
        adjustment_amount=None, patient_amount=None, denial_reason=None,
        remark_codes=None))
    assert is_ok(r), r
    return r["id"]


def _claim_row(conn, claim_id):
    return conn.execute(
        "SELECT claim_status, submitted_date, total_allowed, total_paid, "
        "total_adjustment, patient_responsibility FROM healthclaw_claim "
        "WHERE id = ?", (claim_id,)).fetchone()


def _totals(conn, claim_id):
    row = _claim_row(conn, claim_id)
    return tuple(row[c] for c in CLAIM_TOTALS)


def _posting_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM healthclaw_payment_posting").fetchone()[0]


def _no_ledger_rows(conn):
    assert conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM payment_ledger_entry").fetchone()[0] == 0


def _msg(r):
    return r.get("message", "") + r.get("error", "")


# ---------------------------------------------------------------------------
# health-add-payment-posting
# ---------------------------------------------------------------------------

def _core_posting(conn, env, claim_id, **over):
    kw = dict(company_id=env["company_id"], patient_id=env["patient_id"],
              posting_type="insurance_payment", posting_date="2026-04-01",
              amount="150.005", claim_id=claim_id, payment_entry_id=None,
              payment_method="check", check_number="CHK-7781",
              payer_name="Acme Health", eob_date="2026-03-30", notes=None)
    kw.update(over)
    return call_action(ACTIONS["health-add-payment-posting"], conn, ns(**kw))


def test_core_payment_posting_writes_the_rounded_amount(conn, env):
    claim_id = _claim(conn, env, _insurance(conn, env))
    r = _core_posting(conn, env, claim_id)
    assert is_ok(r), r
    assert r["amount"] == "150.01"
    row = conn.execute(
        "SELECT claim_id, patient_id, posting_type, posting_date, amount, "
        "check_number, payer_name, payment_method, eob_date, company_id "
        "FROM healthclaw_payment_posting WHERE id = ?", (r["id"],)).fetchone()
    assert dict(row) == {
        "claim_id": claim_id, "patient_id": env["patient_id"],
        "posting_type": "insurance_payment", "posting_date": "2026-04-01",
        "amount": "150.01", "check_number": "CHK-7781",
        "payer_name": "Acme Health", "payment_method": "check",
        "eob_date": "2026-03-30", "company_id": env["company_id"],
    }
    r2 = _core_posting(conn, env, claim_id, posting_type="patient_payment",
                       amount="25", payment_method="cash", check_number=None)
    assert is_ok(r2), r2
    amounts = sorted(x["amount"] for x in conn.execute(
        "SELECT amount FROM healthclaw_payment_posting WHERE claim_id = ?",
        (claim_id,)).fetchall())
    assert amounts == ["150.01", "25.00"]
    _no_ledger_rows(conn)


def test_core_payment_posting_refusals_write_nothing(conn, env):
    claim_id = _claim(conn, env, _insurance(conn, env))

    r = _core_posting(conn, env, claim_id, posting_type="bonus")
    assert is_error(r)
    assert _msg(r).startswith("Invalid health-posting-type: bonus.")

    r = _core_posting(conn, env, "no-such-claim")
    assert is_error(r)
    assert _msg(r) == "Claim no-such-claim not found"

    r = _core_posting(conn, env, claim_id, payment_entry_id="no-such-payment")
    assert is_error(r)
    assert _msg(r) == "Payment entry no-such-payment not found"

    r = _core_posting(conn, env, claim_id, payment_method="barter")
    assert is_error(r)
    assert _msg(r).startswith("Invalid health-payment-method: barter.")

    assert _posting_count(conn) == 0
    _no_ledger_rows(conn)


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


def test_adv_payment_posting_writes_row_and_accumulates_claim_totals(conn, env):
    claim_id = _claim(conn, env, _insurance(conn, env))
    charge_id = _charge(conn, env)
    assert _totals(conn, claim_id) == ("0.00", "0.00", "0.00", "0.00")

    r = _adv_posting(conn, env, claim_id, charge_id,
                     "200.00", "120.00", "50.00", "30.00")
    assert is_ok(r), r
    assert (r["paid_amount"], r["adjustment"]) == ("120.00", "50.00")
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
    assert _totals(conn, claim_id) == ("200.00", "120.00", "50.00", "30.00")

    r2 = _adv_posting(conn, env, claim_id, None,
                      "50.105", "30.10", "10.25", "9.755")
    assert is_ok(r2), r2
    row2 = conn.execute(
        "SELECT allowed_amount, paid_amount, adjustment, patient_responsibility "
        "FROM healthclaw_payment_posting WHERE id = ?", (r2["id"],)).fetchone()
    assert tuple(row2) == ("50.11", "30.10", "10.25", "9.76")
    assert _totals(conn, claim_id) == ("250.11", "150.10", "60.25", "39.76")
    assert _claim_row(conn, claim_id)["claim_status"] == "draft"
    _no_ledger_rows(conn)


def test_adv_payment_posting_refusals_leave_claim_totals_alone(conn, env):
    claim_id = _claim(conn, env, _insurance(conn, env))
    charge_id = _charge(conn, env)
    assert is_ok(_adv_posting(conn, env, claim_id, charge_id,
                              "100.00", "80.00", "20.00", "0.00"))
    before = _totals(conn, claim_id)
    assert before == ("100.00", "80.00", "20.00", "0.00")

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

    assert _posting_count(conn) == 1
    assert _totals(conn, claim_id) == before
    _no_ledger_rows(conn)


# ---------------------------------------------------------------------------
# health-adv-submit-claim
# ---------------------------------------------------------------------------

def _adv_submit(conn, claim_id):
    return call_action(ACTIONS["health-adv-submit-claim"], conn,
                       ns(claim_id=claim_id))


def test_adv_submit_claim_submits_and_bills_its_charges(conn, env):
    claim_id = _claim(conn, env, _insurance(conn, env))
    c1 = _charge(conn, env)
    c2 = _charge(conn, env, unit_fee="40.00", quantity="1")
    untouched = _charge(conn, env, unit_fee="10.00", quantity="1")
    conn.execute("UPDATE healthclaw_claim SET charge_ids = ? WHERE id = ?",
                 (json.dumps([c1, c2]), claim_id))
    conn.commit()

    r = _adv_submit(conn, claim_id)
    assert is_ok(r), r
    assert r["charges_billed"] == 2
    row = _claim_row(conn, claim_id)
    assert row["claim_status"] == "submitted"
    assert row["submitted_date"] == r["submitted_date"]
    assert len(row["submitted_date"]) == 20 and row["submitted_date"].endswith("Z")
    statuses = {x["id"]: (x["charge_status"], x["total_fee"]) for x in conn.execute(
        "SELECT id, charge_status, total_fee FROM healthclaw_charge").fetchall()}
    assert statuses == {c1: ("billed", "250.00"), c2: ("billed", "40.00"),
                        untouched: ("unbilled", "10.00")}
    _no_ledger_rows(conn)


def test_adv_submit_claim_resubmits_an_appealed_claim(conn, env):
    claim_id = _claim(conn, env, _insurance(conn, env))
    assert is_ok(_adv_submit(conn, claim_id))
    assert is_ok(call_action(ACTIONS["health-record-denial"], conn, ns(
        claim_id=claim_id, denial_category="CO", denial_code="CO-97",
        denial_reason="Bundled", denial_date="2026-04-10")))
    assert is_ok(call_action(ACTIONS["health-submit-appeal"], conn, ns(
        claim_id=claim_id, appeal_method="written", appeal_reference="APL-1",
        notes=None)))
    assert _claim_row(conn, claim_id)["claim_status"] == "appealed"

    r = _adv_submit(conn, claim_id)
    assert is_ok(r), r
    assert r["charges_billed"] == 0
    assert _claim_row(conn, claim_id)["claim_status"] == "submitted"


def test_adv_submit_claim_refuses_a_claim_that_is_not_draft_or_appealed(conn, env):
    claim_id = _claim(conn, env, _insurance(conn, env))
    charge_id = _charge(conn, env)
    assert is_ok(_adv_submit(conn, claim_id))
    first = dict(_claim_row(conn, claim_id))
    conn.execute("UPDATE healthclaw_claim SET charge_ids = ? WHERE id = ?",
                 (json.dumps([charge_id]), claim_id))
    conn.commit()

    r = _adv_submit(conn, claim_id)
    assert is_error(r)
    assert _msg(r) == ("Cannot submit claim with status: submitted. "
                       "Must be draft or appealed")
    assert dict(_claim_row(conn, claim_id)) == first
    assert conn.execute("SELECT charge_status FROM healthclaw_charge WHERE id = ?",
                        (charge_id,)).fetchone()[0] == "unbilled"

    r = _adv_submit(conn, "no-such-claim")
    assert is_error(r)
    assert _msg(r) == "Claim no-such-claim not found"


# ---------------------------------------------------------------------------
# health-batch-submit-claims
# ---------------------------------------------------------------------------

def test_batch_submit_claims_submits_drafts_with_lines_only(conn, env):
    ins = _insurance(conn, env)
    charge_id = _charge(conn, env)
    with_lines = _claim(conn, env, ins)
    _claim_line(conn, with_lines, charge_id)
    no_lines = _claim(conn, env, ins)
    already = _claim(conn, env, ins)
    _claim_line(conn, already, charge_id)
    assert is_ok(_adv_submit(conn, already))
    already_row = dict(_claim_row(conn, already))

    other = build_env(conn)
    other_claim = _claim(conn, other, _insurance(conn, other))
    _claim_line(conn, other_claim, _charge(conn, other))

    r = call_action(ACTIONS["health-batch-submit-claims"], conn,
                    ns(company_id=env["company_id"]))
    assert is_ok(r), r
    assert (r["submitted_count"], r["failed_count"]) == (1, 1)
    assert r["submitted_claim_ids"] == [with_lines]
    assert r["failures"] == [{"claim_id": no_lines, "reason": "No claim lines"}]

    status = {x["id"]: x["claim_status"] for x in conn.execute(
        "SELECT id, claim_status FROM healthclaw_claim").fetchall()}
    assert status == {with_lines: "submitted", no_lines: "draft",
                      already: "submitted", other_claim: "draft"}
    assert dict(_claim_row(conn, already)) == already_row
    _no_ledger_rows(conn)


def test_batch_submit_claims_refuses_an_unknown_company(conn, env):
    claim_id = _claim(conn, env, _insurance(conn, env))
    _claim_line(conn, claim_id, _charge(conn, env))

    r = call_action(ACTIONS["health-batch-submit-claims"], conn,
                    ns(company_id="no-such-company"))
    assert is_error(r)
    assert _msg(r) == "Company no-such-company not found"
    assert _claim_row(conn, claim_id)["claim_status"] == "draft"
