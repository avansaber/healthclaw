"""Audit rows name the table and the record (part 2).

Covers the advanced, lab, compliance, inventory, referral and
revenue-cycle files: adv_billing, adv_lab, adv_pharmacy, adv_reports_v2,
compliance, inventory, lab, provider_mgmt, rcm, referrals.

Product rule: an audit row carries skill = module name ("healthclaw"),
action = action name ("health-add-referral"), entity_type = table
("healthclaw_referral") and entity_id = that record's id, so a clinic
reading the trail for a record finds it under that record's id.
"""
import ast
import json
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from health_helpers import call_action, is_ok, load_db_query, ns  # noqa: E402

from erpclaw_lib.query import Field, P, Q, Table  # noqa: E402

ACTIONS = load_db_query().ACTIONS

MODULE_DIR = os.path.dirname(_TESTS_DIR)

IN_SCOPE = [
    "adv_billing.py",
    "adv_lab.py",
    "adv_pharmacy.py",
    "adv_reports_v2.py",
    "compliance.py",
    "inventory.py",
    "lab.py",
    "provider_mgmt.py",
    "rcm.py",
    "referrals.py",
]

SKILL = "healthclaw"
TABLE_PREFIX = "healthclaw_"
ACTION_PREFIXES = ("health-", "dental-", "vet-", "mental-", "homehealth-")


def _audit_rows(conn, entity_id):
    """Audit rows for one record through a PyPika-built bound query."""
    t = Table("audit_log")
    rows = conn.execute(
        Q.from_(t).select(
            t.skill, t.action, t.entity_type, t.entity_id, t.new_values
        ).where(Field("entity_id") == P()).get_sql(),
        (entity_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _assert_single_audit(conn, record_id, action, table):
    rows = [r for r in _audit_rows(conn, record_id) if r["action"] == action]
    assert len(rows) == 1, (action, record_id, rows)
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (SKILL, action, table)


def test_every_audit_call_has_the_foundation_shape():
    for name in IN_SCOPE:
        with open(os.path.join(MODULE_DIR, name)) as fh:
            tree = ast.parse(fh.read())
        seen = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id == "audit"):
                continue
            seen += 1
            assert len(node.args) >= 5, (name, seen)
            second = node.args[1]
            assert ((isinstance(second, ast.Name) and second.id == "SKILL")
                    or (isinstance(second, ast.Constant)
                        and second.value == SKILL)), (name, seen)
            third = node.args[2]
            assert (isinstance(third, ast.Constant)
                    and isinstance(third.value, str)
                    and third.value.startswith(ACTION_PREFIXES)), (name, seen)
            fourth = node.args[3]
            assert (isinstance(fourth, ast.Constant)
                    and isinstance(fourth.value, str)
                    and fourth.value.startswith(TABLE_PREFIX)
                    and "_" in fourth.value
                    and "-" not in fourth.value
                    and fourth.value == fourth.value.lower()), (name, seen)
        assert seen >= 1, name


class TestAdvBillingAuditRows:
    def test_audit_rows_name_record(self, conn, env):
        pc = call_action(ACTIONS["health-add-procedure-code"], conn, ns(
            company_id=env["company_id"], code="99213",
            code_type="CPT", description="Office visit",
            category=None, default_fee="150.00", notes=None))
        assert is_ok(pc), pc
        _assert_single_audit(conn, pc["id"], "health-add-procedure-code",
                             "healthclaw_procedure_code")

        charge = call_action(ACTIONS["health-adv-add-charge"], conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            provider_id=env["provider_id"], procedure_code_id=None,
            service_date="2026-03-15", cpt_code="99213", icd10_codes=None,
            description=None, quantity="1", unit_fee="150.00", notes=None))
        assert is_ok(charge), charge
        _assert_single_audit(conn, charge["id"], "health-add-charge",
                             "healthclaw_charge")

        claim = call_action(ACTIONS["health-adv-add-claim"], conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            payer_name="Acme Health", payer_id_number=None,
            policy_number=None, group_number=None, claim_number=None,
            claim_date="2026-03-20",
            charge_ids=json.dumps([charge["id"]]), notes=None))
        assert is_ok(claim), claim
        _assert_single_audit(conn, claim["id"], "health-add-claim",
                             "healthclaw_claim")

        submitted = call_action(ACTIONS["health-adv-submit-claim"], conn, ns(
            claim_id=claim["id"]))
        assert is_ok(submitted), submitted
        _assert_single_audit(conn, claim["id"], "health-submit-claim",
                             "healthclaw_claim")


