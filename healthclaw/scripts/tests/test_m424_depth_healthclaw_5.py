"""M424 depth: behavioural evidence for 12 health read actions.

Every action below already had a test that proved the wrong thing, and that
test was read before anything below was written:

- `health-get-medication`, `health-get-prescription`, `health-get-prior-auth`,
  `health-get-referral`, `health-lab-turnaround-report`,
  `health-list-auth-usages`, `health-list-claim-lines`,
  `health-list-dispense-logs`, `health-list-dispensings` had NO module test at
  all; they were covered only by box-facing routability contracts in
  `testing/integration/contract/test_healthclaw_contract.py`
  (e.g. `test_health_get_medication_exists`), which assert the kebab-case
  name resolves, never what the handler does to the database.
- `health-list-claims` had a shape-only module test
  (`TestClaim.test_list_claims` in `test_billing_inventory.py`): it asserts
  the response is ok on an empty database, never that a stored claim row is
  returned with exact values. (It also passes `claim_status=` / `claim_type=`
  kwargs the handler never reads -- the handler filters on `status` -- so it
  cannot prove filtering either. Left alone; out of scope.)
- `health-list-clinical-notes` had a shape-only module test
  (`TestClinicalNote.test_list_clinical_notes` in `test_clinical.py`): it
  asserts the response is ok, never that a stored note row is returned.
- `health-list-breach-incidents` had no list test at all (only add/update
  tests in `test_phase11.py`); it was covered only by its routability
  contract.

Each test below drives the action BY LITERAL KEBAB-CASE NAME through the
merged router registry (the same lookup `db_query.py` dispatches through),
seeds through the owning module's own write actions, and then reads the rows
back with a fresh `get_connection()` + PyPika (`erpclaw_lib.query`): the row
that should exist with exact values, the rows that must NOT have changed,
and what the response payload mirrors. Catalog questions (does the table
exist) go through `erpclaw_lib.seam`; there is no `sqlite_master`, no
`PRAGMA`, no `information_schema` below. Money compares exact `Decimal`
strings, never float, never approximate, never `round`.

Ledger scope, stated once so no later reader adds a balance assertion that
cannot hold: all 12 handlers are pure reads. None of them reaches the
general ledger, so no success test below asserts new ledger legs. Every
success test pins the full snapshot (including `audit_log` and `gl_entry`)
byte-identical across the call, which is the ledger non-effect proof.

Signal depth per action (all STORED ROW readback; none has a ledger effect):
- health-get-medication ..... STORED ROW (payload mirrors medication row)
- health-get-prescription ... STORED ROW (payload mirrors prescription row)
- health-get-referral ....... STORED ROW (payload mirrors referral row + names)
- health-get-prior-auth ..... STORED ROW (payload mirrors auth row + usage rollup)
- health-lab-turnaround-report  STORED ROWS (completed orders aggregate; open excluded)
- health-list-auth-usages .. STORED ROWS (usage rows for one auth; other auth excluded)
- health-list-breach-incidents  STORED ROWS (incident rows + risk filter)
- health-list-claim-lines ... STORED ROWS (line rows + money legs, ordered)
- health-list-claims ........ STORED ROWS (claim rows + money legs + status filter)
- health-list-clinical-notes  STORED ROWS (note rows + note_type filter)
- health-list-dispense-logs . STORED ROWS (log rows for one prescription)
- health-list-dispensings ... STORED ROWS (dispensing rows + money quantity)
"""
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(_HERE)
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
_LIB_DIR = os.path.join(_SRC_DIR, "erpclaw", "scripts", "erpclaw-setup", "lib")
if os.path.isdir(os.path.join(_LIB_DIR, "erpclaw_lib")) and _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from erpclaw_lib.db import get_connection
from erpclaw_lib.query import Q, P, Table, Field, fn
from erpclaw_lib import seam as _seam


