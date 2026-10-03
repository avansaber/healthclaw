"""M426 depth: behavioural evidence for 12 shape-or-routing-only actions.

Prior state (read before writing anything below):
- `health-update-diagnosis` had a shape-only module test
  (`test_clinical.py::TestDiagnosis::test_update_diagnosis`): asserts the
  response is ok, never that the stored `healthclaw_diagnosis` row changed.
- `health-update-clinical-note` had a shape-only module test
  (`test_clinical.py::TestClinicalNote::test_update_clinical_note`): asserts
  ok only.
- `health-update-fee-schedule` had a shape-only module test
  (`test_billing_inventory.py::TestFeeSchedule::test_update_fee_schedule`):
  asserts ok only.
- `health-update-formulary` had a shape-only module test
  (`test_billing_inventory.py::TestFormulary::test_update_formulary`):
  asserts ok only.
- The other eight had NO module test at all; they were covered only by
  box-facing routability contracts
  (`testing/integration/contract/test_healthclaw_contract.py`, e.g.
  `test_health_refill_prescription_exists`) that assert the action name
  resolves, not what it does:
  `health-medication-inventory-report`, `health-payer-mix-report`,
  `health-refill-prescription`, `health-revenue-cycle-report`,
  `health-underpayment-report`, `health-update-formulary-item`,
  `health-update-imaging-order`, `health-update-imaging-result`.

Every test below observes the database through a fresh `get_connection()`
read-back built with PyPika (`erpclaw_lib.query`): the row that should exist
afterwards with exact values, the row that should have changed from what to
what, and what must NOT have changed. Catalog questions go through
`erpclaw_lib.seam`; there is no `sqlite_master`, no `PRAGMA` and no
`information_schema` below. Money compares exact `Decimal` strings, never
float, never approximate.

Ledger scope, stated once so no later reader adds a balance assertion that
cannot hold: none of these 12 handlers reaches the general ledger. The four
report actions are pure reads; the seven update actions and the refill write
only their own `healthclaw_*` tables (plus one `audit_log` line each). Every
per-action section repeats its own ledger note.

Signal depth per action (stored row unless noted):
- health-update-diagnosis: stored row (status/notes change, rest unchanged).
- health-update-clinical-note: stored row (body/addendum change).
- health-update-fee-schedule: stored row (description change).
- health-update-formulary: stored row (description change).
- health-update-formulary-item: stored row (brand/tier/dose change).
- health-update-imaging-order: stored row (priority/indication/date change).
- health-update-imaging-result: stored row (impression/recommendation/status).
- health-refill-prescription: stored row (prescription counters, medication
  quantity, new dispense-log row).
- health-medication-inventory-report: stored row aggregate (read-only; payload
  mirrors computed buckets, DB byte-identical).
- health-revenue-cycle-report: stored row aggregate (read-only).
- health-payer-mix-report: stored row aggregate (read-only).
- health-underpayment-report: stored row aggregate (read-only).
"""
import json
import os
import shutil
import sys
from decimal import Decimal

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from health_helpers import call_action, ns, is_ok, is_error, load_db_query
import health_helpers as HH

_LIB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(_TESTS_DIR))),
    "erpclaw", "scripts", "erpclaw-setup", "lib")
if os.path.isdir(os.path.join(_LIB_DIR, "erpclaw_lib")) and _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from erpclaw_lib.db import get_connection
from erpclaw_lib.query import Q, P, Table, Field, fn, insert_row
from erpclaw_lib import seam as _seam

mod = load_db_query()
ACTIONS = mod.ACTIONS

SNAPSHOT_TABLES = (
    "healthclaw_medication",
    "healthclaw_prescription",
    "healthclaw_dispense_log",
    "healthclaw_controlled_substance_log",
    "healthclaw_charge",
    "healthclaw_claim",
    "healthclaw_claim_line",
    "healthclaw_diagnosis",
    "healthclaw_clinical_note",
    "healthclaw_fee_schedule",
    "healthclaw_formulary",
    "healthclaw_formulary_item",
    "healthclaw_imaging_order",
    "healthclaw_imaging_result",
    "healthclaw_patient",
    "healthclaw_encounter",
    "item",
    "audit_log",
)


@pytest.fixture(scope="module")
def template_path(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("m426tpl") / "template.sqlite")
    HH.init_all_tables(path)
    for name in ("healthclaw_medication", "healthclaw_prescription",
                 "healthclaw_dispense_log", "healthclaw_charge",
                 "healthclaw_claim", "healthclaw_claim_line",
                 "healthclaw_diagnosis", "healthclaw_clinical_note",
                 "healthclaw_fee_schedule", "healthclaw_formulary",
                 "healthclaw_formulary_item", "healthclaw_imaging_order",
                 "healthclaw_imaging_result"):
        assert _seam.table_exists(name, path), name
    return path


@pytest.fixture
def fconn(template_path, tmp_path):
    dest = str(tmp_path / "case.sqlite")
    shutil.copyfile(template_path, dest)
    conn = get_connection(dest)
    os.environ["ERPCLAW_DB_PATH"] = dest
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass
        os.environ.pop("ERPCLAW_DB_PATH", None)


def _snapshot(conn, tables=SNAPSHOT_TABLES):
    snap = {}
    for name in tables:
        t = Table(name)
        rows = conn.execute(Q.from_(t).select("*").get_sql()).fetchall()
        snap[name] = sorted(repr(dict(r)) for r in rows)
    return snap