class TestAdvLabAuditRows:
    def test_audit_rows_name_record(self, conn, env):
        test = call_action(ACTIONS["health-adv-add-lab-test"], conn, ns(
            company_id=env["company_id"], test_name="CBC",
            test_code="CBC", loinc_code=None, category="hematology",
            specimen_type="blood", reference_range="4.5-11.0",
            unit="x10^9/L", turnaround_hours=24, base_price="45.50",
            notes=None))
        assert is_ok(test), test
        _assert_single_audit(conn, test["id"], "health-add-lab-test",
                             "healthclaw_lab_test")

        order = call_action(ACTIONS["health-adv-add-lab-order"], conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            ordering_provider="Dr. Test Provider",
            lab_test_id=test["id"], order_date="2026-03-10",
            priority="routine", clinical_notes=None, fasting_required=1,
            notes=None))
        assert is_ok(order), order
        _assert_single_audit(conn, order["id"], "health-add-lab-order",
                             "healthclaw_lab_order")

        result = call_action(ACTIONS["health-adv-add-lab-result"], conn, ns(
            company_id=env["company_id"], lab_order_id=order["id"],
            result_value="12.1", result_unit="x10^9/L",
            reference_range="4.5-11.0", is_abnormal=1, is_critical=0,
            performed_by="Tech", verified_by="Dr",
            result_date="2026-03-11", result_notes=None))
        assert is_ok(result), result
        _assert_single_audit(conn, result["id"], "health-add-lab-result",
                             "healthclaw_lab_result")

        marked = call_action(ACTIONS["health-mark-lab-critical"], conn, ns(
            lab_result_id=result["id"], company_id=None))
        assert is_ok(marked), marked
        _assert_single_audit(conn, result["id"], "health-mark-lab-critical",
                             "healthclaw_lab_result")


class TestAdvPharmacyAuditRows:
    def test_audit_rows_name_record(self, conn, env):
        med = call_action(ACTIONS["health-add-medication"], conn, ns(
            company_id=env["company_id"], name="Amoxicillin",
            generic_name=None, ndc_code=None, dea_schedule=None,
            dosage_form=None, strength=None, manufacturer=None,
            unit_price="12.75", quantity_on_hand=None, reorder_level=None,
            notes=None, limit=50, offset=0))
        assert is_ok(med), med
        _assert_single_audit(conn, med["id"], "health-add-medication",
                             "healthclaw_medication")

        updated = call_action(ACTIONS["health-update-medication"], conn, ns(
            medication_id=med["id"], name=None, generic_name=None,
            ndc_code=None, dosage_form=None, strength=None,
            manufacturer=None, notes="Audit trail check",
            dea_schedule=None, unit_price=None, quantity_on_hand=None,
            reorder_level=None, company_id=None, limit=50, offset=0))
        assert is_ok(updated), updated
        _assert_single_audit(conn, med["id"], "health-update-medication",
                             "healthclaw_medication")

        rx = call_action(ACTIONS["health-adv-add-prescription"], conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            prescriber_id=env["provider_id"], medication_id=med["id"],
            rx_number=None, dosage="500mg", frequency="BID", route=None,
            quantity_prescribed=20, refills_authorized=1, dea_number=None,
            prescribed_date="2026-03-12", expiry_date=None, notes=None))
        assert is_ok(rx), rx
        _assert_single_audit(conn, rx["id"], "health-add-prescription",
                             "healthclaw_prescription")


