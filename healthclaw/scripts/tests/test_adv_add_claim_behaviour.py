"""Advanced claim creation: the claim row it writes and the refusals.

Action driven:
  - health-adv-add-claim  (adv_billing.py add_claim)

The handler writes one healthclaw_claim row in draft status. Its claim date
comes from --claim-date, which it requires, as health-add-claim does. It sums
the total_fee of the charges named in --charge-ids into total_charged. It
does not bill the charges and does not post to the general ledger.
"""
import json
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from health_helpers import call_action, is_error, is_ok, load_db_query, ns  # noqa: E402

ACTIONS = load_db_query().ACTIONS


def _charge(conn, env, unit_fee, quantity):
    r = call_action(ACTIONS["health-adv-add-charge"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], procedure_code_id=None,
        service_date="2026-03-15", cpt_code="99213", icd10_codes=None,
        description=None, quantity=quantity, unit_fee=unit_fee, notes=None))
    assert is_ok(r), r
    return r["id"]


def _adv_claim(conn, env, **over):
    kw = dict(company_id=env["company_id"], patient_id=env["patient_id"],
              payer_name="Acme Health", payer_id_number="ACME-EDI-01",
              policy_number="POL-5520", group_number="GRP-77",
              claim_number="EXT-9001", claim_date="2026-03-20",
              charge_ids=None, notes=None)
    kw.update(over)
    return call_action(ACTIONS["health-adv-add-claim"], conn, ns(**kw))


def _claim_count(conn):
    return conn.execute("SELECT COUNT(*) FROM healthclaw_claim").fetchone()[0]


def _msg(r):
    return r.get("message", "") + r.get("error", "")


def test_adv_add_claim_stores_claim_date_and_charge_total(conn, env):
    c1 = _charge(conn, env, "125.00", "2")
    c2 = _charge(conn, env, "40.00", "1")
    untouched = _charge(conn, env, "10.00", "1")

    r = _adv_claim(conn, env, charge_ids=json.dumps([c1, c2]))
    assert is_ok(r), r
    assert (r["total_charged"], r["claim_status"]) == ("290.00", "draft")

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
    stored_ids = conn.execute(
        "SELECT charge_ids FROM healthclaw_claim WHERE id = ?",
        (r["id"],)).fetchone()[0]
    assert json.loads(stored_ids) == [c1, c2]

    statuses = {x["id"]: (x["charge_status"], x["total_fee"]) for x in conn.execute(
        "SELECT id, charge_status, total_fee FROM healthclaw_charge").fetchall()}
    assert statuses == {c1: ("unbilled", "250.00"), c2: ("unbilled", "40.00"),
                        untouched: ("unbilled", "10.00")}
    assert conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0] == 0


def test_adv_add_claim_without_charges_totals_zero(conn, env):
    r = _adv_claim(conn, env, claim_date="2026-04-02", payer_id_number=None,
                   policy_number=None, group_number=None, claim_number=None)
    assert is_ok(r), r
    assert r["total_charged"] == "0.00"
    row = conn.execute(
        "SELECT claim_date, charge_ids, total_charged, claim_status "
        "FROM healthclaw_claim WHERE id = ?", (r["id"],)).fetchone()
    assert tuple(row) == ("2026-04-02", "[]", "0.00", "draft")
    assert _claim_count(conn) == 1


def test_adv_add_claim_refusals_write_nothing(conn, env):
    c1 = _charge(conn, env, "125.00", "2")

    r = _adv_claim(conn, env, claim_date=None, charge_ids=json.dumps([c1]))
    assert is_error(r)
    assert _msg(r) == "--claim-date is required"

    r = _adv_claim(conn, env, payer_name=None)
    assert is_error(r)
    assert _msg(r) == "--payer-name is required"

    r = _adv_claim(conn, env, patient_id=None)
    assert is_error(r)
    assert _msg(r) == "--patient-id is required"

    r = _adv_claim(conn, env, charge_ids="not-json")
    assert is_error(r)
    assert _msg(r) == "--charge-ids must be valid JSON array"

    assert _claim_count(conn) == 0
    assert conn.execute("SELECT charge_status FROM healthclaw_charge WHERE id = ?",
                        (c1,)).fetchone()[0] == "unbilled"
