"""Depth tests (m425): 12 healthclaw actions asserted on stored rows, not envelopes.

Each action below already had a shape-only or routability-only test (or, for
8 of the 12, no direct test at all in this tree). The tests here seed rows
through the owning ADD action, call the LIST / MARK action, then read the rows
back with plain SELECTs and compare exact values -- including money as exact
Decimal strings, never float.

Actions covered (all 12 exist in db_query.ACTIONS):
  health-list-fee-schedule-items, health-list-formularies,
  health-list-formulary-items, health-list-imaging-results,
  health-list-lab-results, health-list-medications, health-list-payment-plans,
  health-list-prescriptions, health-list-prior-auths,
  health-list-procedure-codes, health-list-referrals, health-mark-lab-critical.

Ledger note (applies to every test in this file): none of these 12 actions
posts to the general ledger -- eleven are read-only lists and the twelfth is
a clinical flag update. Each test therefore asserts gl_entry stays at zero
with this comment instead of two-leg assertions a later reader might add.

Existing-test map (read before writing; deepened here, not duplicated):
  shape-only in this tree: list-formularies (test_billing_inventory.py),
    list-prescriptions (test_clinical.py), list-referrals and list-prior-auths
    (test_lab_referrals.py). No direct test in this tree for the other eight;
    their ADD halves are exercised in test_compliance.py, test_phase11.py and
    test_drug_interaction.py.
"""
import uuid
from decimal import Decimal

from health_helpers import (
    call_action, ns, is_error, is_ok, load_db_query,
    seed_company, seed_encounter, seed_patient,
)

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _msg(result):
    return result.get("message", "") + result.get("error", "")


def _count(conn, table):
    return conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]


def _dump(conn, table):
    return [tuple(row)
            for row in conn.execute(
                "SELECT * FROM %s ORDER BY rowid" % table).fetchall()]


def _snapshot(conn, tables):
    return {table: _dump(conn, table) for table in tables}


def _row(conn, table, row_id):
    found = conn.execute(
        "SELECT * FROM %s WHERE id = ?" % table, (row_id,)).fetchone()
    assert found is not None, "expected row %s in %s" % (row_id, table)
    return dict(found)


def _add_insurance(conn, env):
    res = call_action(mod.health_add_patient_insurance, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        insurance_type="primary",
        payer_name="TestPayer",
        payer_id=None, plan_name=None, plan_type=None,
        group_number=None, member_id="MEM-AUTH",
        subscriber_name=None, subscriber_dob=None,
        subscriber_relationship=None,
        copay_amount=None, deductible=None, deductible_met=None,
        out_of_pocket_max=None, effective_date="2026-01-01",
        termination_date=None, preauth_required=None, status=None,
        limit=50, offset=0,
    ))
    assert is_ok(res), res
    return res["id"]


def _add_item(conn, code):
    item_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO item (id, item_code, item_name) VALUES (?, ?, ?)",
        (item_id, code, "Test drug %s" % code))
    conn.commit()
    return item_id