class TestAdvReportsV2AuditRows:
    def test_audit_rows_name_record(self, conn, env):
        charge = call_action(ACTIONS["health-adv-add-charge"], conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            provider_id=env["provider_id"], procedure_code_id=None,
            service_date="2026-03-15", cpt_code="99213", icd10_codes=None,
            description=None, quantity="1", unit_fee="150.00", notes=None))
        assert is_ok(charge), charge

        with_lines = call_action(ACTIONS["health-adv-add-claim"], conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            payer_name="Acme Health", payer_id_number=None,
            policy_number=None, group_number=None, claim_number=None,
            claim_date="2026-03-20",
            charge_ids=json.dumps([charge["id"]]), notes=None))
        assert is_ok(with_lines), with_lines
        line = call_action(ACTIONS["health-add-claim-line"], conn, ns(
            claim_id=with_lines["id"], charge_id=charge["id"],
            cpt_code="99213", line_number="1", modifiers=None,
            diagnosis_pointers="1", units="1", charge_amount="150.00",
            allowed_amount=None, paid_amount=None, adjustment_amount=None,
            patient_amount=None, denial_reason=None, remark_codes=None))
        assert is_ok(line), line

        batch = call_action(ACTIONS["health-batch-submit-claims"], conn, ns(
            company_id=env["company_id"]))
        assert is_ok(batch), batch
        assert with_lines["id"] in batch["submitted_claim_ids"]
        _assert_single_audit(conn, with_lines["id"],
                             "health-batch-submit-claims", "healthclaw_claim")

        rule = call_action(ACTIONS["health-add-scheduling-rule"], conn, ns(
            company_id=env["company_id"], rule_name="Buffer fifteen",
            rule_type="buffer_time", rule_value="15", provider_id=None))
        assert is_ok(rule), rule
        _assert_single_audit(conn, rule["id"], "health-add-scheduling-rule",
                             "healthclaw_scheduling_rule")


class TestComplianceAuditRows:
    def test_audit_rows_name_record(self, conn, env):
        gfe = call_action(
            ACTIONS["health-generate-good-faith-estimate"], conn, ns(
                company_id=env["company_id"], patient_id=env["patient_id"],
                procedure_codes=json.dumps(["99213"]), provider_id=None,
                diagnosis_codes=None, payer_id=None, notes=None,
                limit=50, offset=0))
        assert is_ok(gfe), gfe
        _assert_single_audit(conn, gfe["id"],
                             "health-generate-good-faith-estimate",
                             "healthclaw_good_faith_estimate")

        provided = call_action(
            ACTIONS["health-provide-good-faith-estimate"], conn, ns(
                estimate_id=gfe["id"], limit=50, offset=0))
        assert is_ok(provided), provided
        _assert_single_audit(conn, gfe["id"],
                             "health-provide-good-faith-estimate",
                             "healthclaw_good_faith_estimate")

        breach = call_action(ACTIONS["health-add-breach-incident"], conn, ns(
            company_id=env["company_id"], discovery_date="2026-02-01",
            incident_date="2026-01-28", description="Laptop left in taxi",
            phi_type="demographics", individuals_affected=25,
            risk_level="high", notification_required="1",
            remediation="Remote wipe issued", status=None))
        assert is_ok(breach), breach
        _assert_single_audit(conn, breach["id"], "health-add-breach-incident",
                             "healthclaw_breach_incident")

        updated = call_action(
            ACTIONS["health-update-breach-incident"], conn, ns(
                breach_id=breach["id"], description=None, phi_type=None,
                remediation="Laptop recovered", notification_sent_date=None,
                hhs_report_date=None, incident_date=None, risk_level=None,
                status=None, individuals_affected=None,
                notification_required=None, hhs_reported=None))
        assert is_ok(updated), updated
        _assert_single_audit(conn, breach["id"],
                             "health-update-breach-incident",
                             "healthclaw_breach_incident")