def _load(name, directory):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(directory, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_helpers = _load("health_helpers", _HERE)
call_action = _helpers.call_action
is_ok = _helpers.is_ok
is_error = _helpers.is_error

H = _helpers.load_db_query().ACTIONS

SNAPSHOT_TABLES = (
    "company", "employee", "customer", "naming_series",
    "healthclaw_patient", "healthclaw_encounter",
    "healthclaw_patient_insurance",
    "healthclaw_medication", "healthclaw_prescription",
    "healthclaw_dispense_log", "healthclaw_controlled_substance_log",
    "healthclaw_referral", "healthclaw_prior_auth", "healthclaw_auth_usage",
    "healthclaw_breach_incident",
    "healthclaw_charge", "healthclaw_claim", "healthclaw_claim_line",
    "healthclaw_clinical_note", "healthclaw_dispensing",
    "healthclaw_lab_order", "healthclaw_lab_test", "healthclaw_lab_result",
    "audit_log", "gl_entry",
)


@pytest.fixture(scope="module")
def m424_template(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("m424tpl") / "template.sqlite")
    _helpers.init_all_tables(path)
    for name in SNAPSHOT_TABLES:
        assert _seam.table_exists(name, path), name
    return path


@pytest.fixture
def hconn(m424_template, tmp_path):
    dest = str(tmp_path / "case.sqlite")
    shutil.copyfile(m424_template, dest)
    conn = get_connection(dest)
    os.environ["ERPCLAW_DB_PATH"] = dest
    try:
        yield conn
    finally:
        conn.close()
        os.environ.pop("ERPCLAW_DB_PATH", None)


def _snapshot(conn):
    snap = {}
    for name in SNAPSHOT_TABLES:
        t = Table(name)
        rows = conn.execute(Q.from_(t).select("*").get_sql()).fetchall()
        snap[name] = sorted(repr(dict(r)) for r in rows)
    return snap


def _row(conn, table, row_id):
    t = Table(table)
    row = conn.execute(
        Q.from_(t).select("*").where(t.id == P()).get_sql(), (row_id,)).fetchone()
    return dict(row) if row is not None else None


def _count(conn, table):
    t = Table(table)
    return conn.execute(Q.from_(t).select(fn.Count("*")).get_sql()).fetchone()[0]


_DEFAULTS = dict(
    company_id=None, patient_id=None, encounter_id=None, provider_id=None,
    medication_id=None, prescription_id=None, referral_id=None,
    prior_auth_id=None, insurance_id=None, claim_id=None, charge_id=None,
    name=None, generic_name=None, ndc_code=None, dea_schedule=None,
    dosage_form=None, strength=None, manufacturer=None, unit_price=None,
    quantity_on_hand=None, reorder_level=None, notes=None, description=None,
    dosage=None, frequency=None, route=None, quantity_prescribed=None,
    refills_authorized=None, dea_number=None, prescribed_date=None,
    expiry_date=None, rx_number=None, prescriber_id=None, dispensed_by=None,
    quantity_dispensed=None, lot_number=None, expiration_date=None,
    is_refill=None, referring_provider_id=None, referred_to_provider=None,
    referred_to_specialty=None, referred_to_facility=None,
    referred_to_phone=None, referred_to_fax=None, referral_date=None,
    reason=None, diagnosis_id=None, priority=None, prior_auth_required=None,
    requesting_provider_id=None, service_type=None, cpt_codes=None,
    icd10_codes=None, units_requested=None, request_date=None,
    effective_date=None, usage_date=None, units_used=None,
    discovery_date=None, incident_date=None, phi_type=None,
    individuals_affected=None, risk_level=None, notification_required=None,
    remediation=None, claim_date=None, claim_type=None, total_charge=None,
    total_allowed=None, total_paid=None, patient_responsibility=None,
    adjustment_amount=None, place_of_service=None, filing_indicator=None,
    billing_provider_id=None, rendering_provider_id=None, cpt_code=None,
    charge_amount=None, service_date=None, line_number=None, modifiers=None,
    diagnosis_pointers=None, allowed_amount=None, paid_amount=None,
    patient_amount=None, denial_reason=None, remark_codes=None, author_id=None,
    note_type=None, subjective=None, objective=None, assessment=None,
    plan_text=None, body=None, addendum=None, note_status=None, sign=None,
    ordering_provider=None, lab_test_id=None, order_date=None, test_name=None,
    test_code=None, turnaround_hours=None, base_price=None, result_date=None,
    result_value=None, dispensed_by_id=None, dispensed_date=None, quantity=None,
    directions=None, refill_number=None, status=None, search=None,
    date_from=None, date_to=None, payer_name=None, member_id=None,
    limit=50, offset=0,
)


def _ns(**kw):
    d = dict(_DEFAULTS)
    d.update(kw)
    return _helpers.ns(**d)


def _base(conn):
    return _helpers.build_env(conn)


def _insurance(conn, env, payer="TestPayer", member="MEM-M424"):
    r = call_action(H["health-add-patient-insurance"], conn, _ns(
        patient_id=env["patient_id"], company_id=env["company_id"],
        insurance_type="primary", payer_name=payer, payer_id=None,
        plan_name=None, plan_type=None, group_number=None, member_id=member,
        subscriber_name=None, subscriber_dob=None,
        subscriber_relationship="self", copay_amount=None, deductible=None,
        deductible_met=None, out_of_pocket_max=None,
        effective_date="2026-01-01", termination_date=None,
        preauth_required=None, status=None))
    assert is_ok(r), r
    return r["id"]


def _medication(conn, env, name="Lisinopril 10mg", price="12.50", qoh=100):
    r = call_action(H["health-add-medication"], conn, _ns(
        company_id=env["company_id"], name=name, dea_schedule="non-scheduled",
        unit_price=price, quantity_on_hand=qoh, reorder_level=10,
        generic_name="Lisinopril", ndc_code=None, dosage_form="tablet",
        strength="10mg", manufacturer="Acme", notes=None))
    assert is_ok(r), r
    return r["id"]


def _prescription(conn, env, med_id, dosage="10mg", freq="once daily",
                  date="2026-03-15", qty=30, refills=1):
    r = call_action(H["health-adv-add-prescription"], conn, _ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        prescriber_id=env["provider_id"], medication_id=med_id,
        dosage=dosage, frequency=freq, prescribed_date=date,
        quantity_prescribed=qty, refills_authorized=refills,
        route="oral", rx_number=None, dea_number=None, expiry_date=None,
        notes=None))
    assert is_ok(r), r
    return r["id"]


def _referral(conn, env, to="Dr. Cardio", reason="Chest pain eval",
              date="2026-03-15", priority="urgent"):
    r = call_action(H["health-add-referral"], conn, _ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        encounter_id=env["encounter_id"],
        referring_provider_id=env["provider_id"],
        referred_to_provider=to, referred_to_specialty="Cardiology",
        referred_to_facility=None, referred_to_phone=None,
        referred_to_fax=None, referral_date=date, expiration_date=None,
        reason=reason, diagnosis_id=None, priority=priority,
        insurance_id=None, prior_auth_required=None, prior_auth_id=None,
        notes=None, referral_status=None, status=None))
    assert is_ok(r), r
    return r["id"]


def _prior_auth(conn, env, ins_id, service="procedure", cpt="99213",
                desc="Office visit pre-auth", units=2, date="2026-03-15"):
    r = call_action(H["health-add-prior-auth"], conn, _ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        insurance_id=ins_id, requesting_provider_id=env["provider_id"],
        auth_number=None, service_type=service, cpt_codes=cpt,
        icd10_codes="J06.9", description=desc, units_requested=units,
        request_date=date, effective_date=date, expiration_date="2026-06-15",
        notes=None, auth_status=None, status=None))
    assert is_ok(r), r
    return r["id"]


def _auth_usage(conn, auth_id, date="2026-04-01", units=2, notes="DOS visit"):
    r = call_action(H["health-add-auth-usage"], conn, _ns(
        prior_auth_id=auth_id, encounter_id=None, claim_id=None,
        usage_date=date, units_used=units, notes=notes))
    assert is_ok(r), r
    return r["id"]