def _row(conn, table, row_id):
    t = Table(table)
    r = conn.execute(
        Q.from_(t).select("*").where(t.id == P()).get_sql(),
        (row_id,)).fetchone()
    return dict(r) if r is not None else None


def _count(conn, table):
    t = Table(table)
    return conn.execute(
        Q.from_(t).select(fn.Count("*")).get_sql()).fetchone()[0]


def _build_env(conn):
    cid = HH.seed_company(conn)
    prov = HH.seed_employee(conn, cid, "Dr. Test Provider")
    HH.seed_customer(conn, cid, "Health Customer")
    HH.seed_naming_series(conn, cid)
    pat = HH.seed_patient(conn, cid, "Jane", "Smith")
    enc = HH.seed_encounter(conn, cid, pat, prov)
    return {"company_id": cid, "provider_id": prov, "patient_id": pat,
            "encounter_id": enc}


def _add_dx(conn, env, code="J06.9", desc="Acute upper respiratory infection",
            dtype="primary"):
    r = call_action(ACTIONS["health-add-diagnosis"], conn, ns(
        encounter_id=env["encounter_id"], patient_id=env["patient_id"],
        icd10_code=code, dx_description=desc, diagnosis_type=dtype,
        dx_status=None, diagnosed_by_id=env["provider_id"], notes=None,
        limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _add_note(conn, env, body="Progress note body", ntype="progress"):
    r = call_action(ACTIONS["health-add-clinical-note"], conn, ns(
        encounter_id=env["encounter_id"], patient_id=env["patient_id"],
        author_id=env["provider_id"], note_type=ntype,
        subjective=None, objective=None, assessment=None, plan_text=None,
        body=body, addendum=None, note_status=None, sign=None, notes=None,
        limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _add_fee_schedule(conn, env, name="Update Test FS"):
    r = call_action(ACTIONS["health-add-fee-schedule"], conn, ns(
        company_id=env["company_id"], fee_schedule_name=name,
        description=None, effective_date="2026-01-01", expiration_date=None,
        fee_schedule_status=None, notes=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _add_formulary(conn, env, name="Update Test Formulary"):
    r = call_action(ACTIONS["health-add-formulary"], conn, ns(
        company_id=env["company_id"], formulary_name=name, description=None,
        effective_date="2026-01-01", expiration_date=None,
        formulary_status=None, notes=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _seed_item(conn, code="DRUG-001", name="Test Drug"):
    import uuid
    iid = str(uuid.uuid4())
    sql, _ = insert_row("item", {"id": P(), "item_code": P(),
                                 "item_name": P()})
    conn.execute(sql, (iid, code, name))
    conn.commit()
    return iid


def _add_formulary_item(conn, formulary_id, item_id):
    r = call_action(ACTIONS["health-add-formulary-item"], conn, ns(
        formulary_id=formulary_id, item_id=item_id,
        ndc_code="12345-6789-01", drug_class=None, generic_name=None,
        brand_name="BrandX", strength="500mg", dosage_form=None, route=None,
        controlled_schedule=None, therapeutic_class=None, formulary_tier="1",
        requires_prior_auth=None, max_daily_dose="40", limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _add_imaging_order(conn, env, modality="xray", body_part="Chest",
                       priority="routine", indication="Cough evaluation"):
    r = call_action(ACTIONS["health-add-imaging-order"], conn, ns(
        company_id=env["company_id"], encounter_id=env["encounter_id"],
        patient_id=env["patient_id"],
        ordering_provider_id=env["provider_id"], modality=modality,
        body_part=body_part, laterality=None, contrast=None,
        order_date="2026-03-15", priority=priority,
        clinical_indication=indication, scheduled_date=None, notes=None,
        imaging_order_status=None, status=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _add_imaging_result(conn, order_id):
    r = call_action(ACTIONS["health-add-imaging-result"], conn, ns(
        imaging_order_id=order_id, report_date="2026-03-16",
        radiologist_id=None, findings="No acute abnormality",
        impression="Normal chest", recommendation=None,
        critical_finding=None, addendum=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _add_med(conn, cid, name, price, qty, reorder=0, dea=None):
    r = call_action(ACTIONS["health-add-medication"], conn, ns(
        company_id=cid, name=name, dea_schedule=dea, unit_price=price,
        quantity_on_hand=str(qty), reorder_level=str(reorder),
        generic_name=None, ndc_code=None, dosage_form=None, strength=None,
        manufacturer=None, notes=None, limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


def _add_adv_rx(conn, env, med_id, qty="30", refills="3"):
    r = call_action(ACTIONS["health-adv-add-prescription"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        prescriber_id=env["provider_id"], medication_id=med_id,
        dosage="500mg", frequency="BID", prescribed_date="2026-03-01",
        quantity_prescribed=qty, refills_authorized=refills, route=None,
        rx_number=None, dea_number=None, expiry_date=None, notes=None,
        limit=50, offset=0))
    assert is_ok(r), r
    return r["id"]


# ---------------------------------------------------------------------------
# health-update-diagnosis -- stored row.
# No ledger effect: writes only healthclaw_diagnosis plus one audit_log line.
# ---------------------------------------------------------------------------
class TestUpdateDiagnosis:
    def test_status_and_notes_change_rest_of_row_unchanged(self, fconn):
        env = _build_env(fconn)
        dx1 = _add_dx(fconn, env)
        dx2 = _add_dx(fconn, env, code="I10", desc="Hypertension")
        before1 = _row(fconn, "healthclaw_diagnosis", dx1)
        before2 = _row(fconn, "healthclaw_diagnosis", dx2)
        assert before1["status"] == "active"
        assert before1["notes"] is None

        r = call_action(ACTIONS["health-update-diagnosis"], fconn, ns(
            diagnosis_id=dx1, icd10_code=None, dx_description=None,
            diagnosis_type=None, dx_status="resolved", onset_date=None,
            notes="Resolved with treatment", limit=50, offset=0))
        assert is_ok(r), r
        assert r["updated_fields"] == ["status", "notes"]

        after1 = _row(fconn, "healthclaw_diagnosis", dx1)
        assert after1["status"] == "resolved"
        assert after1["notes"] == "Resolved with treatment"
        assert after1["icd10_code"] == before1["icd10_code"] == "J06.9"
        assert after1["diagnosis_type"] == before1["diagnosis_type"] == "primary"
        assert after1["description"] == before1["description"]
        assert _row(fconn, "healthclaw_diagnosis", dx2) == before2

    def test_unknown_id_refused_and_writes_nothing(self, fconn):
        _build_env(fconn)
        before = _snapshot(fconn)
        r = call_action(ACTIONS["health-update-diagnosis"], fconn, ns(
            diagnosis_id="no-such-dx", icd10_code=None, dx_description=None,
            diagnosis_type=None, dx_status="resolved", onset_date=None,
            notes=None, limit=50, offset=0))
        assert is_error(r)
        assert r["message"] == "Diagnosis no-such-dx not found"
        assert _snapshot(fconn) == before


# ---------------------------------------------------------------------------
# health-update-clinical-note -- stored row.
# No ledger effect: writes only healthclaw_clinical_note plus one audit line.
# ---------------------------------------------------------------------------
class TestUpdateClinicalNote:
    def test_body_and_addendum_change_rest_of_row_unchanged(self, fconn):
        env = _build_env(fconn)
        n1 = _add_note(fconn, env, body="Progress note body")
        n2 = _add_note(fconn, env, body="Sibling note body")
        before2 = _row(fconn, "healthclaw_clinical_note", n2)

        r = call_action(ACTIONS["health-update-clinical-note"], fconn, ns(
            note_id=n1, note_type=None, subjective=None, objective=None,
            assessment=None, plan_text=None, body="Updated body",
            addendum="Addendum text", note_status=None, sign=None, notes=None,
            limit=50, offset=0))
        assert is_ok(r), r
        assert r["updated_fields"] == ["body", "addendum"]

        after1 = _row(fconn, "healthclaw_clinical_note", n1)
        assert after1["body"] == "Updated body"
        assert after1["addendum"] == "Addendum text"
        assert after1["note_type"] == "progress"
        assert after1["status"] == "draft"
        assert _row(fconn, "healthclaw_clinical_note", n2) == before2

    def test_unknown_id_refused_and_writes_nothing(self, fconn):
        _build_env(fconn)
        before = _snapshot(fconn)
        r = call_action(ACTIONS["health-update-clinical-note"], fconn, ns(
            note_id="no-such-note", note_type=None, subjective=None,
            objective=None, assessment=None, plan_text=None,
            body="Updated body", addendum=None, note_status=None, sign=None,
            notes=None, limit=50, offset=0))
        assert is_error(r)
        assert r["message"] == "Clinical note no-such-note not found"
        assert _snapshot(fconn) == before


# ---------------------------------------------------------------------------
# health-update-fee-schedule -- stored row.
# No ledger effect: writes only healthclaw_fee_schedule plus one audit line.
# ---------------------------------------------------------------------------
class TestUpdateFeeSchedule:
    def test_description_changes_rest_of_row_unchanged(self, fconn):
        env = _build_env(fconn)
        fs1 = _add_fee_schedule(fconn, env, name="Update Test FS")
        fs2 = _add_fee_schedule(fconn, env, name="Sibling FS")
        before2 = _row(fconn, "healthclaw_fee_schedule", fs2)

        r = call_action(ACTIONS["health-update-fee-schedule"], fconn, ns(
            fee_schedule_id=fs1, fee_schedule_name=None,
            description="Updated description", fee_schedule_status=None,
            effective_date=None, expiration_date=None, notes=None,
            limit=50, offset=0))
        assert is_ok(r), r
        assert r["updated_fields"] == ["description"]

        after1 = _row(fconn, "healthclaw_fee_schedule", fs1)
        assert after1["description"] == "Updated description"
        assert after1["name"] == "Update Test FS"
        assert after1["status"] == "active"
        assert _row(fconn, "healthclaw_fee_schedule", fs2) == before2

    def test_unknown_id_refused_and_writes_nothing(self, fconn):
        _build_env(fconn)
        before = _snapshot(fconn)
        r = call_action(ACTIONS["health-update-fee-schedule"], fconn, ns(
            fee_schedule_id="no-such-fs", fee_schedule_name=None,
            description="Updated description", fee_schedule_status=None,
            effective_date=None, expiration_date=None, notes=None,
            limit=50, offset=0))
        assert is_error(r)
        assert r["message"] == "Fee schedule no-such-fs not found"
        assert _snapshot(fconn) == before


# ---------------------------------------------------------------------------
# health-update-formulary -- stored row.
# No ledger effect: writes only healthclaw_formulary plus one audit line.
# ---------------------------------------------------------------------------
class TestUpdateFormulary:
    def test_description_changes_rest_of_row_unchanged(self, fconn):
        env = _build_env(fconn)
        f1 = _add_formulary(fconn, env, name="Update Test Formulary")
        f2 = _add_formulary(fconn, env, name="Sibling Formulary")
        before2 = _row(fconn, "healthclaw_formulary", f2)

        r = call_action(ACTIONS["health-update-formulary"], fconn, ns(
            formulary_id=f1, formulary_name=None, description="Updated",
            formulary_status=None, effective_date=None, expiration_date=None,
            notes=None, limit=50, offset=0))
        assert is_ok(r), r
        assert r["updated_fields"] == ["description"]

        after1 = _row(fconn, "healthclaw_formulary", f1)
        assert after1["description"] == "Updated"
        assert after1["name"] == "Update Test Formulary"
        assert after1["status"] == "active"
        assert _row(fconn, "healthclaw_formulary", f2) == before2

    def test_unknown_id_refused_and_writes_nothing(self, fconn):
        _build_env(fconn)
        before = _snapshot(fconn)
        r = call_action(ACTIONS["health-update-formulary"], fconn, ns(
            formulary_id="no-such-formulary", formulary_name=None,
            description="Updated", formulary_status=None, effective_date=None,
            expiration_date=None, notes=None, limit=50, offset=0))
        assert is_error(r)
        assert r["message"] == "Formulary no-such-formulary not found"
        assert _snapshot(fconn) == before


# ---------------------------------------------------------------------------
# health-update-formulary-item -- stored row.
# No ledger effect: writes only healthclaw_formulary_item plus one audit line.
# ---------------------------------------------------------------------------
class TestUpdateFormularyItem:
    def test_brand_tier_and_dose_change_rest_of_row_unchanged(self, fconn):
        env = _build_env(fconn)
        fid = _add_formulary(fconn, env)
        iid = _seed_item(fconn)
        fi = _add_formulary_item(fconn, fid, iid)
        before = _row(fconn, "healthclaw_formulary_item", fi)
        assert before["brand_name"] == "BrandX"
        assert before["formulary_tier"] == "1"
        assert before["max_daily_dose"] == "40"
        assert before["requires_prior_auth"] == 0
        assert before["status"] == "active"

        r = call_action(ACTIONS["health-update-formulary-item"], fconn, ns(
            formulary_item_id=fi, ndc_code=None, drug_class=None,
            generic_name=None, brand_name="BrandY", strength=None,
            dosage_form=None, route=None, controlled_schedule=None,
            therapeutic_class=None, formulary_tier="2",
            requires_prior_auth=None, max_daily_dose="80",
            formulary_item_status=None, limit=50, offset=0))
        assert is_ok(r), r
        assert r["updated_fields"] == ["brand_name", "max_daily_dose",
                                       "formulary_tier"]

        after = _row(fconn, "healthclaw_formulary_item", fi)
        assert after["brand_name"] == "BrandY"
        assert after["formulary_tier"] == "2"
        assert after["max_daily_dose"] == "80"
        assert after["ndc_code"] == before["ndc_code"] == "12345-6789-01"
        assert after["strength"] == before["strength"] == "500mg"
        assert after["requires_prior_auth"] == 0
        assert after["status"] == "active"

    def test_unknown_id_refused_and_writes_nothing(self, fconn):
        _build_env(fconn)
        before = _snapshot(fconn)
        r = call_action(ACTIONS["health-update-formulary-item"], fconn, ns(
            formulary_item_id="no-such-item", ndc_code=None, drug_class=None,
            generic_name=None, brand_name="BrandY", strength=None,
            dosage_form=None, route=None, controlled_schedule=None,
            therapeutic_class=None, formulary_tier=None,
            requires_prior_auth=None, max_daily_dose=None,
            formulary_item_status=None, limit=50, offset=0))
        assert is_error(r)
        assert r["message"] == "Formulary item no-such-item not found"
        assert _snapshot(fconn) == before


# ---------------------------------------------------------------------------
# health-update-imaging-order -- stored row.
# No ledger effect: writes only healthclaw_imaging_order plus one audit line.
# ---------------------------------------------------------------------------
class TestUpdateImagingOrder:
    def test_priority_indication_and_date_change_rest_unchanged(self, fconn):
        env = _build_env(fconn)
        o1 = _add_imaging_order(fconn, env)
        o2 = _add_imaging_order(fconn, env, modality="ct",
                                body_part="Abdomen", priority="urgent",
                                indication="Abdominal pain")
        before2 = _row(fconn, "healthclaw_imaging_order", o2)

        r = call_action(ACTIONS["health-update-imaging-order"], fconn, ns(
            imaging_order_id=o1, body_part=None, cpt_code=None,
            clinical_indication="Worsening cough",
            scheduled_date="2026-03-22", notes=None, modality=None,
            laterality=None, priority="urgent", imaging_order_status=None,
            contrast=None, limit=50, offset=0))
        assert is_ok(r), r
        assert r["updated_fields"] == ["clinical_indication",
                                       "scheduled_date", "priority"]

        after1 = _row(fconn, "healthclaw_imaging_order", o1)
        assert after1["priority"] == "urgent"
        assert after1["clinical_indication"] == "Worsening cough"
        assert after1["scheduled_date"] == "2026-03-22"
        assert after1["modality"] == "xray"
        assert after1["body_part"] == "Chest"
        assert after1["status"] == "ordered"
        assert _row(fconn, "healthclaw_imaging_order", o2) == before2

    def test_unknown_id_refused_and_writes_nothing(self, fconn):
        _build_env(fconn)
        before = _snapshot(fconn)
        r = call_action(ACTIONS["health-update-imaging-order"], fconn, ns(
            imaging_order_id="no-such-order", body_part=None, cpt_code=None,
            clinical_indication=None, scheduled_date=None, notes=None,
            modality=None, laterality=None, priority="urgent",
            imaging_order_status=None, contrast=None, limit=50, offset=0))
        assert is_error(r)
        assert r["message"] == "Imaging order no-such-order not found"
        assert _snapshot(fconn) == before


# ---------------------------------------------------------------------------
# health-update-imaging-result -- stored row.
# No ledger effect: writes only healthclaw_imaging_result plus one audit line.
# ---------------------------------------------------------------------------
class TestUpdateImagingResult:
    def test_impression_recommendation_status_change_rest_unchanged(self, fconn):
        env = _build_env(fconn)
        order = _add_imaging_order(fconn, env)
        ir = _add_imaging_result(fconn, order)
        before = _row(fconn, "healthclaw_imaging_result", ir)
        assert before["status"] == "preliminary"

        r = call_action(ACTIONS["health-update-imaging-result"], fconn, ns(
            imaging_result_id=ir, findings=None,
            impression="Mild infiltrate",
            recommendation="Follow-up in 2 weeks", addendum=None,
            report_date=None, imaging_result_status="final",
            radiologist_id=None, critical_finding=None, limit=50, offset=0))
        assert is_ok(r), r
        assert r["updated_fields"] == ["impression", "recommendation",
                                       "status"]

        after = _row(fconn, "healthclaw_imaging_result", ir)
        assert after["impression"] == "Mild infiltrate"
        assert after["recommendation"] == "Follow-up in 2 weeks"
        assert after["status"] == "final"
        assert after["findings"] == before["findings"] == "No acute abnormality"
        assert after["report_date"] == before["report_date"] == "2026-03-16"
        assert after["critical_finding"] == 0

    def test_unknown_id_refused_and_writes_nothing(self, fconn):
        _build_env(fconn)
        before = _snapshot(fconn)
        r = call_action(ACTIONS["health-update-imaging-result"], fconn, ns(
            imaging_result_id="no-such-result", findings=None,
            impression="Mild infiltrate", recommendation=None, addendum=None,
            report_date=None, imaging_result_status=None, radiologist_id=None,
            critical_finding=None, limit=50, offset=0))
        assert is_error(r)
        assert r["message"] == "Imaging result no-such-result not found"
        assert _snapshot(fconn) == before


# ---------------------------------------------------------------------------
# health-refill-prescription -- stored row (prescription counters, medication
# quantity, new dispense-log row).
# No ledger effect: no journal/gl write; inventory and dispense log only.
# ---------------------------------------------------------------------------
class TestRefillPrescription:
    def test_refill_bumps_counter_deducts_stock_writes_dispense_log(self, fconn):
        env = _build_env(fconn)
        med = _add_med(fconn, env["company_id"], "Amoxicillin", "5.00", 100,
                       reorder=10)
        sib = _add_med(fconn, env["company_id"], "Paracetamol", "10.00", 50)
        rx = _add_adv_rx(fconn, env, med, qty="30", refills="3")
        before_med = _row(fconn, "healthclaw_medication", med)
        before_sib = _row(fconn, "healthclaw_medication", sib)
        assert _count(fconn, "healthclaw_dispense_log") == 0

        r = call_action(ACTIONS["health-refill-prescription"], fconn, ns(
            prescription_id=rx, dispensed_by="Pharm Tech",
            quantity_dispensed="30", lot_number=None, expiration_date=None,
            witness=None, notes=None, limit=50, offset=0))
        assert is_ok(r), r
        assert r["refill_number"] == 1
        assert r["refills_remaining"] == 2
        assert r["rx_status"] == "active"

        rx_row = _row(fconn, "healthclaw_prescription", rx)
        assert rx_row["refills_used"] == 1
        assert rx_row["rx_status"] == "active"
        assert rx_row["quantity_prescribed"] == 30

        med_row = _row(fconn, "healthclaw_medication", med)
        assert med_row["quantity_on_hand"] == 70
        assert med_row["unit_price"] == "5.00"
        assert Decimal(med_row["unit_price"]) == Decimal("5.00")
        assert (Decimal(med_row["unit_price"])
                * Decimal(med_row["quantity_on_hand"])) == Decimal("350.00")

        t = Table("healthclaw_dispense_log")
        logs = [dict(x) for x in fconn.execute(
            Q.from_(t).select("*").where(t.prescription_id == P()).get_sql(),
            (rx,)).fetchall()]
        assert len(logs) == 1
        assert logs[0]["quantity_dispensed"] == 30
        assert logs[0]["is_refill"] == 1
        assert logs[0]["medication_id"] == med
        assert _row(fconn, "healthclaw_medication", sib) == before_sib
        assert before_med["quantity_on_hand"] == 100

    def test_no_refills_remaining_refused_and_writes_nothing(self, fconn):
        env = _build_env(fconn)
        med = _add_med(fconn, env["company_id"], "Amoxicillin", "5.00", 100)
        rx = _add_adv_rx(fconn, env, med, qty="30", refills="0")
        before = _snapshot(fconn)
        disp_before = _count(fconn, "healthclaw_dispense_log")

        r = call_action(ACTIONS["health-refill-prescription"], fconn, ns(
            prescription_id=rx, dispensed_by="Pharm Tech",
            quantity_dispensed="30", lot_number=None, expiration_date=None,
            witness=None, notes=None, limit=50, offset=0))
        assert is_error(r)
        assert r["message"] == "No refills remaining (used 0 of 0)"
        assert _snapshot(fconn) == before
        assert _count(fconn, "healthclaw_dispense_log") == disp_before
        assert _row(fconn, "healthclaw_medication", med)["quantity_on_hand"] == 100


# ---------------------------------------------------------------------------
# health-medication-inventory-report -- stored row aggregate (read-only).
# No ledger effect: a pure SELECT over healthclaw_medication; the DB is
# byte-identical afterwards. This handler has no validating refusal path
# (no err() call): the second test pins the empty-company behaviour instead.
# ---------------------------------------------------------------------------
class TestMedicationInventoryReport:
    def _seed_four(self, fconn, env):
        med_a = _add_med(fconn, env["company_id"], "Med-A", "10.00", 100,
                         reorder=10)
        med_b = _add_med(fconn, env["company_id"], "Med-B", "2.50", 4,
                         reorder=10)
        med_c = _add_med(fconn, env["company_id"], "Med-C", "7.00", 0,
                         reorder=5)
        med_d = _add_med(fconn, env["company_id"], "Med-D", "20.00", 50,
                         reorder=5, dea="II")
        return med_a, med_b, med_c, med_d

    def test_buckets_and_value_match_stored_rows_and_read_changes_nothing(
            self, fconn):
        env = _build_env(fconn)
        med_a, med_b, med_c, med_d = self._seed_four(fconn, env)
        before = _snapshot(fconn)

        r = call_action(
            ACTIONS["health-medication-inventory-report"], fconn, ns(
                company_id=env["company_id"], limit=50, offset=0))
        assert is_ok(r), r
        assert r["total_medications"] == 4
        assert r["total_inventory_value"] == "2010.00"
        assert Decimal(r["total_inventory_value"]) == Decimal("2010.00")
        assert r["out_of_stock_count"] == 1
        assert r["out_of_stock"] == [{"id": med_c, "name": "Med-C"}]
        assert r["below_reorder_count"] == 1
        assert r["below_reorder"] == [{"id": med_b, "name": "Med-B",
                                       "quantity_on_hand": 4,
                                       "reorder_level": 10}]
        assert r["controlled_count"] == 1
        assert r["controlled_substances"] == [
            {"id": med_d, "name": "Med-D", "dea_schedule": "II",
             "quantity_on_hand": 50}]
        assert _snapshot(fconn) == before
        assert _row(fconn, "healthclaw_medication", med_a)["unit_price"] == \
            "10.00"

    def test_unknown_company_reports_zeros_and_writes_nothing(self, fconn):
        env = _build_env(fconn)
        self._seed_four(fconn, env)
        before = _snapshot(fconn)
        r = call_action(
            ACTIONS["health-medication-inventory-report"], fconn, ns(
                company_id="no-such-company", limit=50, offset=0))
        assert is_ok(r), r
        assert r["total_medications"] == 0
        assert r["total_inventory_value"] == "0.00"
        assert Decimal(r["total_inventory_value"]) == Decimal("0.00")
        assert _snapshot(fconn) == before


# ---------------------------------------------------------------------------
# health-revenue-cycle-report -- stored row aggregate (read-only).
# No ledger effect: grouped SELECTs over healthclaw_charge/healthclaw_claim.
# No validating refusal path exists; the second test pins emptiness instead.
# ---------------------------------------------------------------------------
class TestRevenueCycleReport:
    def _seed_cycle(self, fconn, env):
        c1 = call_action(ACTIONS["health-adv-add-charge"], fconn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            provider_id=env["provider_id"], procedure_code_id=None,
            service_date="2026-03-10", cpt_code="99213", icd10_codes="[]",
            description="visit", quantity="2", unit_fee="100.00", notes=None,
            limit=50, offset=0))
        assert is_ok(c1), c1
        c2 = call_action(ACTIONS["health-adv-add-charge"], fconn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            provider_id=env["provider_id"], procedure_code_id=None,
            service_date="2026-03-11", cpt_code="99214", icd10_codes="[]",
            description="visit2", quantity="3", unit_fee="50.00", notes=None,
            limit=50, offset=0))
        assert is_ok(c2), c2
        assert c1["total_fee"] == "200.00"
        assert c2["total_fee"] == "150.00"
        cl1 = call_action(ACTIONS["health-adv-add-claim"], fconn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            payer_name="Acme Health", payer_id_number=None, policy_number=None,
            group_number=None, claim_number=None, claim_date="2026-03-15",
            charge_ids=json.dumps([c1["id"]]), notes=None,
            limit=50, offset=0))
        assert is_ok(cl1), cl1
        cl2 = call_action(ACTIONS["health-adv-add-claim"], fconn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            payer_name="Acme Health", payer_id_number=None, policy_number=None,
            group_number=None, claim_number=None, claim_date="2026-03-16",
            charge_ids=json.dumps([c2["id"]]), notes=None,
            limit=50, offset=0))
        assert is_ok(cl2), cl2
        assert cl1["total_charged"] == "200.00"
        assert cl2["total_charged"] == "150.00"
        for claim_id, charge_id, allowed, paid, adj in (
                (cl1["id"], c1["id"], "180.00", "150.00", "30.00"),
                (cl2["id"], c2["id"], "140.00", "50.00", "90.00")):
            pp = call_action(ACTIONS["health-adv-add-payment-posting"],
                             fconn, ns(
                company_id=env["company_id"], claim_id=claim_id,
                charge_id=charge_id, patient_id=env["patient_id"],
                payer_name="Acme Health", posting_date="2026-03-20",
                allowed_amount=allowed, paid_amount=paid, adjustment=adj,
                patient_responsibility="0.00", payment_method=None,
                check_number=None, notes=None, limit=50, offset=0))
            assert is_ok(pp), pp

    def test_totals_match_stored_charges_claims_and_read_changes_nothing(
            self, fconn):
        env = _build_env(fconn)
        self._seed_cycle(fconn, env)
        before = _snapshot(fconn)

        r = call_action(ACTIONS["health-revenue-cycle-report"], fconn, ns(
            company_id=env["company_id"], date_from=None, date_to=None,
            limit=50, offset=0))
        assert is_ok(r), r
        assert r["total_charges"] == "350.00"
        assert Decimal(r["total_charges"]) == Decimal("350.00")
        assert r["total_charge_count"] == 2
        assert r["charges_by_status"] == {
            "unbilled": {"count": 2, "total": "350.00"}}
        assert r["total_claimed"] == "350.00"
        assert Decimal(r["total_claimed"]) == Decimal("350.00")
        assert r["total_paid"] == "200.00"
        assert Decimal(r["total_paid"]) == Decimal("200.00")
        assert r["collection_rate_pct"] == 57.1
        assert r["claims_by_status"]["draft"]["count"] == 2
        assert r["claims_by_status"]["draft"]["total_charged"] == "350.00"
        assert r["claims_by_status"]["draft"]["total_paid"] == "200.00"
        assert _snapshot(fconn) == before

    def test_unknown_company_reports_zeros_and_writes_nothing(self, fconn):
        env = _build_env(fconn)
        self._seed_cycle(fconn, env)
        before = _snapshot(fconn)
        r = call_action(ACTIONS["health-revenue-cycle-report"], fconn, ns(
            company_id="no-such-company", date_from=None, date_to=None,
            limit=50, offset=0))
        assert is_ok(r), r
        assert r["total_charges"] == "0.00"
        assert r["total_claimed"] == "0.00"
        assert r["total_paid"] == "0.00"
        assert _snapshot(fconn) == before


# ---------------------------------------------------------------------------
# health-payer-mix-report -- stored row aggregate (read-only).
# No ledger effect: grouped SELECT over healthclaw_claim. No validating
# refusal path exists; the second test pins emptiness instead.
# ---------------------------------------------------------------------------
class TestPayerMixReport:
    def test_per_payer_totals_match_stored_claims(self, fconn):
        env = _build_env(fconn)
        TestRevenueCycleReport._seed_cycle(self, fconn, env)
        before = _snapshot(fconn)

        r = call_action(ACTIONS["health-payer-mix-report"], fconn, ns(
            company_id=env["company_id"], limit=50, offset=0))
        assert is_ok(r), r
        assert r["grand_total_charged"] == "350.00"
        assert Decimal(r["grand_total_charged"]) == Decimal("350.00")
        assert r["payer_count"] == 1
        assert len(r["payers"]) == 1
        payer = r["payers"][0]
        assert payer["payer_name"] == "Acme Health"
        assert payer["claim_count"] == 2
        assert payer["total_charged"] == "350.00"
        assert Decimal(payer["total_charged"]) == Decimal("350.00")
        assert payer["total_paid"] == "200.00"
        assert Decimal(payer["total_paid"]) == Decimal("200.00")
        assert payer["total_adjustment"] == "120.00"
        assert Decimal(payer["total_adjustment"]) == Decimal("120.00")
        assert payer["pct_of_total"] == 100.0
        assert _snapshot(fconn) == before

    def test_unknown_company_reports_zeros_and_writes_nothing(self, fconn):
        env = _build_env(fconn)
        TestRevenueCycleReport._seed_cycle(self, fconn, env)
        before = _snapshot(fconn)
        r = call_action(ACTIONS["health-payer-mix-report"], fconn, ns(
            company_id="no-such-company", limit=50, offset=0))
        assert is_ok(r), r
        assert r["grand_total_charged"] == "0.00"
        assert r["payer_count"] == 0
        assert r["payers"] == []
        assert _snapshot(fconn) == before


# ---------------------------------------------------------------------------
# health-underpayment-report -- stored row aggregate (read-only).
# No ledger effect: SELECT over healthclaw_claim_line joined to
# healthclaw_claim. This handler DOES validate input: missing or unknown
# company is refused with no write.
# ---------------------------------------------------------------------------
class TestUnderpaymentReport:
    def _seed_lines(self, fconn, env):
        ch = call_action(ACTIONS["health-add-charge"], fconn, ns(
            company_id=env["company_id"], encounter_id=env["encounter_id"],
            patient_id=env["patient_id"], provider_id=env["provider_id"],
            cpt_code="99213", charge_amount="300.00",
            service_date="2026-03-10", procedure_id=None, fee_schedule_id=None,
            units="1", modifier=None, modifiers=None, diagnosis_ids=None,
            place_of_service="11", rendering_provider_id=None,
            charge_status=None, notes=None, limit=50, offset=0))
        assert is_ok(ch), ch
        ins = call_action(ACTIONS["health-add-patient-insurance"], fconn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            insurance_type="primary", payer_name="Acme", payer_id=None,
            plan_name=None, plan_type=None, group_number=None,
            member_id="M1", subscriber_name=None, subscriber_dob=None,
            subscriber_relationship=None, copay_amount=None, deductible=None,
            deductible_met=None, out_of_pocket_max=None,
            effective_date="2026-01-01", termination_date=None,
            preauth_required=None, status=None, limit=50, offset=0))
        assert is_ok(ins), ins
        cl = call_action(ACTIONS["health-add-claim"], fconn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            encounter_id=env["encounter_id"], insurance_id=ins["id"],
            claim_type="professional", claim_date="2026-03-15",
            total_charge="300.00", billing_provider_id=env["provider_id"],
            rendering_provider_id=env["provider_id"], filing_indicator=None,
            notes=None, claim_status=None, total_allowed=None, total_paid=None,
            patient_responsibility=None, adjustment_amount=None,
            sales_invoice_id=None, denial_reason=None, appeal_deadline=None,
            limit=50, offset=0))
        assert is_ok(cl), cl
        ln = call_action(ACTIONS["health-add-claim-line"], fconn, ns(
            claim_id=cl["id"], charge_id=ch["id"], cpt_code="99213",
            line_number="1", modifiers=None, diagnosis_pointers=None,
            units="1", charge_amount="300.00", allowed_amount="250.00",
            paid_amount="180.00", adjustment_amount="70.00",
            patient_amount="0.00", denial_reason=None, remark_codes=None,
            limit=50, offset=0))
        assert is_ok(ln), ln
        ch2 = call_action(ACTIONS["health-add-charge"], fconn, ns(
            company_id=env["company_id"], encounter_id=env["encounter_id"],
            patient_id=env["patient_id"], provider_id=env["provider_id"],
            cpt_code="99214", charge_amount="100.00",
            service_date="2026-03-10", procedure_id=None, fee_schedule_id=None,
            units="1", modifier=None, modifiers=None, diagnosis_ids=None,
            place_of_service="11", rendering_provider_id=None,
            charge_status=None, notes=None, limit=50, offset=0))
        assert is_ok(ch2), ch2
        cl2 = call_action(ACTIONS["health-add-claim"], fconn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            encounter_id=env["encounter_id"], insurance_id=ins["id"],
            claim_type="professional", claim_date="2026-03-15",
            total_charge="100.00", billing_provider_id=env["provider_id"],
            rendering_provider_id=env["provider_id"], filing_indicator=None,
            notes=None, claim_status=None, total_allowed=None, total_paid=None,
            patient_responsibility=None, adjustment_amount=None,
            sales_invoice_id=None, denial_reason=None, appeal_deadline=None,
            limit=50, offset=0))
        assert is_ok(cl2), cl2
        ln2 = call_action(ACTIONS["health-add-claim-line"], fconn, ns(
            claim_id=cl2["id"], charge_id=ch2["id"], cpt_code="99214",
            line_number="1", modifiers=None, diagnosis_pointers=None,
            units="1", charge_amount="100.00", allowed_amount="100.00",
            paid_amount="100.00", adjustment_amount="0.00",
            patient_amount="0.00", denial_reason=None, remark_codes=None,
            limit=50, offset=0))
        assert is_ok(ln2), ln2
        for claim_id in (cl["id"], cl2["id"]):
            u = call_action(ACTIONS["health-update-claim"], fconn, ns(
                claim_id=claim_id, claim_date=None, place_of_service=None,
                filing_indicator=None, denial_reason=None, appeal_deadline=None,
                notes=None, claim_type=None, claim_status="paid",
                total_charge=None, total_allowed=None, total_paid=None,
                patient_responsibility=None, adjustment_amount=None,
                billing_provider_id=None, rendering_provider_id=None,
                prior_auth_id=None, sales_invoice_id=None,
                limit=50, offset=0))
            assert is_ok(u), u
        return ln["id"], cl["id"], env["patient_id"]

    def test_short_paid_line_reported_fully_paid_line_excluded(self, fconn):
        env = _build_env(fconn)
        line_id, claim_id, patient_id = self._seed_lines(fconn, env)
        before = _snapshot(fconn)

        r = call_action(ACTIONS["health-underpayment-report"], fconn, ns(
            company_id=env["company_id"], limit=50, offset=0))
        assert is_ok(r), r
        assert r["underpayment_count"] == 1
        assert r["total_underpaid"] == "70.00"
        assert Decimal(r["total_underpaid"]) == Decimal("70.00")
        assert len(r["underpayments"]) == 1
        entry = r["underpayments"][0]
        assert entry["claim_line_id"] == line_id
        assert entry["claim_id"] == claim_id
        assert entry["cpt_code"] == "99213"
        assert entry["allowed_amount"] == "250.00"
        assert Decimal(entry["allowed_amount"]) == Decimal("250.00")
        assert entry["paid_amount"] == "180.00"
        assert Decimal(entry["paid_amount"]) == Decimal("180.00")
        assert entry["underpayment"] == "70.00"
        assert Decimal(entry["underpayment"]) == Decimal("70.00")
        assert entry["patient_id"] == patient_id
        assert _snapshot(fconn) == before

    def test_bad_company_refused_and_writes_nothing(self, fconn):
        env = _build_env(fconn)
        self._seed_lines(fconn, env)
        before = _snapshot(fconn)
        r = call_action(ACTIONS["health-underpayment-report"], fconn, ns(
            company_id=None, limit=50, offset=0))
        assert is_error(r)
        assert r["message"] == "--company-id is required"
        assert _snapshot(fconn) == before
        r = call_action(ACTIONS["health-underpayment-report"], fconn, ns(
            company_id="no-such-company", limit=50, offset=0))
        assert is_error(r)
        assert r["message"] == "Company no-such-company not found"
        assert _snapshot(fconn) == before