class TestInventoryAuditRows:
    def test_audit_rows_name_record(self, conn, env):
        formulary = call_action(ACTIONS["health-add-formulary"], conn, ns(
            company_id=env["company_id"],
            formulary_name="Audit Formulary 2026",
            description=None, effective_date="2026-01-01",
            expiration_date=None, formulary_status=None, notes=None,
            limit=50, offset=0))
        assert is_ok(formulary), formulary
        _assert_single_audit(conn, formulary["id"], "health-add-formulary",
                             "healthclaw_formulary")

        updated = call_action(ACTIONS["health-update-formulary"], conn, ns(
            formulary_id=formulary["id"], formulary_name=None,
            description="Audit trail check", effective_date=None,
            expiration_date=None, formulary_status=None,
            limit=50, offset=0))
        assert is_ok(updated), updated
        _assert_single_audit(conn, formulary["id"],
                             "health-update-formulary", "healthclaw_formulary")

        med = call_action(ACTIONS["health-add-medication"], conn, ns(
            company_id=env["company_id"], name="Audit Med",
            generic_name=None, ndc_code=None, dea_schedule=None,
            dosage_form=None, strength=None, manufacturer=None,
            unit_price="5.00", quantity_on_hand=None, reorder_level=None,
            notes=None, limit=50, offset=0))
        assert is_ok(med), med
        rx = call_action(ACTIONS["health-adv-add-prescription"], conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            prescriber_id=env["provider_id"], medication_id=med["id"],
            rx_number=None, dosage="10mg", frequency="daily", route=None,
            quantity_prescribed=30, refills_authorized=0, dea_number=None,
            prescribed_date="2026-03-15", expiry_date=None, notes=None))
        assert is_ok(rx), rx

        dispensing = call_action(ACTIONS["health-add-dispensing"], conn, ns(
            company_id=env["company_id"], prescription_id=rx["id"],
            patient_id=env["patient_id"],
            dispensed_by_id=env["provider_id"],
            dispensed_date="2026-03-20", quantity="30",
            formulary_item_id=None, item_id=None, lot_number=None,
            expiration_date=None, ndc_code=None, directions=None,
            refill_number=None, notes=None, limit=50, offset=0))
        assert is_ok(dispensing), dispensing
        _assert_single_audit(conn, dispensing["id"], "health-add-dispensing",
                             "healthclaw_dispensing")

        cancelled = call_action(ACTIONS["health-cancel-dispensing"], conn, ns(
            dispensing_id=dispensing["id"]))
        assert is_ok(cancelled), cancelled
        _assert_single_audit(conn, dispensing["id"],
                             "health-cancel-dispensing", "healthclaw_dispensing")


class TestLabAuditRows:
    def test_audit_rows_name_record(self, conn, env):
        order = call_action(ACTIONS["health-add-lab-order"], conn, ns(
            company_id=env["company_id"], encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            ordering_provider_id=env["provider_id"],
            order_date="2026-03-15", priority="routine",
            fasting_required=None, specimen_type="blood",
            clinical_indication="Annual screening", collection_date=None,
            received_date=None, notes=None, lab_order_status=None,
            status=None, order_id=None, limit=50, offset=0))
        assert is_ok(order), order
        _assert_single_audit(conn, order["id"], "health-add-lab-order",
                             "healthclaw_lab_order")

        updated = call_action(ACTIONS["health-update-lab-order"], conn, ns(
            lab_order_id=order["id"], clinical_indication=None,
            specimen_type=None, collection_date=None, received_date=None,
            notes="Audit trail check", priority=None,
            lab_order_status=None, fasting_required=None,
            limit=50, offset=0))
        assert is_ok(updated), updated
        _assert_single_audit(conn, order["id"], "health-update-lab-order",
                             "healthclaw_lab_order")

        test = call_action(ACTIONS["health-add-lab-test"], conn, ns(
            lab_order_id=order["id"], test_code="CBC",
            test_name="Complete Blood Count", cpt_code=None,
            limit=50, offset=0))
        assert is_ok(test), test
        _assert_single_audit(conn, test["id"], "health-add-lab-test",
                             "healthclaw_lab_test")

        result = call_action(ACTIONS["health-add-lab-result"], conn, ns(
            lab_test_id=test["id"], component_name="Hemoglobin",
            result_value="13.2", unit="g/dL", reference_low="12.0",
            reference_high="16.0", flag="normal",
            result_date="2026-03-16", performed_by_id=None,
            verified_by_id=None, notes=None, limit=50, offset=0))
        assert is_ok(result), result
        _assert_single_audit(conn, result["id"], "health-add-lab-result",
                             "healthclaw_lab_result")