def _breach(conn, env, discovery="2026-02-01", desc="Laptop left in taxi",
            risk="high", affected=25):
    r = call_action(H["health-add-breach-incident"], conn, _ns(
        company_id=env["company_id"], discovery_date=discovery,
        incident_date="2026-01-28", description=desc, phi_type="demographics",
        individuals_affected=affected, risk_level=risk,
        notification_required="1", remediation="Remote wipe issued",
        status=None))
    assert is_ok(r), r
    return r["id"]


def _charge(conn, env, cpt="99213", amount="150.00", date="2026-03-15"):
    r = call_action(H["health-add-charge"], conn, _ns(
        company_id=env["company_id"], encounter_id=env["encounter_id"],
        patient_id=env["patient_id"], provider_id=env["provider_id"],
        cpt_code=cpt, charge_amount=amount, service_date=date,
        procedure_id=None, fee_schedule_id=None, units="1", modifier=None,
        modifiers=None, diagnosis_ids=None, place_of_service="11",
        rendering_provider_id=None, charge_status=None, notes=None))
    assert is_ok(r), r
    return r["id"]


def _claim(conn, env, ins_id, date="2026-03-20", charge="250.00",
           allowed="200.00", paid="80.00", resp="20.00", adj="50.00"):
    r = call_action(H["health-add-claim"], conn, _ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        encounter_id=env["encounter_id"], insurance_id=ins_id,
        claim_type="professional", claim_date=date, total_charge=charge,
        total_allowed=allowed, total_paid=paid, patient_responsibility=resp,
        adjustment_amount=adj, billing_provider_id=env["provider_id"],
        rendering_provider_id=env["provider_id"], place_of_service="11",
        filing_indicator=None, prior_auth_id=None, sales_invoice_id=None,
        notes=None, claim_status=None))
    assert is_ok(r), r
    return r["id"]


def _claim_line(conn, claim_id, charge_id, line=1, cpt="99213",
                charge="150.00", allowed="120.00", paid="100.00",
                adj="20.00", pat="10.00"):
    r = call_action(H["health-add-claim-line"], conn, _ns(
        claim_id=claim_id, charge_id=charge_id, line_number=line,
        cpt_code=cpt, modifiers=None, diagnosis_pointers="1", units="1",
        charge_amount=charge, allowed_amount=allowed, paid_amount=paid,
        adjustment_amount=adj, patient_amount=pat, denial_reason=None,
        remark_codes=None))
    assert is_ok(r), r
    return r["id"]


def _note(conn, env, note_type="soap", subjective="Headache",
          body=None, plan="OTC relief"):
    r = call_action(H["health-add-clinical-note"], conn, _ns(
        encounter_id=env["encounter_id"], patient_id=env["patient_id"],
        author_id=env["provider_id"], note_type=note_type,
        subjective=subjective, objective="Vitals normal",
        assessment="Tension headache", plan_text=plan, body=body,
        addendum=None, note_status=None, sign=None, notes=None))
    assert is_ok(r), r
    return r["id"]


def _dispense_log(conn, env, rx_id, qty=30, by="Pharm Tech Jones"):
    r = call_action(H["health-add-dispense-log"], conn, _ns(
        company_id=env["company_id"], prescription_id=rx_id,
        dispensed_by=by, quantity_dispensed=qty, is_refill="0",
        lot_number="LOT-1", expiration_date=None, notes=None))
    assert is_ok(r), r
    return r["id"]


def _dispensing(conn, env, rx_id, date="2026-03-16", qty="30.00"):
    r = call_action(H["health-add-dispensing"], conn, _ns(
        company_id=env["company_id"], prescription_id=rx_id,
        patient_id=env["patient_id"], formulary_item_id=None, item_id=None,
        dispensed_by_id=env["provider_id"], dispensed_date=date,
        quantity=qty, lot_number="LOT-9", expiration_date=None,
        ndc_code=None, directions="Take once daily", refill_number="0",
        notes=None, status=None))
    assert is_ok(r), r
    return r["id"]


def _lab_test(conn, env, name="CBC Panel", code="CBC", turnaround=72,
               price="85.00"):
    r = call_action(H["health-adv-add-lab-test"], conn, _ns(
        company_id=env["company_id"], test_name=name, test_code=code,
        loinc_code=None, category="hematology", specimen_type="blood",
        reference_range=None, unit=None, turnaround_hours=turnaround,
        base_price=price, notes=None))
    assert is_ok(r), r
    return r["id"]


def _lab_order(conn, env, test_id, date):
    r = call_action(H["health-adv-add-lab-order"], conn, _ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        ordering_provider=env["provider_id"], lab_test_id=test_id,
        order_date=date, priority="routine", fasting_required=None,
        clinical_notes=None, notes=None))
    assert is_ok(r), r
    return r["id"]


def _lab_result(conn, env, order_id, date):
    r = call_action(H["health-adv-add-lab-result"], conn, _ns(
        company_id=env["company_id"], lab_order_id=order_id,
        result_date=date, result_value="5.2", result_unit="10^9/L",
        reference_range=None, is_abnormal=None, is_critical=None,
        performed_by=None, verified_by=None, result_notes=None))
    assert is_ok(r), r
    return r["id"]