def _add_fee_schedule(conn, company_id, name):
    res = call_action(mod.health_add_fee_schedule, conn, ns(
        company_id=company_id,
        fee_schedule_name=name,
        description=None,
        effective_date="2026-01-01",
        expiration_date=None,
        fee_schedule_status=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(res), res
    return res["id"]


def _add_lab_test(conn, lab_order_id, code, name):
    res = call_action(mod.health_add_lab_test, conn, ns(
        lab_order_id=lab_order_id,
        test_code=code,
        test_name=name,
        component_name=None,
        notes=None, status=None, cpt_code=None,
        limit=50, offset=0,
    ))
    assert is_ok(res), res
    return res["id"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. health-list-fee-schedule-items (stored rows; money)
# ─────────────────────────────────────────────────────────────────────────────

class TestListFeeScheduleItems:
    def _seed(self, conn, env):
        fs_id = _add_fee_schedule(conn, env["company_id"], "M425 FS")
        other_fs = _add_fee_schedule(conn, env["company_id"], "M425 FS Other")
        item_a = call_action(mod.health_add_fee_schedule_item, conn, ns(
            fee_schedule_id=fs_id, cpt_code="99213",
            description="Office visit", standard_charge="150.00",
            allowed_amount="120.00", unit_count=None, modifier=None,
            limit=50, offset=0))
        assert is_ok(item_a), item_a
        item_b = call_action(mod.health_add_fee_schedule_item, conn, ns(
            fee_schedule_id=fs_id, cpt_code="85025",
            description="Blood count", standard_charge="45.50",
            allowed_amount="40.00", unit_count=None, modifier=None,
            limit=50, offset=0))
        assert is_ok(item_b), item_b
        excluded = call_action(mod.health_add_fee_schedule_item, conn, ns(
            fee_schedule_id=other_fs, cpt_code="99213",
            description="Other schedule visit", standard_charge="999.00",
            allowed_amount="999.00", unit_count=None, modifier=None,
            limit=50, offset=0))
        assert is_ok(excluded), excluded
        return fs_id, item_a["id"], item_b["id"], excluded["id"]

    def test_lists_exact_stored_rows(self, conn, env):
        fs_id, id_a, id_b, excluded = self._seed(conn, env)
        before = _snapshot(conn, ["healthclaw_fee_schedule_item",
                                  "audit_log", "gl_entry"])
        result = call_action(mod.health_list_fee_schedule_items, conn, ns(
            fee_schedule_id=fs_id, cpt_code=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 2
        assert [row["cpt_code"] for row in result["rows"]] == ["85025", "99213"]
        assert {row["id"] for row in result["rows"]} == {id_a, id_b}
        assert excluded not in {row["id"] for row in result["rows"]}

        stored = _row(conn, "healthclaw_fee_schedule_item", id_a)
        assert stored["fee_schedule_id"] == fs_id
        assert stored["cpt_code"] == "99213"
        assert stored["description"] == "Office visit"
        assert stored["standard_charge"] == "150.00"
        assert stored["allowed_amount"] == "120.00"
        assert Decimal(stored["standard_charge"]) == Decimal("150.00")
        assert Decimal(stored["allowed_amount"]) == Decimal("120.00")
        assert stored["unit_count"] == 1

        filtered = call_action(mod.health_list_fee_schedule_items, conn, ns(
            fee_schedule_id=fs_id, cpt_code="99213", limit=50, offset=0))
        assert is_ok(filtered), filtered
        assert filtered["total_count"] == 1
        assert filtered["rows"][0]["id"] == id_a

        # Read path: nothing written, and no ledger legs (see module note).
        assert _snapshot(conn, ["healthclaw_fee_schedule_item",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0

    def test_unknown_schedule_returns_empty_and_writes_nothing(self, conn, env):
        self._seed(conn, env)
        before = _snapshot(conn, ["healthclaw_fee_schedule_item",
                                  "audit_log", "gl_entry"])
        # This action validates no input: an unknown id is an empty result,
        # not a refusal.
        result = call_action(mod.health_list_fee_schedule_items, conn, ns(
            fee_schedule_id="does-not-exist", cpt_code=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 0
        assert result["rows"] == []
        assert _snapshot(conn, ["healthclaw_fee_schedule_item",
                                "audit_log", "gl_entry"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# 2. health-list-formularies (stored rows)
# ─────────────────────────────────────────────────────────────────────────────

class TestListFormularies:
    def test_lists_exact_stored_rows(self, conn, env):
        res_a = call_action(mod.health_add_formulary, conn, ns(
            company_id=env["company_id"], formulary_name="M425 Formulary A",
            description="Depth A", effective_date="2026-01-01",
            expiration_date=None, formulary_status=None, notes=None,
            limit=50, offset=0))
        assert is_ok(res_a), res_a
        res_b = call_action(mod.health_add_formulary, conn, ns(
            company_id=env["company_id"], formulary_name="M425 Formulary B",
            description=None, effective_date="2026-01-01",
            expiration_date=None, formulary_status=None, notes=None,
            limit=50, offset=0))
        assert is_ok(res_b), res_b
        upd = call_action(mod.health_update_formulary, conn, ns(
            formulary_id=res_b["id"], formulary_name=None,
            description=None, formulary_status="inactive",
            effective_date=None, expiration_date=None, notes=None,
            limit=50, offset=0))
        assert is_ok(upd), upd

        before = _snapshot(conn, ["healthclaw_formulary",
                                  "audit_log", "gl_entry"])
        result = call_action(mod.health_list_formularies, conn, ns(
            company_id=env["company_id"], status=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 2
        by_id = {row["id"]: row for row in result["rows"]}
        assert by_id[res_a["id"]]["name"] == "M425 Formulary A"
        assert by_id[res_a["id"]]["status"] == "active"
        assert by_id[res_b["id"]]["status"] == "inactive"

        stored = _row(conn, "healthclaw_formulary", res_a["id"])
        assert stored["name"] == "M425 Formulary A"
        assert stored["description"] == "Depth A"
        assert stored["effective_date"] == "2026-01-01"
        assert stored["status"] == "active"
        assert stored["company_id"] == env["company_id"]

        active_only = call_action(mod.health_list_formularies, conn, ns(
            company_id=env["company_id"], status="active",
            limit=50, offset=0))
        assert is_ok(active_only), active_only
        assert active_only["total_count"] == 1
        assert active_only["rows"][0]["id"] == res_a["id"]

        # Read path: nothing written, and no ledger legs (see module note).
        assert _snapshot(conn, ["healthclaw_formulary",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0

    def test_unknown_company_returns_empty_and_writes_nothing(self, conn, env):
        before = _snapshot(conn, ["healthclaw_formulary",
                                  "audit_log", "gl_entry"])
        # This action validates no input: an unknown company is an empty
        # result, not a refusal.
        result = call_action(mod.health_list_formularies, conn, ns(
            company_id="does-not-exist", status=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 0
        assert result["rows"] == []
        assert _snapshot(conn, ["healthclaw_formulary",
                                "audit_log", "gl_entry"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# 3. health-list-formulary-items (stored rows)
# ─────────────────────────────────────────────────────────────────────────────

class TestListFormularyItems:
    def _seed(self, conn, env):
        res = call_action(mod.health_add_formulary, conn, ns(
            company_id=env["company_id"], formulary_name="M425 FI Formulary",
            description=None, effective_date="2026-01-01",
            expiration_date=None, formulary_status=None, notes=None,
            limit=50, offset=0))
        assert is_ok(res), res
        other = call_action(mod.health_add_formulary, conn, ns(
            company_id=env["company_id"], formulary_name="M425 FI Other",
            description=None, effective_date="2026-01-01",
            expiration_date=None, formulary_status=None, notes=None,
            limit=50, offset=0))
        assert is_ok(other), other
        item_one = _add_item(conn, "M425-D1")
        item_two = _add_item(conn, "M425-D2")
        item_other = _add_item(conn, "M425-D3")
        fi_a = call_action(mod.health_add_formulary_item, conn, ns(
            formulary_id=res["id"], item_id=item_one, ndc_code="11111-001",
            drug_class=None, generic_name="amoxicillin", brand_name="Amoxil",
            strength="500mg", dosage_form="capsule", route="oral",
            controlled_schedule=None, therapeutic_class=None,
            formulary_tier="2", requires_prior_auth=None, max_daily_dose=None,
            limit=50, offset=0))
        assert is_ok(fi_a), fi_a
        fi_b = call_action(mod.health_add_formulary_item, conn, ns(
            formulary_id=res["id"], item_id=item_two, ndc_code="22222-002",
            drug_class=None, generic_name="lisinopril", brand_name="Zestril",
            strength="10mg", dosage_form="tablet", route="oral",
            controlled_schedule=None, therapeutic_class=None,
            formulary_tier="1", requires_prior_auth=None, max_daily_dose=None,
            limit=50, offset=0))
        assert is_ok(fi_b), fi_b
        excluded = call_action(mod.health_add_formulary_item, conn, ns(
            formulary_id=other["id"], item_id=item_other,
            ndc_code="33333-003", drug_class=None, generic_name="other",
            brand_name="Other", strength="5mg", dosage_form="tablet",
            route="oral", controlled_schedule=None, therapeutic_class=None,
            formulary_tier="3", requires_prior_auth=None, max_daily_dose=None,
            limit=50, offset=0))
        assert is_ok(excluded), excluded
        return res["id"], item_one, fi_a["id"], fi_b["id"], excluded["id"]

    def test_lists_exact_stored_rows(self, conn, env):
        formulary_id, item_one, id_a, id_b, excluded = self._seed(conn, env)
        before = _snapshot(conn, ["healthclaw_formulary_item",
                                  "audit_log", "gl_entry"])
        result = call_action(mod.health_list_formulary_items, conn, ns(
            formulary_id=formulary_id, status=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 2
        assert {row["id"] for row in result["rows"]} == {id_a, id_b}
        assert excluded not in {row["id"] for row in result["rows"]}

        stored = _row(conn, "healthclaw_formulary_item", id_a)
        assert stored["formulary_id"] == formulary_id
        assert stored["item_id"] == item_one
        assert stored["ndc_code"] == "11111-001"
        assert stored["generic_name"] == "amoxicillin"
        assert stored["brand_name"] == "Amoxil"
        assert stored["strength"] == "500mg"
        assert stored["dosage_form"] == "capsule"
        assert stored["route"] == "oral"
        assert stored["formulary_tier"] == "2"
        assert stored["requires_prior_auth"] == 0
        assert stored["status"] == "active"

        # Read path: nothing written, and no ledger legs (see module note).
        assert _snapshot(conn, ["healthclaw_formulary_item",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0

    def test_unknown_formulary_returns_empty_and_writes_nothing(self, conn, env):
        self._seed(conn, env)
        before = _snapshot(conn, ["healthclaw_formulary_item",
                                  "audit_log", "gl_entry"])
        # This action validates no input: an unknown id is an empty result,
        # not a refusal.
        result = call_action(mod.health_list_formulary_items, conn, ns(
            formulary_id="does-not-exist", status=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 0
        assert result["rows"] == []
        assert _snapshot(conn, ["healthclaw_formulary_item",
                                "audit_log", "gl_entry"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# 4. health-list-lab-results (stored rows)
# ─────────────────────────────────────────────────────────────────────────────

class TestListLabResults:
    def _seed(self, conn, env):
        test_one = _add_lab_test(conn, env["lab_order_id"], "CBC",
                                 "Complete Blood Count")
        test_two = _add_lab_test(conn, env["lab_order_id"], "BMP",
                                 "Basic Metabolic Panel")
        res_a = call_action(mod.health_add_lab_result, conn, ns(
            lab_test_id=test_one, component_name="Hemoglobin",
            result_value="14.2", unit="g/dL", reference_low="12",
            reference_high="16", flag="normal", result_date="2026-03-16",
            performed_by_id=None, verified_by_id=None, notes=None,
            limit=50, offset=0))
        assert is_ok(res_a), res_a
        res_b = call_action(mod.health_add_lab_result, conn, ns(
            lab_test_id=test_one, component_name="WBC",
            result_value="11.5", unit="10^3/mcL", reference_low="4.5",
            reference_high="11.0", flag="high", result_date="2026-03-17",
            performed_by_id=None, verified_by_id=None, notes=None,
            limit=50, offset=0))
        assert is_ok(res_b), res_b
        excluded = call_action(mod.health_add_lab_result, conn, ns(
            lab_test_id=test_two, component_name="Glucose",
            result_value="200", unit="mg/dL", reference_low="70",
            reference_high="100", flag="high", result_date="2026-03-17",
            performed_by_id=None, verified_by_id=None, notes=None,
            limit=50, offset=0))
        assert is_ok(excluded), excluded
        return test_one, res_a["id"], res_b["id"], excluded["id"]

    def test_lists_exact_stored_rows(self, conn, env):
        test_one, id_a, id_b, excluded = self._seed(conn, env)
        before = _snapshot(conn, ["healthclaw_lab_result",
                                  "audit_log", "gl_entry"])
        result = call_action(mod.health_list_lab_results, conn, ns(
            lab_test_id=test_one, flag=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 2
        # Ordered by result_date descending: the 03-17 row comes first.
        assert [row["id"] for row in result["rows"]] == [id_b, id_a]
        assert excluded not in {row["id"] for row in result["rows"]}

        stored = _row(conn, "healthclaw_lab_result", id_a)
        assert stored["lab_test_id"] == test_one
        assert stored["component_name"] == "Hemoglobin"
        assert stored["value"] == "14.2"
        assert stored["unit"] == "g/dL"
        assert stored["reference_low"] == "12"
        assert stored["reference_high"] == "16"
        assert stored["flag"] == "normal"
        assert stored["is_abnormal"] == 0
        assert stored["is_critical"] == 0
        assert stored["result_date"] == "2026-03-16"

        flagged = call_action(mod.health_list_lab_results, conn, ns(
            lab_test_id=test_one, flag="high", limit=50, offset=0))
        assert is_ok(flagged), flagged
        assert flagged["total_count"] == 1
        assert flagged["rows"][0]["id"] == id_b

        # Read path: nothing written, and no ledger legs (see module note).
        # Lab values are TEXT, not money: no Decimal assertion applies here.
        assert _snapshot(conn, ["healthclaw_lab_result",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0

    def test_unknown_test_returns_empty_and_writes_nothing(self, conn, env):
        self._seed(conn, env)
        before = _snapshot(conn, ["healthclaw_lab_result",
                                  "audit_log", "gl_entry"])
        # This action validates no input: an unknown id is an empty result,
        # not a refusal.
        result = call_action(mod.health_list_lab_results, conn, ns(
            lab_test_id="does-not-exist", flag=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 0
        assert result["rows"] == []
        assert _snapshot(conn, ["healthclaw_lab_result",
                                "audit_log", "gl_entry"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# 5. health-list-imaging-results (stored rows)
# ─────────────────────────────────────────────────────────────────────────────

class TestListImagingResults:
    def _add_order(self, conn, env, modality, body_part):
        res = call_action(mod.health_add_imaging_order, conn, ns(
            company_id=env["company_id"], encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            ordering_provider_id=env["provider_id"],
            modality=modality, body_part=body_part,
            laterality=None, contrast=None, order_date="2026-03-15",
            priority="routine", clinical_indication="Depth probe",
            scheduled_date=None, notes=None, imaging_order_status=None,
            status=None, order_id=None, cpt_code=None,
            limit=50, offset=0))
        assert is_ok(res), res
        return res["id"]

    def _add_result(self, conn, order_id, findings, impression, report_date):
        res = call_action(mod.health_add_imaging_result, conn, ns(
            imaging_order_id=order_id, radiologist_id=None,
            findings=findings, impression=impression, recommendation=None,
            critical_finding=None, report_date=report_date, addendum=None,
            limit=50, offset=0))
        assert is_ok(res), res
        return res["id"]

    def test_lists_exact_stored_rows(self, conn, env):
        order_one = self._add_order(conn, env, "xray", "Chest")
        order_two = self._add_order(conn, env, "ct", "Abdomen")
        id_a = self._add_result(conn, order_one, "Clear lungs", "Normal",
                                "2026-03-16")
        id_b = self._add_result(conn, order_one, "Mild infiltrate",
                                "Follow up", "2026-03-18")
        excluded = self._add_result(conn, order_two, "Unrelated",
                                    "Unrelated", "2026-03-18")

        before = _snapshot(conn, ["healthclaw_imaging_result",
                                  "audit_log", "gl_entry"])
        result = call_action(mod.health_list_imaging_results, conn, ns(
            imaging_order_id=order_one, status=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 2
        # Ordered by report_date descending: the 03-18 row comes first.
        assert [row["id"] for row in result["rows"]] == [id_b, id_a]
        assert excluded not in {row["id"] for row in result["rows"]}

        stored = _row(conn, "healthclaw_imaging_result", id_a)
        assert stored["imaging_order_id"] == order_one
        assert stored["findings"] == "Clear lungs"
        assert stored["impression"] == "Normal"
        assert stored["report_date"] == "2026-03-16"
        assert stored["status"] == "preliminary"
        assert stored["critical_finding"] == 0

        # Read path: nothing written, and no ledger legs (see module note).
        assert _snapshot(conn, ["healthclaw_imaging_result",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0

    def test_unknown_order_returns_empty_and_writes_nothing(self, conn, env):
        order_one = self._add_order(conn, env, "xray", "Chest")
        self._add_result(conn, order_one, "Clear lungs", "Normal",
                         "2026-03-16")
        before = _snapshot(conn, ["healthclaw_imaging_result",
                                  "audit_log", "gl_entry"])
        # This action validates no input: an unknown id is an empty result,
        # not a refusal.
        result = call_action(mod.health_list_imaging_results, conn, ns(
            imaging_order_id="does-not-exist", status=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 0
        assert result["rows"] == []
        assert _snapshot(conn, ["healthclaw_imaging_result",
                                "audit_log", "gl_entry"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# 6. health-list-medications (stored rows; money)
# ─────────────────────────────────────────────────────────────────────────────

class TestListMedications:
    def _add_med(self, conn, company_id, name, generic, price, dea):
        res = call_action(mod.health_add_medication, conn, ns(
            company_id=company_id, name=name, generic_name=generic,
            ndc_code="68180-%s" % name[:4], dea_schedule=dea,
            dosage_form="tablet", strength="10mg", manufacturer="Acme",
            unit_price=price, quantity_on_hand="100", reorder_level="10",
            notes=None, limit=50, offset=0))
        assert is_ok(res), res
        return res["id"]

    def test_lists_exact_stored_rows(self, conn, env):
        id_a = self._add_med(conn, env["company_id"], "Lisinopril",
                             "lisinopril", "12.50", "non-scheduled")
        id_b = self._add_med(conn, env["company_id"], "Oxycodone",
                             "oxycodone", "8.00", "II")
        other_company = seed_company(conn)
        excluded = self._add_med(conn, other_company, "Elsewhere",
                                 "elsewhere", "99.00", "non-scheduled")

        before = _snapshot(conn, ["healthclaw_medication",
                                  "audit_log", "gl_entry"])
        result = call_action(mod.health_list_medications, conn, ns(
            company_id=env["company_id"], dea_schedule=None, search=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 2
        assert {row["id"] for row in result["rows"]} == {id_a, id_b}
        assert excluded not in {row["id"] for row in result["rows"]}

        stored = _row(conn, "healthclaw_medication", id_a)
        assert stored["company_id"] == env["company_id"]
        assert stored["name"] == "Lisinopril"
        assert stored["generic_name"] == "lisinopril"
        assert stored["dea_schedule"] == "non-scheduled"
        assert stored["unit_price"] == "12.50"
        assert Decimal(stored["unit_price"]) == Decimal("12.50")
        assert stored["quantity_on_hand"] == 100
        assert stored["reorder_level"] == 10
        assert stored["is_active"] == 1

        scheduled = call_action(mod.health_list_medications, conn, ns(
            company_id=env["company_id"], dea_schedule="II", search=None,
            limit=50, offset=0))
        assert is_ok(scheduled), scheduled
        assert scheduled["total_count"] == 1
        assert scheduled["rows"][0]["id"] == id_b

        searched = call_action(mod.health_list_medications, conn, ns(
            company_id=env["company_id"], dea_schedule=None,
            search="lisinopril", limit=50, offset=0))
        assert is_ok(searched), searched
        assert searched["total_count"] == 1
        assert searched["rows"][0]["id"] == id_a

        # Read path: nothing written, and no ledger legs (see module note).
        assert _snapshot(conn, ["healthclaw_medication",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0

    def test_unmatched_search_returns_empty_and_writes_nothing(self, conn, env):
        self._add_med(conn, env["company_id"], "Lisinopril", "lisinopril",
                      "12.50", "non-scheduled")
        before = _snapshot(conn, ["healthclaw_medication",
                                  "audit_log", "gl_entry"])
        # This action validates no input: a non-matching search is an empty
        # result, not a refusal.
        result = call_action(mod.health_list_medications, conn, ns(
            company_id=env["company_id"], dea_schedule=None,
            search="no-such-drug-xyz", limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 0
        assert result["rows"] == []
        assert _snapshot(conn, ["healthclaw_medication",
                                "audit_log", "gl_entry"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# 7. health-list-payment-plans (stored rows; money; validates input)
# ─────────────────────────────────────────────────────────────────────────────

class TestListPaymentPlans:
    def _add_plan(self, conn, patient_id, company_id, amount, installment):
        res = call_action(mod.health_add_payment_plan, conn, ns(
            company_id=company_id, patient_id=patient_id, amount=amount,
            installment_amount=installment, frequency="monthly",
            start_date="2026-04-01", limit=50, offset=0))
        assert is_ok(res), res
        return res["id"]

    def test_lists_exact_stored_rows(self, conn, env):
        id_a = self._add_plan(conn, env["patient_id"], env["company_id"],
                              "1200.00", "100.00")
        id_b = self._add_plan(conn, env["patient_id"], env["company_id"],
                              "300.00", "100.00")
        other_patient = seed_patient(conn, env["company_id"], "Other", "Pt")
        excluded = self._add_plan(conn, other_patient, env["company_id"],
                                  "500.00", "100.00")

        before = _snapshot(conn, ["healthclaw_payment_plan",
                                  "audit_log", "gl_entry"])
        result = call_action(mod.health_list_payment_plans, conn, ns(
            patient_id=env["patient_id"], status=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 2
        assert {row["id"] for row in result["rows"]} == {id_a, id_b}
        assert excluded not in {row["id"] for row in result["rows"]}

        stored = _row(conn, "healthclaw_payment_plan", id_a)
        assert stored["patient_id"] == env["patient_id"]
        assert stored["total_amount"] == "1200.00"
        assert stored["installment_amount"] == "100.00"
        assert stored["remaining_balance"] == "1200.00"
        assert Decimal(stored["total_amount"]) == Decimal("1200.00")
        assert Decimal(stored["installment_amount"]) == Decimal("100.00")
        assert Decimal(stored["remaining_balance"]) == Decimal("1200.00")
        assert stored["frequency"] == "monthly"
        assert stored["num_installments"] == 12
        assert stored["installments_paid"] == 0
        assert stored["start_date"] == "2026-04-01"
        assert stored["next_due_date"] == "2026-04-01"
        assert stored["status"] == "active"
        assert stored["company_id"] == env["company_id"]

        stored_b = _row(conn, "healthclaw_payment_plan", id_b)
        assert stored_b["num_installments"] == 3
        assert stored_b["total_amount"] == "300.00"

        # Read path: nothing written, and no ledger legs (see module note).
        assert _snapshot(conn, ["healthclaw_payment_plan",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0

    def test_refusal_writes_nothing(self, conn, env):
        plan_id = self._add_plan(conn, env["patient_id"], env["company_id"],
                                 "1200.00", "100.00")
        before = _snapshot(conn, ["healthclaw_payment_plan",
                                  "audit_log", "gl_entry"])

        missing = call_action(mod.health_list_payment_plans, conn, ns(
            patient_id=None, status=None, limit=50, offset=0))
        assert is_error(missing)
        assert _msg(missing) == "--patient-id is required"

        bogus = call_action(mod.health_list_payment_plans, conn, ns(
            patient_id="no-such-patient", status=None, limit=50, offset=0))
        assert is_error(bogus)
        assert _msg(bogus) == "Patient no-such-patient not found"

        assert _row(conn, "healthclaw_payment_plan",
                    plan_id)["status"] == "active"
        assert _snapshot(conn, ["healthclaw_payment_plan",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0


# ─────────────────────────────────────────────────────────────────────────────
# 8. health-list-prescriptions (stored rows)
# ─────────────────────────────────────────────────────────────────────────────

class TestListPrescriptions:
    def _add_rx(self, conn, env, patient_id, med_name, dosage,
                encounter_id=None):
        res = call_action(mod.health_add_prescription, conn, ns(
            company_id=env["company_id"],
            encounter_id=encounter_id or env["encounter_id"],
            patient_id=patient_id, prescriber_id=env["provider_id"],
            medication_name=med_name, ndc_code=None, dosage=dosage,
            frequency="3x daily", route="oral", quantity="30", refills="0",
            daw=None, rx_start_date="2026-03-15", rx_end_date="2026-03-25",
            controlled_schedule=None, pharmacy_notes=None, rx_status=None,
            discontinued_reason=None, notes=None, provider_id=None,
            diagnosis_id=None, limit=50, offset=0))
        assert is_ok(res), res
        return res["id"]

    def test_lists_exact_stored_rows(self, conn, env):
        id_a = self._add_rx(conn, env, env["patient_id"], "Amoxicillin",
                            "500mg")
        id_b = self._add_rx(conn, env, env["patient_id"], "Ibuprofen",
                            "200mg")
        other_patient = seed_patient(conn, env["company_id"], "Other", "Pt")
        other_encounter = seed_encounter(conn, env["company_id"],
                                         other_patient, env["provider_id"])
        excluded = self._add_rx(conn, env, other_patient, "Elsewhere",
                                "5mg", encounter_id=other_encounter)

        before = _snapshot(conn, ["healthclaw_prescription",
                                  "audit_log", "gl_entry"])
        result = call_action(mod.health_list_prescriptions, conn, ns(
            encounter_id=env["encounter_id"], patient_id=None, rx_status=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 2
        assert {row["id"] for row in result["rows"]} == {id_a, id_b}
        assert excluded not in {row["id"] for row in result["rows"]}

        stored = _row(conn, "healthclaw_prescription", id_a)
        assert stored["encounter_id"] == env["encounter_id"]
        assert stored["patient_id"] == env["patient_id"]
        assert stored["prescriber_id"] == env["provider_id"]
        assert stored["medication_name"] == "Amoxicillin"
        assert stored["dosage"] == "500mg"
        assert stored["frequency"] == "3x daily"
        assert stored["route"] == "oral"
        assert stored["quantity"] == "30"
        assert stored["refills"] == 0
        assert stored["daw"] == 0
        assert stored["start_date"] == "2026-03-15"
        assert stored["end_date"] == "2026-03-25"
        assert stored["status"] == "active"
        assert stored["company_id"] == env["company_id"]

        by_patient = call_action(mod.health_list_prescriptions, conn, ns(
            encounter_id=None, patient_id=other_patient, rx_status=None,
            limit=50, offset=0))
        assert is_ok(by_patient), by_patient
        assert by_patient["total_count"] == 1
        assert by_patient["rows"][0]["id"] == excluded

        # Read path: nothing written, and no ledger legs (see module note).
        assert _snapshot(conn, ["healthclaw_prescription",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0

    def test_unknown_encounter_returns_empty_and_writes_nothing(self, conn, env):
        self._add_rx(conn, env, env["patient_id"], "Amoxicillin", "500mg")
        before = _snapshot(conn, ["healthclaw_prescription",
                                  "audit_log", "gl_entry"])
        # This action validates no input: an unknown id is an empty result,
        # not a refusal.
        result = call_action(mod.health_list_prescriptions, conn, ns(
            encounter_id="does-not-exist", patient_id=None, rx_status=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 0
        assert result["rows"] == []
        assert _snapshot(conn, ["healthclaw_prescription",
                                "audit_log", "gl_entry"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# 9. health-list-prior-auths (stored rows)
# ─────────────────────────────────────────────────────────────────────────────

class TestListPriorAuths:
    def _add_auth(self, conn, env, patient_id, insurance_id, service,
                  description):
        res = call_action(mod.health_add_prior_auth, conn, ns(
            company_id=env["company_id"], patient_id=patient_id,
            insurance_id=insurance_id,
            requesting_provider_id=env["provider_id"], service_type=service,
            cpt_codes="99213", icd10_codes="J06.9", description=description,
            units_requested="1", request_date="2026-03-15",
            effective_date="2026-03-15", expiration_date="2026-06-15",
            auth_number=None, auth_status=None, decision_date=None,
            units_approved=None, notes=None, status=None,
            limit=50, offset=0))
        assert is_ok(res), res
        return res["id"]

    def test_lists_exact_stored_rows(self, conn, env):
        insurance_id = _add_insurance(conn, env)
        id_a = self._add_auth(conn, env, env["patient_id"], insurance_id,
                              "procedure", "Office visit pre-auth")
        id_b = self._add_auth(conn, env, env["patient_id"], insurance_id,
                              "imaging", "MRI pre-auth")
        other_patient = seed_patient(conn, env["company_id"], "Other", "Pt")
        other_ins = call_action(mod.health_add_patient_insurance, conn, ns(
            patient_id=other_patient, company_id=env["company_id"],
            insurance_type="primary", payer_name="OtherPayer", payer_id=None,
            plan_name=None, plan_type=None, group_number=None,
            member_id="MEM-OTHER", subscriber_name=None, subscriber_dob=None,
            subscriber_relationship=None, copay_amount=None, deductible=None,
            deductible_met=None, out_of_pocket_max=None,
            effective_date="2026-01-01", termination_date=None,
            preauth_required=None, status=None, limit=50, offset=0))
        assert is_ok(other_ins), other_ins
        excluded = self._add_auth(conn, env, other_patient, other_ins["id"],
                                  "procedure", "Other patient auth")

        before = _snapshot(conn, ["healthclaw_prior_auth",
                                  "audit_log", "gl_entry"])
        result = call_action(mod.health_list_prior_auths, conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            auth_status=None, status=None, insurance_id=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 2
        assert {row["id"] for row in result["rows"]} == {id_a, id_b}
        assert excluded not in {row["id"] for row in result["rows"]}

        stored = _row(conn, "healthclaw_prior_auth", id_a)
        assert stored["patient_id"] == env["patient_id"]
        assert stored["insurance_id"] == insurance_id
        assert stored["requesting_provider_id"] == env["provider_id"]
        assert stored["service_type"] == "procedure"
        assert stored["cpt_codes"] == "99213"
        assert stored["icd10_codes"] == "J06.9"
        assert stored["description"] == "Office visit pre-auth"
        assert stored["units_requested"] == 1
        assert stored["units_approved"] is None
        assert stored["request_date"] == "2026-03-15"
        assert stored["effective_date"] == "2026-03-15"
        assert stored["expiration_date"] == "2026-06-15"
        assert stored["status"] == "pending"
        assert stored["company_id"] == env["company_id"]

        # Read path: nothing written, and no ledger legs (see module note).
        assert _snapshot(conn, ["healthclaw_prior_auth",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0

    def test_unknown_patient_returns_empty_and_writes_nothing(self, conn, env):
        insurance_id = _add_insurance(conn, env)
        self._add_auth(conn, env, env["patient_id"], insurance_id,
                       "procedure", "Office visit pre-auth")
        before = _snapshot(conn, ["healthclaw_prior_auth",
                                  "audit_log", "gl_entry"])
        # This action validates no input: an unknown id is an empty result,
        # not a refusal.
        result = call_action(mod.health_list_prior_auths, conn, ns(
            company_id=None, patient_id="does-not-exist", auth_status=None,
            status=None, insurance_id=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 0
        assert result["rows"] == []
        assert _snapshot(conn, ["healthclaw_prior_auth",
                                "audit_log", "gl_entry"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# 10. health-list-procedure-codes (stored rows; money)
# ─────────────────────────────────────────────────────────────────────────────

class TestListProcedureCodes:
    def _add_code(self, conn, company_id, code, code_type, description,
                  category, fee):
        res = call_action(mod.health_add_procedure_code, conn, ns(
            company_id=company_id, code=code, code_type=code_type,
            description=description, category=category, default_fee=fee,
            notes=None, limit=50, offset=0))
        assert is_ok(res), res
        return res["id"]

    def test_lists_exact_stored_rows(self, conn, env):
        id_a = self._add_code(conn, env["company_id"], "99213", "CPT",
                              "Office visit", "E/M", "150.00")
        id_b = self._add_code(conn, env["company_id"], "G0202", "HCPCS",
                              "Screening mammography", "Radiology", "200.00")
        other_company = seed_company(conn)
        excluded = self._add_code(conn, other_company, "99213", "CPT",
                                  "Elsewhere visit", "E/M", "999.00")

        before = _snapshot(conn, ["healthclaw_procedure_code",
                                  "audit_log", "gl_entry"])
        result = call_action(mod.health_list_procedure_codes, conn, ns(
            company_id=env["company_id"], code_type=None, category=None,
            search=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 2
        # Ordered by code ascending.
        assert [row["code"] for row in result["rows"]] == ["99213", "G0202"]
        assert {row["id"] for row in result["rows"]} == {id_a, id_b}
        assert excluded not in {row["id"] for row in result["rows"]}

        stored = _row(conn, "healthclaw_procedure_code", id_a)
        assert stored["company_id"] == env["company_id"]
        assert stored["code"] == "99213"
        assert stored["code_type"] == "CPT"
        assert stored["description"] == "Office visit"
        assert stored["category"] == "E/M"
        assert stored["default_fee"] == "150.00"
        assert Decimal(stored["default_fee"]) == Decimal("150.00")
        assert stored["is_active"] == 1

        cpt_only = call_action(mod.health_list_procedure_codes, conn, ns(
            company_id=env["company_id"], code_type="CPT", category=None,
            search=None, limit=50, offset=0))
        assert is_ok(cpt_only), cpt_only
        assert cpt_only["total_count"] == 1
        assert cpt_only["rows"][0]["id"] == id_a

        searched = call_action(mod.health_list_procedure_codes, conn, ns(
            company_id=env["company_id"], code_type=None, category=None,
            search="mammography", limit=50, offset=0))
        assert is_ok(searched), searched
        assert searched["total_count"] == 1
        assert searched["rows"][0]["id"] == id_b

        # Read path: nothing written, and no ledger legs (see module note).
        assert _snapshot(conn, ["healthclaw_procedure_code",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0

    def test_unknown_company_returns_empty_and_writes_nothing(self, conn, env):
        self._add_code(conn, env["company_id"], "99213", "CPT",
                       "Office visit", "E/M", "150.00")
        before = _snapshot(conn, ["healthclaw_procedure_code",
                                  "audit_log", "gl_entry"])
        # This action validates no input: an unknown company is an empty
        # result, not a refusal.
        result = call_action(mod.health_list_procedure_codes, conn, ns(
            company_id="does-not-exist", code_type=None, category=None,
            search=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 0
        assert result["rows"] == []
        assert _snapshot(conn, ["healthclaw_procedure_code",
                                "audit_log", "gl_entry"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# 11. health-list-referrals (stored rows)
# ─────────────────────────────────────────────────────────────────────────────

class TestListReferrals:
    def _add_referral(self, conn, env, patient_id, to_provider, specialty,
                      reason):
        res = call_action(mod.health_add_referral, conn, ns(
            company_id=env["company_id"], patient_id=patient_id,
            referring_provider_id=env["provider_id"],
            referred_to_provider=to_provider,
            referred_to_specialty=specialty, referred_to_facility=None,
            referred_to_phone=None, referred_to_fax=None,
            referral_date="2026-03-15", reason=reason, priority="routine",
            prior_auth_required=None, notes=None, referral_status=None,
            status=None, encounter_id=None, diagnosis_id=None,
            insurance_id=None, expiration_date=None,
            limit=50, offset=0))
        assert is_ok(res), res
        return res["id"]

    def test_lists_exact_stored_rows(self, conn, env):
        id_a = self._add_referral(conn, env, env["patient_id"],
                                  "Dr. Specialist", "Cardiology",
                                  "Chest pain evaluation")
        id_b = self._add_referral(conn, env, env["patient_id"], "Dr. Derm",
                                  "Dermatology", "Skin rash")
        other_patient = seed_patient(conn, env["company_id"], "Other", "Pt")
        excluded = self._add_referral(conn, env, other_patient, "Dr. Other",
                                      "Neurology", "Headache")

        before = _snapshot(conn, ["healthclaw_referral",
                                  "audit_log", "gl_entry"])
        result = call_action(mod.health_list_referrals, conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            referral_status=None, referring_provider_id=None, status=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 2
        assert {row["id"] for row in result["rows"]} == {id_a, id_b}
        assert excluded not in {row["id"] for row in result["rows"]}

        stored = _row(conn, "healthclaw_referral", id_a)
        assert stored["patient_id"] == env["patient_id"]
        assert stored["referring_provider_id"] == env["provider_id"]
        assert stored["referred_to_provider"] == "Dr. Specialist"
        assert stored["referred_to_specialty"] == "Cardiology"
        assert stored["referral_date"] == "2026-03-15"
        assert stored["reason"] == "Chest pain evaluation"
        assert stored["priority"] == "routine"
        assert stored["prior_auth_required"] == 0
        assert stored["status"] == "pending"
        assert stored["company_id"] == env["company_id"]

        by_provider = call_action(mod.health_list_referrals, conn, ns(
            company_id=None, patient_id=None, referral_status=None,
            referring_provider_id=env["provider_id"], status=None,
            limit=50, offset=0))
        assert is_ok(by_provider), by_provider
        assert by_provider["total_count"] == 3

        # Read path: nothing written, and no ledger legs (see module note).
        assert _snapshot(conn, ["healthclaw_referral",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0

    def test_unknown_patient_returns_empty_and_writes_nothing(self, conn, env):
        self._add_referral(conn, env, env["patient_id"], "Dr. Specialist",
                           "Cardiology", "Chest pain evaluation")
        before = _snapshot(conn, ["healthclaw_referral",
                                  "audit_log", "gl_entry"])
        # This action validates no input: an unknown id is an empty result,
        # not a refusal.
        result = call_action(mod.health_list_referrals, conn, ns(
            company_id=None, patient_id="does-not-exist",
            referral_status=None, referring_provider_id=None, status=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_count"] == 0
        assert result["rows"] == []
        assert _snapshot(conn, ["healthclaw_referral",
                                "audit_log", "gl_entry"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# 12. health-mark-lab-critical (stored-row transition; validates input)
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkLabCritical:
    def _add_result(self, conn, lab_test_id, component, value, flag, date):
        res = call_action(mod.health_add_lab_result, conn, ns(
            lab_test_id=lab_test_id, component_name=component,
            result_value=value, unit="g/dL", reference_low="12",
            reference_high="16", flag=flag, result_date=date,
            performed_by_id=None, verified_by_id=None, notes=None,
            limit=50, offset=0))
        assert is_ok(res), res
        return res["id"]

    def test_marks_exact_row_and_leaves_the_rest(self, conn, env):
        lab_test_id = _add_lab_test(conn, env["lab_order_id"], "CBC",
                                    "Complete Blood Count")
        target_id = self._add_result(conn, lab_test_id, "Hemoglobin", "6.1",
                                     "critical_low", "2026-03-16")
        other_id = self._add_result(conn, lab_test_id, "WBC", "7.0",
                                    "normal", "2026-03-16")

        before_target = _row(conn, "healthclaw_lab_result", target_id)
        assert before_target["is_critical"] == 0
        assert before_target["is_abnormal"] == 0
        before_other = _row(conn, "healthclaw_lab_result", other_id)
        audit_before = _count(conn, "audit_log")

        result = call_action(mod.health_mark_lab_critical, conn, ns(
            lab_result_id=target_id, company_id=None, limit=50, offset=0))
        assert is_ok(result), result
        assert result["id"] == target_id
        assert result["is_critical"] == 1
        assert result["is_abnormal"] == 1

        after_target = _row(conn, "healthclaw_lab_result", target_id)
        assert after_target["is_critical"] == 1
        assert after_target["is_abnormal"] == 1
        for column, old_value in before_target.items():
            if column in ("is_critical", "is_abnormal", "updated_at"):
                continue
            assert after_target[column] == old_value, column

        # The sibling result is byte-identical: what should NOT have changed.
        assert _row(conn, "healthclaw_lab_result", other_id) == before_other

        # A flag update posts no ledger legs (see module note).
        assert _count(conn, "gl_entry") == 0
        assert _count(conn, "audit_log") == audit_before + 1

    def test_refusal_writes_nothing(self, conn, env):
        lab_test_id = _add_lab_test(conn, env["lab_order_id"], "CBC",
                                    "Complete Blood Count")
        target_id = self._add_result(conn, lab_test_id, "Hemoglobin", "6.1",
                                     "critical_low", "2026-03-16")
        before = _snapshot(conn, ["healthclaw_lab_result",
                                  "audit_log", "gl_entry"])

        missing = call_action(mod.health_mark_lab_critical, conn, ns(
            lab_result_id=None, company_id=None, limit=50, offset=0))
        assert is_error(missing)
        assert _msg(missing) == "--lab-result-id is required"

        bogus_id = "no-such-result"
        bogus = call_action(mod.health_mark_lab_critical, conn, ns(
            lab_result_id=bogus_id, company_id=None, limit=50, offset=0))
        assert is_error(bogus)
        assert _msg(bogus) == "Lab result %s not found" % bogus_id

        kept = _row(conn, "healthclaw_lab_result", target_id)
        assert kept["is_critical"] == 0
        assert kept["is_abnormal"] == 0
        assert _snapshot(conn, ["healthclaw_lab_result",
                                "audit_log", "gl_entry"]) == before
        assert _count(conn, "gl_entry") == 0