class TestProviderMgmtAuditRows:
    def test_audit_rows_name_record(self, conn, env):
        cred = call_action(
            ACTIONS["health-add-provider-credential"], conn, ns(
                company_id=env["company_id"],
                provider_id=env["provider_id"],
                credential_type="medical_license",
                credential_number="LIC-AUDIT-1",
                issuing_authority="State Board", issue_date="2020-01-01",
                expiration_date="2030-01-01", verification_date=None,
                verified_by=None, notes=None, status=None, days=None,
                limit=50, offset=0))
        assert is_ok(cred), cred
        _assert_single_audit(conn, cred["id"],
                             "health-add-provider-credential",
                             "healthclaw_provider_credential")


class TestRcmAuditRows:
    def test_audit_rows_name_record(self, conn, env):
        payer = call_action(ACTIONS["health-add-payer"], conn, ns(
            company_id=env["company_id"], name="Audit Payer",
            payer_type="commercial", edi_payer_id=None,
            electronic_filing_id=None, address=None, city=None, state=None,
            zip_code=None, phone=None, claims_address=None, claims_city=None,
            claims_state=None, claims_zip=None, submission_method=None,
            timely_filing_days=None, era_enrollment=None, notes=None,
            limit=50, offset=0))
        assert is_ok(payer), payer
        _assert_single_audit(conn, payer["id"], "health-add-payer",
                             "healthclaw_payer")

        updated = call_action(ACTIONS["health-update-payer"], conn, ns(
            payer_id=payer["id"], name="Audit Payer Renamed",
            payer_type=None, edi_payer_id=None, electronic_filing_id=None,
            address=None, city=None, state=None, zip_code=None, phone=None,
            claims_address=None, claims_city=None, claims_state=None,
            claims_zip=None, submission_method=None, timely_filing_days=None,
            era_enrollment=None, payer_status=None, notes=None,
            limit=50, offset=0))
        assert is_ok(updated), updated
        _assert_single_audit(conn, payer["id"], "health-update-payer",
                             "healthclaw_payer")

        insurance = call_action(
            ACTIONS["health-add-patient-insurance"], conn, ns(
                patient_id=env["patient_id"],
                company_id=env["company_id"], insurance_type="primary",
                payer_name="Audit Payer", payer_id=None, plan_name=None,
                plan_type=None, group_number=None, member_id="MEM-AUDIT",
                subscriber_name=None, subscriber_dob=None,
                subscriber_relationship=None, copay_amount=None,
                deductible=None, deductible_met=None, out_of_pocket_max=None,
                effective_date="2026-01-01", termination_date=None,
                preauth_required=None, status=None, limit=50, offset=0))
        assert is_ok(insurance), insurance

        check = call_action(
            ACTIONS["health-record-eligibility-check"], conn, ns(
                patient_id=env["patient_id"],
                patient_insurance_id=insurance["id"], payer_id=None,
                coverage_status="active", check_method="electronic",
                copay=None, deductible=None, deductible_met=None,
                coinsurance_pct=None, out_of_pocket_max=None, oop_met=None,
                plan_begin_date=None, plan_end_date=None, in_network=None,
                prior_auth_required=None, notes=None, checked_by=None,
                limit=50, offset=0))
        assert is_ok(check), check
        _assert_single_audit(conn, check["id"],
                             "health-record-eligibility-check",
                             "healthclaw_eligibility_check")