# ---------------------------------------------------------------------------
# health-get-medication -- STORED ROW (read-only).
# No ledger effect: a pure SELECT that never touches journal/gl tables.
# ---------------------------------------------------------------------------
class TestGetMedicationDepth:
    def test_get_returns_the_stored_row_and_writes_nothing(self, hconn):
        env = _base(hconn)
        target = _medication(hconn, env, "Lisinopril 10mg", "12.50", 100)
        other = _medication(hconn, env, "Metformin 500mg", "8.25", 250)
        before = _snapshot(hconn)

        r = call_action(H["health-get-medication"], hconn,
                        _ns(medication_id=target))
        assert is_ok(r), r
        row = _row(hconn, "healthclaw_medication", target)
        assert row["name"] == "Lisinopril 10mg"
        assert row["unit_price"] == "12.50"
        assert Decimal(row["unit_price"]) == Decimal("12.50")
        assert row["quantity_on_hand"] == 100
        assert row["dea_schedule"] == "non-scheduled"
        assert row["company_id"] == env["company_id"]
        for key in ("id", "name", "generic_name", "dea_schedule",
                    "dosage_form", "strength", "manufacturer", "unit_price",
                    "quantity_on_hand", "company_id"):
            assert r[key] == row[key], key
        assert r["unit_price"] == "12.50"
        assert _row(hconn, "healthclaw_medication", other)["name"] == \
            "Metformin 500mg"
        assert _count(hconn, "healthclaw_medication") == 2
        assert _snapshot(hconn) == before

    def test_refuses_missing_and_unknown_id_and_writes_nothing(self, hconn):
        env = _base(hconn)
        target = _medication(hconn, env)
        before = _snapshot(hconn)

        r = call_action(H["health-get-medication"], hconn,
                        _ns(medication_id=None))
        assert is_error(r)
        assert r["message"] == "--medication-id is required"
        assert _snapshot(hconn) == before

        r = call_action(H["health-get-medication"], hconn,
                        _ns(medication_id="no-such-med"))
        assert is_error(r)
        assert r["message"] == "Medication no-such-med not found"
        assert _snapshot(hconn) == before
        assert _row(hconn, "healthclaw_medication", target)["name"] == \
            "Lisinopril 10mg"


# ---------------------------------------------------------------------------
# health-get-prescription -- STORED ROW (read-only).
# No ledger effect: a pure SELECT that never touches journal/gl tables.
# ---------------------------------------------------------------------------
class TestGetPrescriptionDepth:
    def test_get_returns_the_stored_row_and_writes_nothing(self, hconn):
        env = _base(hconn)
        med = _medication(hconn, env)
        target = _prescription(hconn, env, med)
        before = _snapshot(hconn)

        r = call_action(H["health-get-prescription"], hconn,
                        _ns(prescription_id=target))
        assert is_ok(r), r
        row = _row(hconn, "healthclaw_prescription", target)
        assert row["dosage"] == "10mg"
        assert row["frequency"] == "once daily"
        assert row["quantity_prescribed"] == 30
        assert row["refills_authorized"] == 1
        assert row["refills_used"] == 0
        assert row["rx_status"] == "active"
        assert row["route"] == "oral"
        assert row["prescribed_date"] == "2026-03-15"
        assert row["medication_id"] == med
        assert row["patient_id"] == env["patient_id"]
        for key in ("id", "dosage", "frequency", "route",
                    "quantity_prescribed", "refills_authorized",
                    "refills_used", "rx_status", "prescribed_date",
                    "medication_id", "patient_id", "company_id"):
            assert r[key] == row[key], key
        assert _snapshot(hconn) == before

    def test_refuses_missing_and_unknown_id_and_writes_nothing(self, hconn):
        env = _base(hconn)
        med = _medication(hconn, env)
        target = _prescription(hconn, env, med)
        before = _snapshot(hconn)

        r = call_action(H["health-get-prescription"], hconn,
                        _ns(prescription_id=None))
        assert is_error(r)
        assert r["message"] == "--prescription-id is required"
        assert _snapshot(hconn) == before

        r = call_action(H["health-get-prescription"], hconn,
                        _ns(prescription_id="no-such-rx"))
        assert is_error(r)
        assert r["message"] == "Prescription no-such-rx not found"
        assert _snapshot(hconn) == before
        assert _row(hconn, "healthclaw_prescription", target)["dosage"] == \
            "10mg"


# ---------------------------------------------------------------------------
# health-get-referral -- STORED ROW (read-only).
# No ledger effect: a pure SELECT (plus name enrichments) that never touches
# journal/gl tables. Note the envelope: the row's own `status` is surfaced
# as `document_status` by the response helper, so that is what is asserted.
# ---------------------------------------------------------------------------
class TestGetReferralDepth:
    def test_get_returns_the_stored_row_and_writes_nothing(self, hconn):
        env = _base(hconn)
        target = _referral(hconn, env)
        other = _referral(hconn, env, to="Dr. Derm", reason="Rash eval",
                          date="2026-03-20", priority="routine")
        before = _snapshot(hconn)

        r = call_action(H["health-get-referral"], hconn,
                        _ns(referral_id=target))
        assert is_ok(r), r
        row = _row(hconn, "healthclaw_referral", target)
        assert row["referred_to_provider"] == "Dr. Cardio"
        assert row["reason"] == "Chest pain eval"
        assert row["priority"] == "urgent"
        assert row["status"] == "pending"
        assert row["referral_date"] == "2026-03-15"
        assert row["patient_id"] == env["patient_id"]
        assert row["referring_provider_id"] == env["provider_id"]
        assert r["referred_to_provider"] == row["referred_to_provider"]
        assert r["reason"] == row["reason"]
        assert r["document_status"] == "pending"
        assert r["patient_name"] == "Jane Smith"
        assert r["referring_provider_name"] == "Dr. Test Provider"
        assert _row(hconn, "healthclaw_referral", other)[
            "referred_to_provider"] == "Dr. Derm"
        assert _snapshot(hconn) == before

    def test_refuses_missing_and_unknown_id_and_writes_nothing(self, hconn):
        env = _base(hconn)
        target = _referral(hconn, env)
        before = _snapshot(hconn)

        r = call_action(H["health-get-referral"], hconn,
                        _ns(referral_id=None))
        assert is_error(r)
        assert r["message"] == "--referral-id is required"
        assert _snapshot(hconn) == before

        r = call_action(H["health-get-referral"], hconn,
                        _ns(referral_id="no-such-ref"))
        assert is_error(r)
        assert r["message"] == "Referral no-such-ref not found"
        assert _snapshot(hconn) == before
        assert _row(hconn, "healthclaw_referral", target)[
            "referred_to_provider"] == "Dr. Cardio"


