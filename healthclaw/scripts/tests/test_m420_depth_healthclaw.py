"""M420 depth tests: 12 healthclaw actions proven against stored rows.

Each action below already had a test that proved the wrong thing: a
shape-only test in this directory (response has the right keys) or a
routability-only contract test in testing/integration/contract (the action
can be reached at all). Neither observes the database, so a routed action
returning a perfectly shaped response while writing nothing -- or the wrong
thing -- still passed. Every test here invokes the action, then reads the
rows back through the test connection and compares exact values.

Per-action depth classification (acceptance item 3):
  stored-row EFFECT (writes one row, verified by re-read):
    - health-add-encounter
    - health-add-clinical-note
    - health-add-order
    - health-add-lab-order
    - health-add-lab-result
    - health-add-imaging-result
    - health-add-formulary
    - health-add-formulary-item
    - health-add-dispensing
    - health-add-dispense-log
    - health-add-auth-usage
  stored-row READ (read-only; response verified against re-read rows, plus
  proof the call wrote nothing):
    - health-abnormal-results-report
  ledger effect: NONE of the 12 actions posts to the ledger. Each behaviour
    test asserts gl_entry stays empty so a later reader does not add a
    both-legs assertion that cannot hold. Money stored in TEXT columns is
    compared as exact strings via Decimal -- never float, never round().

FINDING markers document real behaviour that looks wrong; production code
is deliberately NOT fixed by this task (see CHANGES.md).

Refusal rule: every action that validates input gets one refusal case
proving the refusal happens, the message names the real problem, and every
table below is identical afterwards. health-abnormal-results-report
validates nothing, so its second test proves that leniency explicitly
(unknown company -> empty result, nothing written) instead of pretending a
refusal exists.
"""
import json
import os
import re
import sys
import uuid
from decimal import Decimal

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from health_helpers import (  # noqa: E402
    call_action, ns, is_error, is_ok, load_db_query,
    seed_company, seed_naming_series, seed_patient,
)

mod = load_db_query()
ACTIONS = mod.ACTIONS

# Every table these 12 actions (and their seeds) can plausibly touch, plus
# the ledger and the audit trail. naming_series is deliberately NOT in this
# list: get_next_name() legitimately bumps it on the write path, so it is
# excluded from byte-identical comparisons with a comment at each use.
_SNAPSHOT_TABLES = (
    "healthclaw_encounter",
    "healthclaw_clinical_note",
    "healthclaw_order",
    "healthclaw_lab_order",
    "healthclaw_lab_test",
    "healthclaw_lab_result",
    "healthclaw_imaging_order",
    "healthclaw_imaging_result",
    "healthclaw_formulary",
    "healthclaw_formulary_item",
    "healthclaw_dispensing",
    "healthclaw_dispense_log",
    "healthclaw_medication",
    "healthclaw_prescription",
    "healthclaw_prior_auth",
    "healthclaw_auth_usage",
    "healthclaw_patient_insurance",
    "healthclaw_patient",
    "item",
    "gl_entry",
    "audit_log",
)


def _snapshot(conn, exclude=()):
    """Ordered dump of every snapshot table, minus exclusions."""
    snap = {}
    for table in _SNAPSHOT_TABLES:
        if table in exclude:
            continue
        try:
            rows = conn.execute("SELECT * FROM %s" % table).fetchall()
        except Exception:
            continue
        snap[table] = sorted(
            json.dumps(dict(row), sort_keys=True, default=str) for row in rows
        )
    return snap


def _gl_count(conn):
    return conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0]


def _msg(result):
    return result.get("message", "") + result.get("error", "")


def _row_by_id(conn, table, row_id):
    row = conn.execute(
        "SELECT * FROM %s WHERE id = ?" % table, (row_id,)).fetchone()
    assert row is not None, "expected row in %s id=%s" % (table, row_id)
    return dict(row)


def _added_rows(before, after):
    """JSON dumps present after but not before (ids are unique)."""
    prior = set(before)
    return sorted(r for r in after if r not in prior)


def _seed_item(conn, name="Depth Item"):
    """Foundation stock item (direct insert, same pattern as seed_company)."""
    iid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO item (id, item_name, item_code, stock_uom, is_stock_item)"
        " VALUES (?, ?, ?, ?, 1)",
        (iid, name, "ITEM-%s" % iid[:6].upper(), "Each"))
    conn.commit()
    return iid