class TestReferralsAuditRows:
    def test_audit_rows_name_record(self, conn, env):
        referral = call_action(ACTIONS["health-add-referral"], conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            encounter_id=env["encounter_id"],
            referring_provider_id=env["provider_id"],
            referred_to_provider="Dr. Audit Specialist",
            referred_to_specialty="Cardiology", referred_to_facility=None,
            referred_to_phone=None, referred_to_fax=None,
            referral_date="2026-03-15", expiration_date=None,
            reason="Chest pain eval", diagnosis_id=None, priority="urgent",
            insurance_id=None, prior_auth_required=None, prior_auth_id=None,
            notes=None, referral_status=None, status=None))
        assert is_ok(referral), referral
        _assert_single_audit(conn, referral["id"], "health-add-referral",
                             "healthclaw_referral")

        updated = call_action(ACTIONS["health-update-referral"], conn, ns(
            referral_id=referral["id"], referred_to_provider=None,
            referred_to_specialty=None, referred_to_facility=None,
            referred_to_phone=None, referred_to_fax=None, referral_date=None,
            expiration_date=None, reason=None, notes="Audit trail check",
            priority=None, referral_status=None, diagnosis_id=None,
            insurance_id=None, prior_auth_id=None, prior_auth_required=None,
            status=None))
        assert is_ok(updated), updated
        _assert_single_audit(conn, referral["id"], "health-update-referral",
                             "healthclaw_referral")

        insurance = call_action(
            ACTIONS["health-add-patient-insurance"], conn, ns(
                patient_id=env["patient_id"],
                company_id=env["company_id"], insurance_type="primary",
                payer_name="Audit Payer", payer_id=None, plan_name=None,
                plan_type=None, group_number=None, member_id="MEM-AUDIT",
                subscriber_name=None, subscriber_dob=None,
                subscriber_relationship=None, copay_amount=None,
                deductible=None, deductible_met=None, out_of_pocket_max=None,
                effective_date="2026-01-01", termination_date=None,
                preauth_required=None, status=None, limit=50, offset=0))
        assert is_ok(insurance), insurance

        auth = call_action(ACTIONS["health-add-prior-auth"], conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            insurance_id=insurance["id"],
            requesting_provider_id=env["provider_id"], auth_number=None,
            service_type="procedure", cpt_codes="99213",
            icd10_codes="J06.9", description="Office visit pre-auth",
            units_requested=2, request_date="2026-03-15",
            effective_date="2026-03-15", expiration_date="2026-06-15",
            notes=None, auth_status=None, status=None))
        assert is_ok(auth), auth
        _assert_single_audit(conn, auth["id"], "health-add-prior-auth",
                             "healthclaw_prior_auth")