# ---------------------------------------------------------------------------
# health-get-prior-auth -- STORED ROW (read-only).
# No ledger effect: a pure SELECT (plus payer/provider names and a usage
# rollup) that never touches journal/gl tables. The row's own `status` is
# surfaced as `document_status` by the response helper.
# ---------------------------------------------------------------------------
class TestGetPriorAuthDepth:
    def test_get_returns_the_stored_row_and_usage_rollup(self, hconn):
        env = _base(hconn)
        ins = _insurance(hconn, env)
        target = _prior_auth(hconn, env, ins)
        before = _snapshot(hconn)

        r = call_action(H["health-get-prior-auth"], hconn,
                        _ns(prior_auth_id=target))
        assert is_ok(r), r
        row = _row(hconn, "healthclaw_prior_auth", target)
        assert row["service_type"] == "procedure"
        assert row["cpt_codes"] == "99213"
        assert row["description"] == "Office visit pre-auth"
        assert row["units_requested"] == 2
        assert row["units_approved"] is None
        assert row["status"] == "pending"
        assert row["request_date"] == "2026-03-15"
        assert r["service_type"] == row["service_type"]
        assert r["document_status"] == "pending"
        assert r["payer_name"] == "TestPayer"
        assert r["requesting_provider_name"] == "Dr. Test Provider"
        assert r["usage_count"] == 0
        assert r["total_units_used"] == 0
        assert _snapshot(hconn) == before

        use = _auth_usage(hconn, target, "2026-04-01", 2)
        assert _row(hconn, "healthclaw_auth_usage", use)["units_used"] == 2
        again = call_action(H["health-get-prior-auth"], hconn,
                            _ns(prior_auth_id=target))
        assert is_ok(again), again
        assert again["usage_count"] == 1
        assert again["total_units_used"] == 2
        assert again["document_status"] == "pending"

    def test_refuses_missing_and_unknown_id_and_writes_nothing(self, hconn):
        env = _base(hconn)
        ins = _insurance(hconn, env)
        target = _prior_auth(hconn, env, ins)
        before = _snapshot(hconn)

        r = call_action(H["health-get-prior-auth"], hconn,
                        _ns(prior_auth_id=None))
        assert is_error(r)
        assert r["message"] == "--prior-auth-id is required"
        assert _snapshot(hconn) == before

        r = call_action(H["health-get-prior-auth"], hconn,
                        _ns(prior_auth_id="no-such-auth"))
        assert is_error(r)
        assert r["message"] == "Prior auth no-such-auth not found"
        assert _snapshot(hconn) == before
        assert _row(hconn, "healthclaw_prior_auth", target)[
            "service_type"] == "procedure"


# ---------------------------------------------------------------------------
# health-lab-turnaround-report -- STORED ROWS (read-only aggregation).
# No ledger effect and no money in the payload: hours are compute, not
# currency. Money appears only on the joined lab_test row (`base_price`,
# asserted as an exact Decimal string via read-back). The open order proves
# the completed-only filter; the snapshot proves the report writes nothing.
# ---------------------------------------------------------------------------
class TestLabTurnaroundReportDepth:
    def test_completed_orders_aggregate_and_open_order_excluded(self, hconn):
        env = _base(hconn)
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        test_id = _lab_test(hconn, env)
        first = _lab_order(hconn, env, test_id, yesterday)
        second = _lab_order(hconn, env, test_id, today)
        opened = _lab_order(hconn, env, test_id, today)
        _lab_result(hconn, env, first, today)
        _lab_result(hconn, env, second, today)
        assert _row(hconn, "healthclaw_lab_order", opened)[
            "order_status"] == "ordered"
        before = _snapshot(hconn)

        r = call_action(H["health-lab-turnaround-report"], hconn, _ns(
            company_id=env["company_id"], date_from=None, date_to=None))
        assert is_ok(r), r
        assert r["total_completed"] == 2
        assert r["exceeded_target_count"] == 0
        assert r["on_target_rate"] == 100.0
        entries = r["entries"]
        assert [e["order_id"] for e in entries] == [second, first]
        for entry in entries:
            assert entry["test_name"] == "CBC Panel"
            assert entry["expected_hours"] == 72
            assert entry["met_target"] is True
            assert entry["actual_hours"] >= 0
            assert entry["actual_hours"] <= 72
        assert r["average_turnaround_hours"] == \
            round((entries[0]["actual_hours"] + entries[1]["actual_hours"])
                  / 2, 1)
        assert opened not in [e["order_id"] for e in entries]

        test_row = _row(hconn, "healthclaw_lab_test", test_id)
        assert test_row["base_price"] == "85.00"
        assert Decimal(test_row["base_price"]) == Decimal("85.00")
        assert _snapshot(hconn) == before

    def test_empty_window_reports_zeroes_and_writes_nothing(self, hconn):
        # This action validates no input, so there is no refusal path: an
        # out-of-range window is the truthful negative case (zeroes, not an
        # error) and must still write nothing.
        env = _base(hconn)
        test_id = _lab_test(hconn, env)
        order_id = _lab_order(hconn, env, test_id, "2026-03-15")
        _lab_result(hconn, env, order_id, "2026-03-16")
        before = _snapshot(hconn)

        r = call_action(H["health-lab-turnaround-report"], hconn, _ns(
            company_id=env["company_id"], date_from="2999-01-01",
            date_to=None))
        assert is_ok(r), r
        assert r["total_completed"] == 0
        assert r["average_turnaround_hours"] == 0.0
        assert r["exceeded_target_count"] == 0
        assert r["on_target_rate"] == 0.0
        assert r["entries"] == []
        assert _snapshot(hconn) == before