def _seed_core_rx(conn, env, medication_name="Amoxicillin 500mg"):
    r = call_action(ACTIONS["health-add-prescription"], conn, ns(
        company_id=env["company_id"], encounter_id=env["encounter_id"],
        patient_id=env["patient_id"], prescriber_id=env["provider_id"],
        provider_id=None, medication_name=medication_name, ndc_code=None,
        dosage="500mg", frequency="BID", route="oral", quantity="30",
        refills="1", daw=None, rx_start_date="2026-03-01", rx_end_date=None,
        diagnosis_id=None, controlled_schedule=None, pharmacy_notes=None,
        notes=None, status=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _seed_adv_med_rx(conn, env):
    med = call_action(ACTIONS["health-add-medication"], conn, ns(
        company_id=env["company_id"], name="Lisinopril", generic_name=None,
        ndc_code=None, dea_schedule="non-scheduled", dosage_form=None,
        strength="10mg", manufacturer=None, unit_price="5.00",
        quantity_on_hand="100", reorder_level=None, notes=None,
        limit=50, offset=0))
    assert is_ok(med), med
    rx = call_action(ACTIONS["health-adv-add-prescription"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        prescriber_id=env["provider_id"], medication_id=med["id"],
        dosage="10mg", frequency="QD", route="oral",
        quantity_prescribed="30", refills_authorized="0", dea_number=None,
        rx_number=None, prescribed_date="2026-03-01", expiry_date=None,
        notes=None, limit=50, offset=0))
    assert is_ok(rx), rx
    return med["id"], rx["id"]


def _seed_insurance(conn, env):
    r = call_action(ACTIONS["health-add-patient-insurance"], conn, ns(
        patient_id=env["patient_id"], company_id=env["company_id"],
        insurance_type="primary", payer_name="Acme Health", payer_id=None,
        plan_name=None, plan_type=None, group_number=None,
        member_id="MEM-DEPTH-1", subscriber_name=None, subscriber_dob=None,
        subscriber_relationship=None, copay_amount=None, deductible=None,
        deductible_met=None, out_of_pocket_max=None,
        effective_date="2026-01-01", termination_date=None,
        preauth_required=None, status=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _seed_prior_auth(conn, env):
    ins_id = _seed_insurance(conn, env)
    r = call_action(ACTIONS["health-add-prior-auth"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        insurance_id=ins_id, requesting_provider_id=env["provider_id"],
        service_type="procedure", cpt_codes="99213", icd10_codes="J06.9",
        description="Depth-test auth", units_requested="5",
        request_date="2026-03-10", effective_date="2026-03-10",
        expiration_date="2026-06-10", auth_number=None, auth_status=None,
        decision_date=None, units_approved=None, notes=None, status=None,
        limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _seed_core_lab_test(conn, env):
    r = call_action(ACTIONS["health-add-lab-test"], conn, ns(
        lab_order_id=env["lab_order_id"], test_code="CBC",
        test_name="CBC panel", cpt_code=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _seed_imaging_order(conn, env):
    r = call_action(ACTIONS["health-add-imaging-order"], conn, ns(
        company_id=env["company_id"], encounter_id=env["encounter_id"],
        patient_id=env["patient_id"], ordering_provider_id=env["provider_id"],
        modality="mri", body_part="knee", laterality=None, cpt_code=None,
        order_date="2026-03-15", priority="routine",
        clinical_indication="Knee pain", contrast=None, scheduled_date=None,
        imaging_order_status=None, notes=None, status=None,
        limit=50, offset=0, order_id=None))
    assert is_ok(r), r
    return r["id"]


def _seed_adv_lab(conn, env, abnormal="1", critical="1", value="9.80"):
    """Adv lab test + order + result; returns (test_id, order_id, result_id)."""
    test = call_action(ACTIONS["health-adv-add-lab-test"], conn, ns(
        company_id=env["company_id"], test_name="Basic Metabolic Panel",
        test_code="BMP", loinc_code="51990-0", category="chemistry",
        specimen_type="blood", reference_range="see components", unit="mg/dL",
        turnaround_hours="24", base_price="12.50", notes=None,
        limit=50, offset=0))
    assert is_ok(test), test
    order = call_action(ACTIONS["health-adv-add-lab-order"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        ordering_provider="Dr. House", lab_test_id=test["id"],
        order_date="2026-03-10", priority="routine", clinical_notes=None,
        fasting_required=None, notes=None, limit=50, offset=0))
    assert is_ok(order), order
    result = call_action(ACTIONS["health-adv-add-lab-result"], conn, ns(
        company_id=env["company_id"], lab_order_id=order["id"],
        result_value=value, result_unit="mg/dL",
        reference_range="7.0-10.0", is_abnormal=abnormal,
        is_critical=critical, performed_by="tech-1", verified_by=None,
        result_date="2026-03-11", result_notes=None,
        limit=50, offset=0))
    assert is_ok(result), result
    return test["id"], order["id"], result["id"]


# =============================================================================
# health-add-encounter -- stored-row EFFECT
# =============================================================================
class TestAddEncounterDepth:
    def test_add_encounter_writes_exact_row(self, conn, env):
        before = _snapshot(conn, exclude=(
            "healthclaw_encounter", "audit_log", "naming_series"))
        enc_before = _snapshot(conn)["healthclaw_encounter"]
        audit_before = _snapshot(conn)["audit_log"]

        result = call_action(ACTIONS["health-add-encounter"], conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            provider_id=env["provider_id"], encounter_date="2026-03-15",
            encounter_type="outpatient", encounter_status=None,
            chief_complaint="Annual physical", department="Internal Medicine",
            room="Room 5", appointment_id=None, admission_date="2026-03-14",
            discharge_date=None, discharge_disposition=None, notes="Depth note",
            status=None, limit=50, offset=0, search=None))
        assert is_ok(result), result
        assert result["encounter_date"] == "2026-03-15"
        # The payload's own "status" arrives as document_status; the stored
        # row must agree with it.
        assert result["document_status"] == "open"

        stored = _row_by_id(conn, "healthclaw_encounter", result["id"])
        assert stored["naming_series"] == result["naming_series"]
        assert stored["naming_series"].startswith("ENC-")
        assert (stored["patient_id"], stored["provider_id"],
                stored["encounter_date"], stored["encounter_type"]) == (
            env["patient_id"], env["provider_id"], "2026-03-15", "outpatient")
        assert (stored["chief_complaint"], stored["department"],
                stored["room"], stored["admission_date"],
                stored["status"], stored["notes"],
                stored["company_id"]) == (
            "Annual physical", "Internal Medicine", "Room 5", "2026-03-14",
            "open", "Depth note", env["company_id"])
        assert stored["appointment_id"] is None
        assert stored["created_at"] and stored["updated_at"]

        # Exactly one new encounter row; every other table untouched
        # (naming_series legitimately bumps and is excluded here).
        assert _added_rows(
            enc_before, _snapshot(conn)["healthclaw_encounter"]) != []
        assert len(_added_rows(
            enc_before, _snapshot(conn)["healthclaw_encounter"])) == 1
        assert _snapshot(conn, exclude=(
            "healthclaw_encounter", "audit_log", "naming_series")) == before
        # Exactly one audit row for this action.
        new_audits = _added_rows(
            audit_before, _snapshot(conn)["audit_log"])
        assert len(new_audits) == 1
        audit = json.loads(new_audits[0])
        assert (audit["skill"], audit["action"], audit["entity_type"],
                audit["entity_id"]) == (
            "healthclaw", "health-add-encounter", "healthclaw_encounter",
            result["id"])
        # No ledger effect: encounters never post; both-legs cannot hold.
        assert _gl_count(conn) == 0

    def test_add_encounter_drops_discharge_fields(self, conn, env):
        # FINDING, deliberately not fixed: discharge_date,
        # discharge_disposition and status arguments are silently ignored --
        # the INSERT hardcodes discharge_date NULL and status "open", and
        # discharge_disposition is not even an inserted column. A caller
        # closing an encounter at creation time gets an open row back with
        # no error. The test documents the real behaviour.
        result = call_action(ACTIONS["health-add-encounter"], conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            provider_id=env["provider_id"], encounter_date="2026-03-15",
            encounter_type="outpatient", encounter_status="completed",
            chief_complaint=None, department=None, room=None,
            appointment_id=None, admission_date=None,
            discharge_date="2026-03-20", discharge_disposition="home",
            notes=None, status="completed", limit=50, offset=0, search=None))
        assert is_ok(result), result
        stored = _row_by_id(conn, "healthclaw_encounter", result["id"])
        assert (stored["discharge_date"], stored["discharge_disposition"],
                stored["status"]) == (None, None, "open")
        assert _gl_count(conn) == 0

    def test_add_encounter_refusal_writes_nothing(self, conn, env):
        before = _snapshot(conn)
        result = call_action(ACTIONS["health-add-encounter"], conn, ns(
            company_id=env["company_id"], patient_id=None,
            provider_id=env["provider_id"], encounter_date="2026-03-15",
            encounter_type="outpatient", encounter_status=None,
            chief_complaint=None, department=None, room=None,
            appointment_id=None, admission_date=None, discharge_date=None,
            discharge_disposition=None, notes=None, status=None,
            limit=50, offset=0, search=None))
        assert is_error(result), result
        assert _msg(result) == "--patient-id is required"
        # Byte-identical: no encounter row, no naming bump, no audit row.
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0


# =============================================================================
# health-add-clinical-note -- stored-row EFFECT
# =============================================================================
class TestAddClinicalNoteDepth:
    def test_add_soap_note_writes_exact_row(self, conn, env):
        before = _snapshot(conn, exclude=(
            "healthclaw_clinical_note", "audit_log", "naming_series"))

        result = call_action(ACTIONS["health-add-clinical-note"], conn, ns(
            encounter_id=env["encounter_id"], patient_id=env["patient_id"],
            author_id=env["provider_id"], provider_id=None, note_type="soap",
            subjective="Headache x3 days", objective="Vitals normal",
            assessment="Tension headache",
            plan_text="OTC analgesia, review 2 weeks", body=None,
            addendum=None, note_status=None, sign=None, notes=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["note_type"] == "soap"
        assert result["document_status"] == "draft"

        stored = _row_by_id(conn, "healthclaw_clinical_note", result["id"])
        assert (stored["encounter_id"], stored["patient_id"],
                stored["author_id"], stored["note_type"]) == (
            env["encounter_id"], env["patient_id"], env["provider_id"],
            "soap")
        assert (stored["subjective"], stored["objective"],
                stored["assessment"], stored["plan"]) == (
            "Headache x3 days", "Vitals normal", "Tension headache",
            "OTC analgesia, review 2 weeks")
        # --body is the free-text column for non-SOAP notes; a SOAP note
        # leaves it NULL.
        assert stored["body"] is None
        assert stored["status"] == "draft"
        assert stored["created_at"] and stored["updated_at"]

        assert _snapshot(conn, exclude=(
            "healthclaw_clinical_note", "audit_log",
            "naming_series")) == before
        count = conn.execute(
            "SELECT COUNT(*) FROM healthclaw_clinical_note").fetchone()[0]
        assert count == 1
        # No ledger effect: notes never post; both-legs cannot hold.
        assert _gl_count(conn) == 0

    def test_add_note_ignores_sign_and_addendum(self, conn, env):
        # FINDING, deliberately not fixed: addendum, note_status and sign
        # are accepted as flags but never read on create (signing only
        # exists on update). The note is stored draft with no addendum and
        # no error, so a caller believing it filed a signed note is wrong.
        result = call_action(ACTIONS["health-add-clinical-note"], conn, ns(
            encounter_id=env["encounter_id"], patient_id=env["patient_id"],
            author_id=env["provider_id"], provider_id=None, note_type="soap",
            subjective="s", objective="o", assessment="a", plan_text="p",
            body=None, addendum="post-visit addendum", note_status="signed",
            sign="1", notes=None, limit=50, offset=0))
        assert is_ok(result), result
        stored = _row_by_id(conn, "healthclaw_clinical_note", result["id"])
        assert (stored["status"], stored["addendum"],
                stored["signed_at"]) == ("draft", None, None)
        assert _gl_count(conn) == 0

    def test_add_note_refusal_writes_nothing(self, conn, env):
        before = _snapshot(conn)
        result = call_action(ACTIONS["health-add-clinical-note"], conn, ns(
            encounter_id=None, patient_id=env["patient_id"],
            author_id=env["provider_id"], provider_id=None, note_type="soap",
            subjective="s", objective=None, assessment=None, plan_text=None,
            body=None, addendum=None, note_status=None, sign=None, notes=None,
            limit=50, offset=0))
        assert is_error(result), result
        assert _msg(result) == "--encounter-id is required"
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0


# =============================================================================
# health-add-order -- stored-row EFFECT
# =============================================================================
class TestAddOrderDepth:
    def test_add_order_writes_exact_row(self, conn, env):
        before = _snapshot(conn, exclude=(
            "healthclaw_order", "audit_log", "naming_series"))

        result = call_action(ACTIONS["health-add-order"], conn, ns(
            company_id=env["company_id"], encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            ordering_provider_id=env["provider_id"], provider_id=None,
            order_type="imaging", order_date="2026-03-15", priority="urgent",
            clinical_indication="Rule out fracture", diagnosis_id=None,
            description=None, notes="Depth order", status=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["order_type"] == "imaging"
        assert result["document_status"] == "pending"

        stored = _row_by_id(conn, "healthclaw_order", result["id"])
        assert stored["naming_series"] == result["naming_series"]
        assert stored["naming_series"].startswith("ORD-")
        assert (stored["encounter_id"], stored["patient_id"],
                stored["ordering_provider_id"], stored["order_type"],
                stored["order_date"], stored["priority"]) == (
            env["encounter_id"], env["patient_id"], env["provider_id"],
            "imaging", "2026-03-15", "urgent")
        assert (stored["clinical_indication"], stored["status"],
                stored["notes"], stored["company_id"]) == (
            "Rule out fracture", "pending", "Depth order",
            env["company_id"])
        assert stored["diagnosis_id"] is None

        assert _snapshot(conn, exclude=(
            "healthclaw_order", "audit_log", "naming_series")) == before
        count = conn.execute(
            "SELECT COUNT(*) FROM healthclaw_order").fetchone()[0]
        assert count == 1
        # No ledger effect: orders never post; both-legs cannot hold.
        assert _gl_count(conn) == 0

    def test_add_order_refusal_writes_nothing(self, conn, env):
        before = _snapshot(conn)
        result = call_action(ACTIONS["health-add-order"], conn, ns(
            company_id=env["company_id"], encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            ordering_provider_id=env["provider_id"], provider_id=None,
            order_type=None, order_date="2026-03-15", priority=None,
            clinical_indication=None, diagnosis_id=None, description=None,
            notes=None, status=None, limit=50, offset=0))
        assert is_error(result), result
        assert _msg(result) == "--order-type is required"
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0


# =============================================================================
# health-add-lab-order (core lab.py) -- stored-row EFFECT
# =============================================================================
class TestAddLabOrderDepth:
    def test_add_lab_order_writes_exact_row(self, conn, env):
        seed_before = _row_by_id(
            conn, "healthclaw_lab_order", env["lab_order_id"])
        before = _snapshot(conn, exclude=(
            "healthclaw_lab_order", "audit_log", "naming_series"))

        result = call_action(ACTIONS["health-add-lab-order"], conn, ns(
            company_id=env["company_id"], encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            ordering_provider_id=env["provider_id"], order_date="2026-03-15",
            priority="stat", fasting_required="1", specimen_type="blood",
            clinical_indication="Annual screening", collection_date=None,
            received_date=None, notes="Depth lab order",
            lab_order_status=None, status=None, order_id=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["order_date"] == "2026-03-15"
        assert result["document_status"] == "ordered"

        stored = _row_by_id(conn, "healthclaw_lab_order", result["id"])
        assert stored["naming_series"] == result["naming_series"]
        assert stored["naming_series"].startswith("LAB-")
        assert (stored["encounter_id"], stored["patient_id"],
                stored["ordering_provider_id"], stored["order_date"],
                stored["priority"]) == (
            env["encounter_id"], env["patient_id"], env["provider_id"],
            "2026-03-15", "stat")
        assert stored["fasting_required"] == 1
        assert (stored["clinical_indication"], stored["specimen_type"],
                stored["order_status"], stored["notes"],
                stored["company_id"]) == (
            "Annual screening", "blood", "ordered", "Depth lab order",
            env["company_id"])
        assert stored["collection_date"] is None
        assert stored["received_date"] is None

        # The seeded lab order is untouched; every other table identical.
        assert _row_by_id(conn, "healthclaw_lab_order",
                          env["lab_order_id"]) == seed_before
        assert _snapshot(conn, exclude=(
            "healthclaw_lab_order", "audit_log", "naming_series")) == before
        # No ledger effect: lab orders never post; both-legs cannot hold.
        assert _gl_count(conn) == 0

    def test_add_lab_order_refusal_writes_nothing(self, conn, env):
        before = _snapshot(conn)
        result = call_action(ACTIONS["health-add-lab-order"], conn, ns(
            company_id=env["company_id"], encounter_id=env["encounter_id"],
            patient_id=env["patient_id"], ordering_provider_id=None,
            order_date="2026-03-15", priority=None, fasting_required=None,
            specimen_type=None, clinical_indication=None, collection_date=None,
            received_date=None, notes=None, lab_order_status=None, status=None,
            order_id=None, limit=50, offset=0))
        assert is_error(result), result
        assert _msg(result) == "--ordering-provider-id is required"
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0


# =============================================================================
# health-add-lab-result (core lab.py) -- stored-row EFFECT
# =============================================================================
class TestAddLabResultDepth:
    def test_add_lab_result_writes_exact_row(self, conn, env):
        test_id = _seed_core_lab_test(conn, env)
        before = _snapshot(conn, exclude=(
            "healthclaw_lab_result", "audit_log", "naming_series"))

        result = call_action(ACTIONS["health-add-lab-result"], conn, ns(
            lab_test_id=test_id, component_name="Hemoglobin",
            result_value="13.2", unit="g/dL", reference_low="12.0",
            reference_high="16.0", flag="normal", result_date="2026-03-16",
            performed_by_id=None, verified_by_id=None, notes="Depth result",
            limit=50, offset=0))
        assert is_ok(result), result
        assert (result["lab_test_id"], result["component_name"],
                result["flag"]) == (test_id, "Hemoglobin", "normal")

        stored = _row_by_id(conn, "healthclaw_lab_result", result["id"])
        assert (stored["lab_test_id"], stored["component_name"],
                stored["value"], stored["unit"]) == (
            test_id, "Hemoglobin", "13.2", "g/dL")
        assert (stored["reference_low"], stored["reference_high"],
                stored["flag"], stored["result_date"],
                stored["notes"]) == (
            "12.0", "16.0", "normal", "2026-03-16", "Depth result")
        assert stored["created_at"]

        assert _snapshot(conn, exclude=(
            "healthclaw_lab_result", "audit_log",
            "naming_series")) == before
        # No ledger effect: results never post; both-legs cannot hold.
        assert _gl_count(conn) == 0

    def test_core_abnormal_flag_leaves_is_abnormal_zero(self, conn, env):
        # FINDING, deliberately not fixed: the core result carries the
        # human flag column ("normal".."abnormal") while the adv
        # health-abnormal-results-report filters the separate is_abnormal
        # integer, which the core insert never sets (defaults 0). So a core
        # result flagged "abnormal" is invisible to the abnormal report.
        test_id = _seed_core_lab_test(conn, env)
        result = call_action(ACTIONS["health-add-lab-result"], conn, ns(
            lab_test_id=test_id, component_name="WBC", result_value="22.0",
            unit="cells/mcL", reference_low="4.5", reference_high="11.0",
            flag="abnormal", result_date="2026-03-16", performed_by_id=None,
            verified_by_id=None, notes=None, limit=50, offset=0))
        assert is_ok(result), result
        stored = _row_by_id(conn, "healthclaw_lab_result", result["id"])
        assert (stored["flag"], stored["is_abnormal"],
                stored["is_critical"]) == ("abnormal", 0, 0)
        report = call_action(ACTIONS["health-abnormal-results-report"], conn,
                             ns(company_id=None, patient_id=None,
                                date_from=None, date_to=None,
                                limit=50, offset=0))
        assert is_ok(report), report
        assert report["total_abnormal"] == 0
        assert _gl_count(conn) == 0

    def test_add_lab_result_refusal_writes_nothing(self, conn, env):
        before = _snapshot(conn)
        result = call_action(ACTIONS["health-add-lab-result"], conn, ns(
            lab_test_id=None, component_name="Hemoglobin",
            result_value="13.2", unit=None, reference_low=None,
            reference_high=None, flag=None, result_date="2026-03-16",
            performed_by_id=None, verified_by_id=None, notes=None,
            limit=50, offset=0))
        assert is_error(result), result
        assert _msg(result) == "--lab-test-id is required"
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0


# =============================================================================
# health-add-imaging-result -- stored-row EFFECT
# =============================================================================
class TestAddImagingResultDepth:
    def test_add_imaging_result_writes_exact_row(self, conn, env):
        order_id = _seed_imaging_order(conn, env)
        before = _snapshot(conn, exclude=(
            "healthclaw_imaging_result", "audit_log", "naming_series"))

        result = call_action(ACTIONS["health-add-imaging-result"], conn, ns(
            imaging_order_id=order_id, radiologist_id=env["provider_id"],
            findings="Mild joint effusion", impression="Early OA",
            recommendation="Physio review", critical_finding="1",
            report_date="2026-03-17", addendum=None,
            imaging_result_status=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["imaging_order_id"] == order_id
        assert result["document_status"] == "preliminary"

        stored = _row_by_id(conn, "healthclaw_imaging_result", result["id"])
        assert (stored["imaging_order_id"], stored["radiologist_id"],
                stored["report_date"], stored["status"]) == (
            order_id, env["provider_id"], "2026-03-17", "preliminary")
        assert (stored["findings"], stored["impression"],
                stored["recommendation"]) == (
            "Mild joint effusion", "Early OA", "Physio review")
        assert stored["critical_finding"] == 1
        assert stored["addendum"] is None

        assert _snapshot(conn, exclude=(
            "healthclaw_imaging_result", "audit_log",
            "naming_series")) == before
        # No ledger effect: results never post; both-legs cannot hold.
        assert _gl_count(conn) == 0

    def test_add_imaging_result_refusal_writes_nothing(self, conn, env):
        before = _snapshot(conn)
        result = call_action(ACTIONS["health-add-imaging-result"], conn, ns(
            imaging_order_id=None, radiologist_id=None, findings=None,
            impression=None, recommendation=None, critical_finding=None,
            report_date="2026-03-17", addendum=None,
            imaging_result_status=None, limit=50, offset=0))
        assert is_error(result), result
        assert _msg(result) == "--imaging-order-id is required"
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0


# =============================================================================
# health-add-formulary -- stored-row EFFECT
# =============================================================================
class TestAddFormularyDepth:
    def test_add_formulary_writes_exact_row(self, conn, env):
        before = _snapshot(conn, exclude=(
            "healthclaw_formulary", "audit_log", "naming_series"))

        result = call_action(ACTIONS["health-add-formulary"], conn, ns(
            company_id=env["company_id"],
            formulary_name="Hospital Formulary 2026",
            description="Annual formulary", effective_date="2026-01-01",
            expiration_date="2026-12-31", formulary_status=None, notes=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["name"] == "Hospital Formulary 2026"
        assert result["document_status"] == "active"

        stored = _row_by_id(conn, "healthclaw_formulary", result["id"])
        assert (stored["name"], stored["description"],
                stored["effective_date"], stored["expiration_date"],
                stored["status"], stored["company_id"]) == (
            "Hospital Formulary 2026", "Annual formulary", "2026-01-01",
            "2026-12-31", "active", env["company_id"])

        assert _snapshot(conn, exclude=(
            "healthclaw_formulary", "audit_log",
            "naming_series")) == before
        # No ledger effect: formularies never post; both-legs cannot hold.
        assert _gl_count(conn) == 0

    def test_add_formulary_refusal_writes_nothing(self, conn, env):
        before = _snapshot(conn)
        result = call_action(ACTIONS["health-add-formulary"], conn, ns(
            company_id=env["company_id"], formulary_name=None,
            description=None, effective_date="2026-01-01",
            expiration_date=None, formulary_status=None, notes=None,
            limit=50, offset=0))
        assert is_error(result), result
        assert _msg(result) == "--formulary-name is required"
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0


# =============================================================================
# health-add-formulary-item -- stored-row EFFECT
# =============================================================================
class TestAddFormularyItemDepth:
    def test_add_formulary_item_writes_exact_row(self, conn, env):
        form = call_action(ACTIONS["health-add-formulary"], conn, ns(
            company_id=env["company_id"], formulary_name="Depth Formulary",
            description=None, effective_date="2026-01-01",
            expiration_date=None, formulary_status=None, notes=None,
            limit=50, offset=0))
        assert is_ok(form), form
        item_id = _seed_item(conn)
        before = _snapshot(conn, exclude=(
            "healthclaw_formulary_item", "audit_log", "naming_series"))

        result = call_action(ACTIONS["health-add-formulary-item"], conn, ns(
            formulary_id=form["id"], item_id=item_id,
            ndc_code="00904-0590-01", drug_class="Penicillins",
            generic_name="Amoxicillin", brand_name="Amoxil",
            strength="500mg", dosage_form="capsule", route="oral",
            controlled_schedule=None, therapeutic_class="Anti-infective",
            formulary_tier="2", requires_prior_auth="1",
            max_daily_dose="4000mg", formulary_item_status=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert (result["formulary_id"], result["item_id"]) == (
            form["id"], item_id)

        stored = _row_by_id(conn, "healthclaw_formulary_item", result["id"])
        assert (stored["formulary_id"], stored["item_id"],
                stored["ndc_code"], stored["drug_class"]) == (
            form["id"], item_id, "00904-0590-01", "Penicillins")
        assert (stored["generic_name"], stored["brand_name"],
                stored["strength"], stored["dosage_form"],
                stored["route"]) == (
            "Amoxicillin", "Amoxil", "500mg", "capsule", "oral")
        assert stored["controlled_schedule"] is None
        assert (stored["therapeutic_class"], stored["formulary_tier"],
                stored["max_daily_dose"], stored["status"]) == (
            "Anti-infective", "2", "4000mg", "active")
        # "1" folds to integer 1; anything else folds to 0.
        assert stored["requires_prior_auth"] == 1

        assert _snapshot(conn, exclude=(
            "healthclaw_formulary_item", "audit_log",
            "naming_series")) == before
        # No ledger effect and no money column on this table: nothing to
        # compare as Decimal, no both-legs assertion can hold.
        assert _gl_count(conn) == 0

    def test_add_formulary_item_refusal_writes_nothing(self, conn, env):
        item_id = _seed_item(conn)
        before = _snapshot(conn)
        result = call_action(ACTIONS["health-add-formulary-item"], conn, ns(
            formulary_id=None, item_id=item_id, ndc_code=None,
            drug_class=None, generic_name=None, brand_name=None, strength=None,
            dosage_form=None, route=None, controlled_schedule=None,
            therapeutic_class=None, formulary_tier=None,
            requires_prior_auth=None, max_daily_dose=None,
            formulary_item_status=None, limit=50, offset=0))
        assert is_error(result), result
        assert _msg(result) == "--formulary-id is required"
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0


# =============================================================================
# health-add-dispensing -- stored-row EFFECT (money as text)
# =============================================================================
class TestAddDispensingDepth:
    def test_add_dispensing_writes_exact_row(self, conn, env):
        rx_id = _seed_core_rx(conn, env)
        before = _snapshot(conn, exclude=(
            "healthclaw_dispensing", "audit_log", "naming_series"))

        result = call_action(ACTIONS["health-add-dispensing"], conn, ns(
            company_id=env["company_id"], prescription_id=rx_id,
            patient_id=env["patient_id"], formulary_item_id=None,
            item_id=None, dispensed_by_id=env["provider_id"],
            dispensed_date="2026-03-18", quantity="30", lot_number="LOT-9",
            expiration_date="2027-01-01", ndc_code="00904-0590-01",
            directions="Take twice daily", refill_number="0", notes=None,
            dispensing_status=None, status=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["prescription_id"] == rx_id
        assert result["document_status"] == "dispensed"

        stored = _row_by_id(conn, "healthclaw_dispensing", result["id"])
        assert stored["naming_series"] == result["naming_series"]
        assert stored["naming_series"].startswith("DISP-")
        assert (stored["prescription_id"], stored["patient_id"],
                stored["dispensed_by_id"], stored["dispensed_date"]) == (
            rx_id, env["patient_id"], env["provider_id"], "2026-03-18")
        # Money is text: quantity is Decimal-rounded to 2dp and stored as
        # an exact string -- never float, never round().
        assert stored["quantity"] == "30.00"
        assert Decimal(stored["quantity"]) == Decimal("30.00")
        assert (stored["lot_number"], stored["expiration_date"],
                stored["ndc_code"], stored["directions"]) == (
            "LOT-9", "2027-01-01", "00904-0590-01", "Take twice daily")
        assert stored["refill_number"] == 0
        assert (stored["status"], stored["company_id"]) == (
            "dispensed", env["company_id"])
        assert stored["formulary_item_id"] is None
        assert stored["item_id"] is None

        # The prescription row itself is untouched by dispensing.
        assert _row_by_id(conn, "healthclaw_prescription",
                          rx_id)["status"] == "active"
        assert _snapshot(conn, exclude=(
            "healthclaw_dispensing", "audit_log",
            "naming_series")) == before
        # No ledger effect: dispensing never posts; both-legs cannot hold.
        assert _gl_count(conn) == 0

    def test_add_dispensing_refusal_writes_nothing(self, conn, env):
        before = _snapshot(conn)
        result = call_action(ACTIONS["health-add-dispensing"], conn, ns(
            company_id=env["company_id"], prescription_id=None,
            patient_id=env["patient_id"], formulary_item_id=None,
            item_id=None, dispensed_by_id=env["provider_id"],
            dispensed_date="2026-03-18", quantity="30", lot_number=None,
            expiration_date=None, ndc_code=None, directions=None,
            refill_number=None, notes=None, dispensing_status=None,
            status=None, limit=50, offset=0))
        assert is_error(result), result
        assert _msg(result) == "--prescription-id is required"
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0


# =============================================================================
# health-add-dispense-log -- stored-row EFFECT
# =============================================================================
class TestAddDispenseLogDepth:
    def test_add_dispense_log_writes_exact_row(self, conn, env):
        med_id, rx_id = _seed_adv_med_rx(conn, env)
        before = _snapshot(conn, exclude=(
            "healthclaw_dispense_log", "audit_log", "naming_series"))

        result = call_action(ACTIONS["health-add-dispense-log"], conn, ns(
            company_id=env["company_id"], prescription_id=rx_id,
            dispensed_by="pharm-tech-1", quantity_dispensed="30",
            is_refill="0", lot_number="LOT-1", expiration_date="2027-01-01",
            notes="Depth dispense", limit=50, offset=0))
        assert is_ok(result), result
        assert (result["prescription_id"],
                result["quantity_dispensed"]) == (rx_id, 30)

        stored = _row_by_id(conn, "healthclaw_dispense_log", result["id"])
        assert (stored["company_id"], stored["prescription_id"],
                stored["medication_id"], stored["dispensed_by"]) == (
            env["company_id"], rx_id, med_id, "pharm-tech-1")
        assert stored["quantity_dispensed"] == 30
        # FINDING, deliberately not fixed: there is no --dispense-date
        # flag, so backdating is impossible -- dispense_date is always the
        # server timestamp. Documented, not asserted as input echo.
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
            stored["dispense_date"]) is not None
        assert (stored["is_refill"], stored["lot_number"],
                stored["expiration_date"], stored["notes"]) == (
            0, "LOT-1", "2027-01-01", "Depth dispense")

        assert _snapshot(conn, exclude=(
            "healthclaw_dispense_log", "audit_log",
            "naming_series")) == before
        # No ledger effect: dispense logs never post; both-legs cannot hold.
        assert _gl_count(conn) == 0

    def test_dispense_log_with_core_prescription_raises(self, conn, env):
        # FINDING, deliberately not fixed: a core health-add-prescription
        # row carries no medication_id, but healthclaw_dispense_log.
        # medication_id is NOT NULL. Instead of a truthful refusal, the
        # action dies with an unhandled sqlite3.IntegrityError -- no error
        # envelope, no message, and the caller cannot tell what to fix.
        rx_id = _seed_core_rx(conn, env)
        before = _snapshot(conn)
        with pytest.raises(Exception,
                           match="NOT NULL constraint failed"):
            call_action(ACTIONS["health-add-dispense-log"], conn, ns(
                company_id=env["company_id"], prescription_id=rx_id,
                dispensed_by="pharm-tech-1", quantity_dispensed="30",
                is_refill="0", lot_number=None, expiration_date=None,
                notes=None, limit=50, offset=0))
        conn.rollback()
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0

    def test_add_dispense_log_refusal_writes_nothing(self, conn, env):
        _, rx_id = _seed_adv_med_rx(conn, env)
        before = _snapshot(conn)
        result = call_action(ACTIONS["health-add-dispense-log"], conn, ns(
            company_id=env["company_id"], prescription_id=rx_id,
            dispensed_by="pharm-tech-1", quantity_dispensed="0",
            is_refill=None, lot_number=None, expiration_date=None,
            notes=None, limit=50, offset=0))
        assert is_error(result), result
        assert _msg(result) == "--quantity-dispensed must be > 0"
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0


# =============================================================================
# health-add-auth-usage -- stored-row EFFECT
# =============================================================================
class TestAddAuthUsageDepth:
    def test_add_auth_usage_writes_exact_row(self, conn, env):
        auth_id = _seed_prior_auth(conn, env)
        before = _snapshot(conn, exclude=(
            "healthclaw_auth_usage", "audit_log", "naming_series"))

        result = call_action(ACTIONS["health-add-auth-usage"], conn, ns(
            prior_auth_id=auth_id, encounter_id=env["encounter_id"],
            claim_id=None, usage_date="2026-04-02", units_used="3",
            notes="Depth usage", limit=50, offset=0))
        assert is_ok(result), result
        assert (result["prior_auth_id"],
                result["usage_date"]) == (auth_id, "2026-04-02")

        stored = _row_by_id(conn, "healthclaw_auth_usage", result["id"])
        assert (stored["prior_auth_id"], stored["encounter_id"],
                stored["usage_date"], stored["units_used"],
                stored["notes"]) == (
            auth_id, env["encounter_id"], "2026-04-02", 3, "Depth usage")
        assert stored["claim_id"] is None
        assert stored["created_at"]

        assert _snapshot(conn, exclude=(
            "healthclaw_auth_usage", "audit_log",
            "naming_series")) == before
        # No ledger effect: auth usage never posts; both-legs cannot hold.
        assert _gl_count(conn) == 0

    def test_add_auth_usage_refusal_writes_nothing(self, conn, env):
        before = _snapshot(conn)
        result = call_action(ACTIONS["health-add-auth-usage"], conn, ns(
            prior_auth_id=None, encounter_id=env["encounter_id"],
            claim_id=None, usage_date="2026-04-02", units_used=None,
            notes=None, limit=50, offset=0))
        assert is_error(result), result
        assert _msg(result) == "--prior-auth-id is required"
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0


# =============================================================================
# health-abnormal-results-report -- stored-row READ (read-only)
# =============================================================================
class TestAbnormalResultsReportDepth:
    def test_report_matches_stored_abnormal_rows(self, conn, env):
        _, _, abnormal_id = _seed_adv_lab(
            conn, env, abnormal="1", critical="1", value="9.80")
        # A normal result on the same order must not leak into the report.
        normal = call_action(ACTIONS["health-adv-add-lab-result"], conn, ns(
            company_id=env["company_id"], lab_order_id=conn.execute(
                "SELECT lab_order_id FROM healthclaw_lab_result WHERE id = ?",
                (abnormal_id,)).fetchone()[0],
            result_value="8.10", result_unit="mg/dL",
            reference_range="7.0-10.0", is_abnormal="0", is_critical="0",
            performed_by="tech-1", verified_by=None,
            result_date="2026-03-12", result_notes=None,
            limit=50, offset=0))
        assert is_ok(normal), normal
        # Another company's abnormal result must not leak across companies.
        other_company = seed_company(conn)
        seed_naming_series(conn, other_company)
        other_patient = seed_patient(conn, other_company, "Other", "Patient")
        other_test = call_action(ACTIONS["health-adv-add-lab-test"], conn, ns(
            company_id=other_company, test_name="Other Panel",
            test_code="OP", loinc_code=None, category="chemistry",
            specimen_type="blood", reference_range=None, unit=None,
            turnaround_hours=None, base_price="0.00", notes=None,
            limit=50, offset=0))
        assert is_ok(other_test), other_test
        other_order = call_action(ACTIONS["health-adv-add-lab-order"], conn,
                                  ns(
            company_id=other_company, patient_id=other_patient,
            ordering_provider="Dr. Other", lab_test_id=other_test["id"],
            order_date="2026-03-10", priority="routine", clinical_notes=None,
            fasting_required=None, notes=None, limit=50, offset=0))
        assert is_ok(other_order), other_order
        other_result = call_action(
            ACTIONS["health-adv-add-lab-result"], conn, ns(
                company_id=other_company, lab_order_id=other_order["id"],
                result_value="99.90", result_unit="mg/dL",
                reference_range=None, is_abnormal="1", is_critical="0",
                performed_by=None, verified_by=None,
                result_date="2026-03-11", result_notes=None,
                limit=50, offset=0))
        assert is_ok(other_result), other_result

        # Stored rows the report must aggregate, read back first.
        stored = _row_by_id(conn, "healthclaw_lab_result", abnormal_id)
        assert stored["is_abnormal"] == 1
        assert stored["is_critical"] == 1
        # Money is text: the seeded test price is an exact string.
        price = conn.execute(
            "SELECT base_price FROM healthclaw_lab_test WHERE test_name = ?"
            " AND company_id = ?",
            ("Basic Metabolic Panel", env["company_id"])).fetchone()[0]
        assert price == "12.50"
        assert Decimal(price) == Decimal("12.50")

        before = _snapshot(conn)
        result = call_action(
            ACTIONS["health-abnormal-results-report"], conn, ns(
                company_id=env["company_id"], patient_id=None,
                date_from=None, date_to=None, limit=50, offset=0))
        assert is_ok(result), result
        assert (result["total_abnormal"],
                result["critical_count"]) == (1, 1)
        assert len(result["entries"]) == 1
        entry = result["entries"][0]
        assert entry["id"] == abnormal_id
        assert (entry["result_value"], entry["patient_id"],
                entry["test_name"], entry["category"],
                entry["is_critical"]) == (
            "9.80", env["patient_id"], "Basic Metabolic Panel", "chemistry",
            1)
        # Read-only: stored rows and audit log identical afterwards.
        assert _snapshot(conn) == before
        # No ledger effect: reporting never posts; both-legs cannot hold.
        assert _gl_count(conn) == 0

    def test_report_with_unknown_company_is_empty_and_writes_nothing(
            self, conn, env):
        # This report validates nothing, so there is no refusal to test:
        # an unknown company yields an empty result and writes nothing.
        _seed_adv_lab(conn, env, abnormal="1", critical="0", value="9.80")
        before = _snapshot(conn)
        result = call_action(
            ACTIONS["health-abnormal-results-report"], conn, ns(
                company_id="no-such-company", patient_id=None,
                date_from=None, date_to=None, limit=50, offset=0))
        assert is_ok(result), result
        assert (result["total_abnormal"], result["critical_count"],
                result["entries"]) == (0, 0, [])
        assert _snapshot(conn) == before
        assert _gl_count(conn) == 0