def test_no_audit_row_is_keyed_by_company(conn, env):
    company_id = env["company_id"]

    pc = call_action(ACTIONS["health-add-procedure-code"], conn, ns(
        company_id=company_id, code="99213", code_type="CPT",
        description="Office visit", category=None, default_fee="150.00",
        notes=None))
    assert is_ok(pc), pc

    lab_test = call_action(ACTIONS["health-adv-add-lab-test"], conn, ns(
        company_id=company_id, test_name="CBC", test_code="CBC",
        loinc_code=None, category="hematology", specimen_type="blood",
        reference_range="4.5-11.0", unit="x10^9/L", turnaround_hours=24,
        base_price="45.50", notes=None))
    assert is_ok(lab_test), lab_test

    med = call_action(ACTIONS["health-add-medication"], conn, ns(
        company_id=company_id, name="Amoxicillin", generic_name=None,
        ndc_code=None, dea_schedule=None, dosage_form=None, strength=None,
        manufacturer=None, unit_price="12.75", quantity_on_hand=None,
        reorder_level=None, notes=None, limit=50, offset=0))
    assert is_ok(med), med

    rule = call_action(ACTIONS["health-add-scheduling-rule"], conn, ns(
        company_id=company_id, rule_name="Buffer fifteen",
        rule_type="buffer_time", rule_value="15", provider_id=None))
    assert is_ok(rule), rule

    baa = call_action(ACTIONS["health-add-baa"], conn, ns(
        company_id=company_id, vendor_name="Audit Vendor",
        vendor_contact=None, agreement_date="2026-01-01",
        expiration_date=None, review_date=None, phi_categories=None,
        breach_notification_days=None, limit=50, offset=0))
    assert is_ok(baa), baa

    formulary = call_action(ACTIONS["health-add-formulary"], conn, ns(
        company_id=company_id, formulary_name="Audit Formulary 2026",
        description=None, effective_date="2026-01-01", expiration_date=None,
        formulary_status=None, notes=None, limit=50, offset=0))
    assert is_ok(formulary), formulary

    order = call_action(ACTIONS["health-add-lab-order"], conn, ns(
        company_id=company_id, encounter_id=env["encounter_id"],
        patient_id=env["patient_id"],
        ordering_provider_id=env["provider_id"], order_date="2026-03-15",
        priority="routine", fasting_required=None, specimen_type="blood",
        clinical_indication="Annual screening", collection_date=None,
        received_date=None, notes=None, lab_order_status=None, status=None,
        order_id=None, limit=50, offset=0))
    assert is_ok(order), order

    cred = call_action(ACTIONS["health-add-provider-credential"], conn, ns(
        company_id=company_id, provider_id=env["provider_id"],
        credential_type="medical_license", credential_number="LIC-AUDIT-1",
        issuing_authority="State Board", issue_date="2020-01-01",
        expiration_date="2030-01-01", verification_date=None,
        verified_by=None, notes=None, status=None, days=None,
        limit=50, offset=0))
    assert is_ok(cred), cred

    payer = call_action(ACTIONS["health-add-payer"], conn, ns(
        company_id=company_id, name="Audit Payer", payer_type="commercial",
        edi_payer_id=None, electronic_filing_id=None, address=None, city=None,
        state=None, zip_code=None, phone=None, claims_address=None,
        claims_city=None, claims_state=None, claims_zip=None,
        submission_method=None, timely_filing_days=None, era_enrollment=None,
        notes=None, limit=50, offset=0))
    assert is_ok(payer), payer

    referral = call_action(ACTIONS["health-add-referral"], conn, ns(
        company_id=company_id, patient_id=env["patient_id"],
        encounter_id=env["encounter_id"],
        referring_provider_id=env["provider_id"],
        referred_to_provider="Dr. Audit Specialist",
        referred_to_specialty="Cardiology", referred_to_facility=None,
        referred_to_phone=None, referred_to_fax=None,
        referral_date="2026-03-15", expiration_date=None,
        reason="Chest pain eval", diagnosis_id=None, priority="urgent",
        insurance_id=None, prior_auth_required=None, prior_auth_id=None,
        notes=None, referral_status=None, status=None))
    assert is_ok(referral), referral

    t = Table("audit_log")
    keyed = conn.execute(
        Q.from_(t).select(
            t.skill, t.action, t.entity_type, t.entity_id, t.new_values
        ).where(Field("entity_id") == P()).get_sql(),
        (company_id,),
    ).fetchall()
    assert [dict(r) for r in keyed
            if dict(r)["skill"] == SKILL] == []

    skills = [r[0] for r in conn.execute(
        Q.from_(t).select(t.skill).get_sql()).fetchall()]
    assert [s for s in skills if s.startswith(TABLE_PREFIX)] == []