# ---------------------------------------------------------------------------
# health-list-auth-usages -- STORED ROWS (read-only).
# No ledger effect and no money: units are plain ints. This action validates
# no input, so an unknown filter id is the truthful negative case (empty,
# not an error) and must still write nothing.
# ---------------------------------------------------------------------------
class TestListAuthUsagesDepth:
    def test_list_returns_exact_usage_rows_and_writes_nothing(self, hconn):
        env = _base(hconn)
        ins = _insurance(hconn, env)
        auth_a = _prior_auth(hconn, env, ins)
        auth_b = _prior_auth(hconn, env, ins, desc="MRI pre-auth")
        first = _auth_usage(hconn, auth_a, "2026-04-01", 2)
        second = _auth_usage(hconn, auth_a, "2026-04-15", 1)
        elsewhere = _auth_usage(hconn, auth_b, "2026-04-10", 3)
        before = _snapshot(hconn)

        r = call_action(H["health-list-auth-usages"], hconn, _ns(
            prior_auth_id=auth_a, encounter_id=None, claim_id=None))
        assert is_ok(r), r
        assert r["total_count"] == 2
        assert r["has_more"] is False
        rows = r["rows"]
        assert [w["id"] for w in rows] == [second, first]
        assert rows[0]["units_used"] == 1
        assert rows[0]["usage_date"] == "2026-04-15"
        assert rows[1]["units_used"] == 2
        assert rows[1]["usage_date"] == "2026-04-01"
        for w in rows:
            assert w["prior_auth_id"] == auth_a
        assert elsewhere not in [w["id"] for w in rows]
        assert _row(hconn, "healthclaw_auth_usage", elsewhere)[
            "units_used"] == 3
        assert _snapshot(hconn) == before

    def test_unknown_auth_lists_empty_and_writes_nothing(self, hconn):
        env = _base(hconn)
        ins = _insurance(hconn, env)
        auth_a = _prior_auth(hconn, env, ins)
        use = _auth_usage(hconn, auth_a)
        before = _snapshot(hconn)

        r = call_action(H["health-list-auth-usages"], hconn, _ns(
            prior_auth_id="no-such-auth", encounter_id=None, claim_id=None))
        assert is_ok(r), r
        assert r["total_count"] == 0
        assert r["rows"] == []
        assert _snapshot(hconn) == before
        assert _row(hconn, "healthclaw_auth_usage", use)["units_used"] == 2


# ---------------------------------------------------------------------------
# health-list-breach-incidents -- STORED ROWS (read-only).
# No ledger effect and no money: affected counts are plain ints.
# ---------------------------------------------------------------------------
class TestListBreachIncidentsDepth:
    def test_list_returns_exact_incident_rows_and_writes_nothing(self, hconn):
        env = _base(hconn)
        first = _breach(hconn, env, "2026-02-01", "Laptop left in taxi",
                        "high", 25)
        second = _breach(hconn, env, "2026-03-01", "Misdirected fax",
                         "low", 3)
        before = _snapshot(hconn)

        r = call_action(H["health-list-breach-incidents"], hconn, _ns(
            company_id=env["company_id"], status=None, risk_level=None))
        assert is_ok(r), r
        assert r["total_count"] == 2
        rows = r["rows"]
        assert [w["id"] for w in rows] == [second, first]
        assert rows[0]["description"] == "Misdirected fax"
        assert rows[0]["risk_level"] == "low"
        assert rows[0]["individuals_affected"] == 3
        assert rows[0]["status"] == "investigating"
        assert rows[1]["individuals_affected"] == 25
        assert rows[1]["risk_level"] == "high"

        filtered = call_action(H["health-list-breach-incidents"], hconn,
                               _ns(company_id=env["company_id"], status=None,
                                    risk_level="high"))
        assert is_ok(filtered), filtered
        assert filtered["total_count"] == 1
        assert filtered["rows"][0]["id"] == first
        assert _row(hconn, "healthclaw_breach_incident", second)[
            "description"] == "Misdirected fax"
        assert _snapshot(hconn) == before

    def test_refuses_missing_and_unknown_company_and_writes_nothing(self,
                                                                    hconn):
        env = _base(hconn)
        target = _breach(hconn, env)
        before = _snapshot(hconn)

        r = call_action(H["health-list-breach-incidents"], hconn, _ns(
            company_id=None, status=None, risk_level=None))
        assert is_error(r)
        assert r["message"] == "--company-id is required"
        assert _snapshot(hconn) == before

        r = call_action(H["health-list-breach-incidents"], hconn, _ns(
            company_id="no-such-company", status=None, risk_level=None))
        assert is_error(r)
        assert r["message"] == "Company no-such-company not found"
        assert _snapshot(hconn) == before
        assert _row(hconn, "healthclaw_breach_incident", target)[
            "risk_level"] == "high"


# ---------------------------------------------------------------------------
# health-list-claim-lines -- STORED ROWS (read-only).
# No ledger effect. Money is text: all five amount legs compare as exact
# Decimal strings, never float.
# ---------------------------------------------------------------------------
class TestListClaimLinesDepth:
    def test_list_returns_exact_line_rows_and_writes_nothing(self, hconn):
        env = _base(hconn)
        ins = _insurance(hconn, env)
        claim_id = _claim(hconn, env, ins)
        charge_a = _charge(hconn, env, "99213", "150.00")
        charge_b = _charge(hconn, env, "99214", "75.50")
        first = _claim_line(hconn, claim_id, charge_a, 1, "99213", "150.00",
                            "120.00", "100.00", "20.00", "10.00")
        second = _claim_line(hconn, claim_id, charge_b, 2, "99214", "75.50",
                             "60.00", "0.00", "60.00", "0.00")
        before = _snapshot(hconn)

        r = call_action(H["health-list-claim-lines"], hconn, _ns(
            claim_id=claim_id, charge_id=None))
        assert is_ok(r), r
        assert r["total_count"] == 2
        assert r["has_more"] is False
        rows = r["rows"]
        assert [w["id"] for w in rows] == [first, second]
        assert rows[0]["cpt_code"] == "99213"
        assert rows[0]["charge_amount"] == "150.00"
        assert rows[0]["allowed_amount"] == "120.00"
        assert rows[0]["paid_amount"] == "100.00"
        assert rows[0]["adjustment_amount"] == "20.00"
        assert rows[0]["patient_amount"] == "10.00"
        for key, want in (("charge_amount", "150.00"),
                          ("allowed_amount", "120.00"),
                          ("paid_amount", "100.00"),
                          ("adjustment_amount", "20.00"),
                          ("patient_amount", "10.00")):
            assert Decimal(rows[0][key]) == Decimal(want), key
        assert rows[1]["charge_amount"] == "75.50"
        assert Decimal(rows[1]["charge_amount"]) == Decimal("75.50")
        assert _row(hconn, "healthclaw_claim_line", second)[
            "cpt_code"] == "99214"

        by_charge = call_action(H["health-list-claim-lines"], hconn, _ns(
            claim_id=None, charge_id=charge_b))
        assert is_ok(by_charge), by_charge
        assert by_charge["total_count"] == 1
        assert by_charge["rows"][0]["id"] == second
        assert _snapshot(hconn) == before

    def test_unknown_claim_lists_empty_and_writes_nothing(self, hconn):
        # This action validates no input, so an unknown filter id is the
        # truthful negative case (empty, not an error).
        env = _base(hconn)
        ins = _insurance(hconn, env)
        claim_id = _claim(hconn, env, ins)
        charge_id = _charge(hconn, env)
        line = _claim_line(hconn, claim_id, charge_id)
        before = _snapshot(hconn)

        r = call_action(H["health-list-claim-lines"], hconn, _ns(
            claim_id="no-such-claim", charge_id=None))
        assert is_ok(r), r
        assert r["total_count"] == 0
        assert r["rows"] == []
        assert _snapshot(hconn) == before
        assert _row(hconn, "healthclaw_claim_line", line)[
            "charge_amount"] == "150.00"


# ---------------------------------------------------------------------------
# health-list-claims -- STORED ROWS (read-only).
# No ledger effect. Money is text: all five total legs compare as exact
# Decimal strings, never float.
# ---------------------------------------------------------------------------
class TestListClaimsDepth:
    def test_list_returns_exact_claim_rows_and_writes_nothing(self, hconn):
        env = _base(hconn)
        ins = _insurance(hconn, env)
        first = _claim(hconn, env, ins, "2026-03-20", "250.00", "200.00",
                       "80.00", "20.00", "50.00")
        second = _claim(hconn, env, ins, "2026-03-21", "375.25", "300.00",
                        "0.00", "0.00", "0.00")
        before = _snapshot(hconn)

        r = call_action(H["health-list-claims"], hconn, _ns(
            company_id=env["company_id"], patient_id=None, status=None,
            insurance_id=None))
        assert is_ok(r), r
        assert r["total_count"] == 2
        rows = r["rows"]
        assert [w["id"] for w in rows] == [second, first]
        assert rows[1]["total_charge"] == "250.00"
        assert rows[1]["total_allowed"] == "200.00"
        assert rows[1]["total_paid"] == "80.00"
        assert rows[1]["patient_responsibility"] == "20.00"
        assert rows[1]["adjustment_amount"] == "50.00"
        assert rows[1]["claim_status"] == "draft"
        for key, want in (("total_charge", "250.00"),
                          ("total_allowed", "200.00"),
                          ("total_paid", "80.00"),
                          ("patient_responsibility", "20.00"),
                          ("adjustment_amount", "50.00")):
            assert Decimal(rows[1][key]) == Decimal(want), key
        assert rows[0]["total_charge"] == "375.25"
        assert Decimal(rows[0]["total_charge"]) == Decimal("375.25")

        drafts = call_action(H["health-list-claims"], hconn, _ns(
            company_id=env["company_id"], patient_id=None, status="draft",
            insurance_id=None))
        assert is_ok(drafts), drafts
        assert drafts["total_count"] == 2
        submitted = call_action(H["health-list-claims"], hconn, _ns(
            company_id=env["company_id"], patient_id=None,
            status="submitted", insurance_id=None))
        assert is_ok(submitted), submitted
        assert submitted["total_count"] == 0
        assert _row(hconn, "healthclaw_claim", first)[
            "total_charge"] == "250.00"
        assert _snapshot(hconn) == before

    def test_unknown_patient_lists_empty_and_writes_nothing(self, hconn):
        # This action validates no input, so an unknown filter id is the
        # truthful negative case (empty, not an error).
        env = _base(hconn)
        ins = _insurance(hconn, env)
        target = _claim(hconn, env, ins)
        before = _snapshot(hconn)

        r = call_action(H["health-list-claims"], hconn, _ns(
            company_id=env["company_id"], patient_id="no-such-patient",
            status=None, insurance_id=None))
        assert is_ok(r), r
        assert r["total_count"] == 0
        assert r["rows"] == []
        assert _snapshot(hconn) == before
        assert _row(hconn, "healthclaw_claim", target)[
            "total_charge"] == "250.00"


# ---------------------------------------------------------------------------
# health-list-clinical-notes -- STORED ROWS (read-only).
# No ledger effect and no money: notes carry no currency.
# ---------------------------------------------------------------------------
class TestListClinicalNotesDepth:
    def test_list_returns_exact_note_rows_and_writes_nothing(self, hconn):
        env = _base(hconn)
        soap = _note(hconn, env, "soap", "Headache")
        progress = _note(hconn, env, "progress", "Follow-up",
                         body="Improving steadily")
        before = _snapshot(hconn)

        r = call_action(H["health-list-clinical-notes"], hconn, _ns(
            encounter_id=env["encounter_id"], patient_id=None,
            note_type=None))
        assert is_ok(r), r
        assert r["total_count"] == 2
        by_id = {w["id"]: w for w in r["rows"]}
        assert set(by_id) == {soap, progress}
        assert by_id[soap]["note_type"] == "soap"
        assert by_id[soap]["subjective"] == "Headache"
        assert by_id[soap]["objective"] == "Vitals normal"
        assert by_id[soap]["assessment"] == "Tension headache"
        assert by_id[soap]["plan"] == "OTC relief"
        assert by_id[soap]["status"] == "draft"
        assert by_id[progress]["body"] == "Improving steadily"
        row = _row(hconn, "healthclaw_clinical_note", soap)
        assert row["subjective"] == "Headache"
        assert row["status"] == "draft"

        only_soap = call_action(H["health-list-clinical-notes"], hconn,
                                _ns(encounter_id=env["encounter_id"],
                                     patient_id=None, note_type="soap"))
        assert is_ok(only_soap), only_soap
        assert only_soap["total_count"] == 1
        assert only_soap["rows"][0]["id"] == soap
        assert _snapshot(hconn) == before

    def test_unknown_encounter_lists_empty_and_writes_nothing(self, hconn):
        # This action validates no input, so an unknown filter id is the
        # truthful negative case (empty, not an error).
        env = _base(hconn)
        target = _note(hconn, env)
        before = _snapshot(hconn)

        r = call_action(H["health-list-clinical-notes"], hconn, _ns(
            encounter_id="no-such-encounter", patient_id=None,
            note_type=None))
        assert is_ok(r), r
        assert r["total_count"] == 0
        assert r["rows"] == []
        assert _snapshot(hconn) == before
        assert _row(hconn, "healthclaw_clinical_note", target)[
            "subjective"] == "Headache"


# ---------------------------------------------------------------------------
# health-list-dispense-logs -- STORED ROWS (read-only).
# No ledger effect and no money: quantities are plain ints.
# ---------------------------------------------------------------------------
class TestListDispenseLogsDepth:
    def test_list_returns_exact_log_rows_and_writes_nothing(self, hconn):
        env = _base(hconn)
        med = _medication(hconn, env)
        other_med = _medication(hconn, env, "Metformin 500mg", "8.25", 250)
        rx = _prescription(hconn, env, med)
        other_rx = _prescription(hconn, env, other_med, qty=60)
        first = _dispense_log(hconn, env, rx, 30)
        second = _dispense_log(hconn, env, rx, 15, "Pharm Tech Lee")
        elsewhere = _dispense_log(hconn, env, other_rx, 60)
        before = _snapshot(hconn)

        r = call_action(H["health-list-dispense-logs"], hconn, _ns(
            company_id=env["company_id"], prescription_id=rx,
            medication_id=None))
        assert is_ok(r), r
        assert r["total_count"] == 2
        by_id = {w["id"]: w for w in r["rows"]}
        assert set(by_id) == {first, second}
        assert by_id[first]["quantity_dispensed"] == 30
        assert by_id[first]["dispensed_by"] == "Pharm Tech Jones"
        assert by_id[first]["medication_id"] == med
        assert by_id[first]["prescription_id"] == rx
        assert by_id[second]["quantity_dispensed"] == 15
        assert elsewhere not in by_id
        assert _row(hconn, "healthclaw_dispense_log", elsewhere)[
            "quantity_dispensed"] == 60

        by_med = call_action(H["health-list-dispense-logs"], hconn, _ns(
            company_id=env["company_id"], prescription_id=None,
            medication_id=other_med))
        assert is_ok(by_med), by_med
        assert by_med["total_count"] == 1
        assert by_med["rows"][0]["id"] == elsewhere
        assert _snapshot(hconn) == before

    def test_unknown_medication_lists_empty_and_writes_nothing(self, hconn):
        # This action validates no input, so an unknown filter id is the
        # truthful negative case (empty, not an error).
        env = _base(hconn)
        med = _medication(hconn, env)
        rx = _prescription(hconn, env, med)
        target = _dispense_log(hconn, env, rx)
        before = _snapshot(hconn)

        r = call_action(H["health-list-dispense-logs"], hconn, _ns(
            company_id=env["company_id"], prescription_id=None,
            medication_id="no-such-med"))
        assert is_ok(r), r
        assert r["total_count"] == 0
        assert r["rows"] == []
        assert _snapshot(hconn) == before
        assert _row(hconn, "healthclaw_dispense_log", target)[
            "quantity_dispensed"] == 30


# ---------------------------------------------------------------------------
# health-list-dispensings -- STORED ROWS (read-only).
# No ledger effect. Money is text: `quantity` is stored via currency
# rounding, so it compares as an exact Decimal string, never float.
# ---------------------------------------------------------------------------
class TestListDispensingsDepth:
    def test_list_returns_exact_dispensing_rows_and_writes_nothing(self,
                                                                   hconn):
        env = _base(hconn)
        med = _medication(hconn, env)
        rx_a = _prescription(hconn, env, med)
        rx_b = _prescription(hconn, env, med, qty=60)
        first = _dispensing(hconn, env, rx_a, "2026-03-16", "30.00")
        second = _dispensing(hconn, env, rx_b, "2026-03-17", "15.00")
        before = _snapshot(hconn)

        r = call_action(H["health-list-dispensings"], hconn, _ns(
            patient_id=env["patient_id"], prescription_id=None,
            status=None))
        assert is_ok(r), r
        assert r["total_count"] == 2
        rows = r["rows"]
        assert [w["id"] for w in rows] == [second, first]
        assert rows[1]["quantity"] == "30.00"
        assert Decimal(rows[1]["quantity"]) == Decimal("30.00")
        assert rows[1]["status"] == "dispensed"
        assert rows[1]["directions"] == "Take once daily"
        assert rows[1]["prescription_id"] == rx_a
        assert rows[0]["quantity"] == "15.00"
        assert Decimal(rows[0]["quantity"]) == Decimal("15.00")
        row = _row(hconn, "healthclaw_dispensing", first)
        assert row["quantity"] == "30.00"
        assert row["status"] == "dispensed"

        only_b = call_action(H["health-list-dispensings"], hconn, _ns(
            patient_id=None, prescription_id=rx_b, status=None))
        assert is_ok(only_b), only_b
        assert only_b["total_count"] == 1
        assert only_b["rows"][0]["id"] == second
        assert _snapshot(hconn) == before

    def test_unknown_patient_lists_empty_and_writes_nothing(self, hconn):
        # This action validates no input, so an unknown filter id is the
        # truthful negative case (empty, not an error).
        env = _base(hconn)
        med = _medication(hconn, env)
        rx = _prescription(hconn, env, med)
        target = _dispensing(hconn, env, rx)
        before = _snapshot(hconn)

        r = call_action(H["health-list-dispensings"], hconn, _ns(
            patient_id="no-such-patient", prescription_id=None,
            status=None))
        assert is_ok(r), r
        assert r["total_count"] == 0
        assert r["rows"] == []
        assert _snapshot(hconn) == before
        assert _row(hconn, "healthclaw_dispensing", target)[
            "quantity"] == "30.00"
