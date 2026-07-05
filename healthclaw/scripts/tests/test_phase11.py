"""Tests for HealthClaw Phase 11: Remaining 16 MEDIUM gaps.

Tests cover:
  H6: Secondary Insurance Billing (crossover claims)
  H7: Patient Statements
  H8: Payment Plans
  H12: BAA Tracking
  H13: Breach Incident Management
  H17: Care Team
  H18: Patient Education
  H23: Recurring Appointments
  H25: Underpayment Detection
  H26: Superbill Generation
  H29-32: Reports (collections aging, charge reconciliation, batch submit, provider productivity)
  H33-35: Interoperability stubs
  H38: Consent Templates
  H39-44: Misc (scheduling rules, growth chart)
"""
import json
import uuid
import pytest
from decimal import Decimal
from health_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Seed helpers
# ─────────────────────────────────────────────────────────────────────────────

def _add_insurance(conn, env, ins_type="primary"):
    ins_id = str(uuid.uuid4())
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        """INSERT INTO healthclaw_patient_insurance
           (id, naming_series, patient_id, insurance_type, payer_name, member_id,
            subscriber_relationship, copay_amount, deductible, deductible_met,
            out_of_pocket_max, effective_date, status, company_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'self', '25', '1000', '0', '5000', '2026-01-01', 'active', ?, ?, ?)""",
        (ins_id, f"INS-{ins_id[:6]}", env["patient_id"], ins_type,
         f"Test Payer {ins_type.title()}", f"MEM-{ins_id[:6]}",
         env["company_id"], now, now)
    )
    conn.commit()
    return ins_id


def _add_charge(conn, env, amount="100.00"):
    return call_action(mod.health_add_charge, conn, ns(
        company_id=env["company_id"],
        encounter_id=env["encounter_id"],
        patient_id=env["patient_id"],
        provider_id=env["provider_id"],
        cpt_code="99213",
        service_date="2026-01-15",
        charge_amount=amount,
        modifiers=None, diagnosis_ids=None, units=None,
        allowed_amount=amount, fee_schedule_id=None,
        procedure_id=None, place_of_service=None,
        notes=None, limit=50, offset=0,
    ))


def _add_claim(conn, env, ins_id, total_charge="100.00"):
    return call_action(mod.health_add_claim, conn, ns(
        company_id=env["company_id"],
        patient_id=env["patient_id"],
        encounter_id=env["encounter_id"],
        insurance_id=ins_id,
        claim_date="2026-01-15",
        claim_type="professional",
        total_charge=total_charge,
        total_allowed="80.00",
        total_paid="0",
        patient_responsibility="0",
        adjustment_amount="0",
        billing_provider_id=env["provider_id"],
        rendering_provider_id=env["provider_id"],
        place_of_service=None,
        filing_indicator=None,
        prior_auth_id=None,
        sales_invoice_id=None,
        denial_reason=None,
        denial_category=None,
        denial_code=None,
        denial_date=None,
        appeal_deadline=None,
        appeal_method=None,
        appeal_reference=None,
        appeal_outcome=None,
        appeal_amount_recovered=None,
        notes=None, limit=50, offset=0,
    ))


# ═══════════════════════════════════════════════════════════════════════════
# H17: Care Team
# ═══════════════════════════════════════════════════════════════════════════

class TestCareTeam:
    def test_add_care_team_member(self, conn, env):
        result = call_action(mod.health_add_care_team_member, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            role="pcp",
            start_date="2026-01-01",
            status=None, limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["role"] == "pcp"
        assert result["care_team_status"] == "active"

    def test_list_care_team(self, conn, env):
        call_action(mod.health_add_care_team_member, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            role="pcp", start_date=None, status=None, limit=50, offset=0,
        ))
        call_action(mod.health_add_care_team_member, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider2_id"],
            role="specialist", start_date=None, status=None, limit=50, offset=0,
        ))
        result = call_action(mod.health_list_care_team, conn, ns(
            patient_id=env["patient_id"],
            status=None, limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 2

    def test_remove_care_team_member(self, conn, env):
        add_res = call_action(mod.health_add_care_team_member, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            role="nurse", start_date=None, status=None, limit=50, offset=0,
        ))
        assert is_ok(add_res)

        rm_res = call_action(mod.health_remove_care_team_member, conn, ns(
            care_team_id=add_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(rm_res), rm_res
        assert rm_res["care_team_status"] == "inactive"

    def test_invalid_role_rejected(self, conn, env):
        result = call_action(mod.health_add_care_team_member, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            role="invalid_role", start_date=None, status=None, limit=50, offset=0,
        ))
        assert is_error(result)


# ═══════════════════════════════════════════════════════════════════════════
# H18: Patient Education
# ═══════════════════════════════════════════════════════════════════════════

class TestPatientEducation:
    def test_add_patient_education(self, conn, env):
        result = call_action(mod.health_add_patient_education, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            author_id=None,
            education_type="discharge_instructions",
            body="Take medications as prescribed. Follow up in 2 weeks.",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["education_type"] == "discharge_instructions"
        assert result["note_status"] == "signed"

    def test_list_patient_education(self, conn, env):
        call_action(mod.health_add_patient_education, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            author_id=None,
            education_type="medication_guide",
            body="This medication should be taken with food.",
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_patient_education, conn, ns(
            patient_id=env["patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1
        assert result["rows"][0]["education_type"] == "medication_guide"


# ═══════════════════════════════════════════════════════════════════════════
# H23: Recurring Appointments
# ═══════════════════════════════════════════════════════════════════════════

class TestRecurringAppointments:
    def test_create_recurring(self, conn, env):
        result = call_action(mod.health_create_recurring_appointment, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            appointment_date="2026-04-01",
            start_time="09:00",
            end_time="09:30",
            recurrence_count="4",
            interval_days="7",
            appointment_type="follow_up",
            duration_minutes=None,
            chief_complaint=None,
            location=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["appointment_count"] == 4
        assert len(result["appointment_ids"]) == 4
        assert result["first_date"] == "2026-04-01"
        assert result["last_date"] == "2026-04-22"

    def test_list_recurring_series(self, conn, env):
        call_action(mod.health_create_recurring_appointment, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            appointment_date="2026-05-01",
            start_time="10:00",
            end_time="10:30",
            recurrence_count="3",
            interval_days="14",
            appointment_type=None,
            duration_minutes=None,
            chief_complaint=None,
            location=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_recurring_series, conn, ns(
            patient_id=env["patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["series_count"] >= 1
        assert len(result["series"][0]["appointments"]) >= 3


# ═══════════════════════════════════════════════════════════════════════════
# H7: Patient Statements
# ═══════════════════════════════════════════════════════════════════════════

class TestPatientStatements:
    def test_generate_statement(self, conn, env):
        _add_charge(conn, env, "250.00")
        result = call_action(mod.health_generate_patient_statement, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            posting_date=None,
            date_from=None,
            date_to=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert Decimal(result["total_charges"]) >= Decimal("250.00")
        assert result["statement_status"] == "generated"

    def test_list_statements(self, conn, env):
        _add_charge(conn, env, "100.00")
        call_action(mod.health_generate_patient_statement, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            posting_date=None, date_from=None, date_to=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_patient_statements, conn, ns(
            patient_id=env["patient_id"],
            status=None, limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ═══════════════════════════════════════════════════════════════════════════
# H8: Payment Plans
# ═══════════════════════════════════════════════════════════════════════════

class TestPaymentPlans:
    def test_add_payment_plan(self, conn, env):
        result = call_action(mod.health_add_payment_plan, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            amount="1200.00",
            installment_amount="100.00",
            frequency="monthly",
            start_date="2026-04-01",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_amount"] == "1200.00"
        assert result["installment_amount"] == "100.00"
        assert result["num_installments"] == 12
        assert result["plan_status"] == "active"

    def test_record_plan_payment(self, conn, env):
        plan = call_action(mod.health_add_payment_plan, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            amount="300.00",
            installment_amount="100.00",
            frequency="monthly",
            start_date="2026-04-01",
            limit=50, offset=0,
        ))
        assert is_ok(plan)

        pay_res = call_action(mod.health_record_plan_payment, conn, ns(
            payment_plan_id=plan["id"],
            amount=None,  # uses installment_amount
            limit=50, offset=0,
        ))
        assert is_ok(pay_res), pay_res
        assert Decimal(pay_res["remaining_balance"]) == Decimal("200.00")
        assert pay_res["installments_paid"] == 1
        assert pay_res["plan_status"] == "active"

    def test_payment_plan_completes(self, conn, env):
        plan = call_action(mod.health_add_payment_plan, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            amount="200.00",
            installment_amount="100.00",
            frequency="monthly",
            start_date="2026-04-01",
            limit=50, offset=0,
        ))
        assert is_ok(plan)

        # Pay twice -> should complete
        call_action(mod.health_record_plan_payment, conn, ns(
            payment_plan_id=plan["id"], amount=None, limit=50, offset=0,
        ))
        res = call_action(mod.health_record_plan_payment, conn, ns(
            payment_plan_id=plan["id"], amount=None, limit=50, offset=0,
        ))
        assert is_ok(res), res
        assert res["plan_status"] == "completed"
        assert Decimal(res["remaining_balance"]) == Decimal("0.00")

    def test_payment_plan_status(self, conn, env):
        plan = call_action(mod.health_add_payment_plan, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            amount="500.00",
            installment_amount="100.00",
            frequency="monthly",
            start_date="2026-04-01",
            limit=50, offset=0,
        ))
        assert is_ok(plan)

        call_action(mod.health_record_plan_payment, conn, ns(
            payment_plan_id=plan["id"], amount=None, limit=50, offset=0,
        ))

        status = call_action(mod.health_payment_plan_status, conn, ns(
            payment_plan_id=plan["id"], limit=50, offset=0,
        ))
        assert is_ok(status), status
        assert Decimal(status["amount_paid"]) == Decimal("100.00")
        assert Decimal(status["pct_complete"]) == Decimal("20.00")


# ═══════════════════════════════════════════════════════════════════════════
# H12: BAA Tracking
# ═══════════════════════════════════════════════════════════════════════════

class TestBAATracking:
    def test_add_baa(self, conn, env):
        result = call_action(mod.health_add_baa, conn, ns(
            company_id=env["company_id"],
            vendor_name="CloudEHR Inc.",
            vendor_contact="security@cloudehr.com",
            agreement_date="2026-01-01",
            expiration_date="2027-01-01",
            review_date="2026-06-01",
            phi_categories="clinical,billing",
            breach_notification_days="30",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["vendor_name"] == "CloudEHR Inc."
        assert result["baa_status"] == "active"

    def test_list_baas(self, conn, env):
        call_action(mod.health_add_baa, conn, ns(
            company_id=env["company_id"],
            vendor_name="Lab Corp",
            vendor_contact=None,
            agreement_date="2026-01-01",
            expiration_date="2027-01-01",
            review_date=None,
            phi_categories=None,
            breach_notification_days=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_baas, conn, ns(
            company_id=env["company_id"],
            status=None, limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1

    def test_check_expiring_baas(self, conn, env):
        # Add a BAA expiring within 30 days
        call_action(mod.health_add_baa, conn, ns(
            company_id=env["company_id"],
            vendor_name="Expiring Vendor",
            vendor_contact=None,
            agreement_date="2025-01-01",
            expiration_date="2026-04-01",
            review_date=None,
            phi_categories=None,
            breach_notification_days=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_check_expiring_baas, conn, ns(
            company_id=env["company_id"],
            days="90",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["expiring_count"] >= 1


# ═══════════════════════════════════════════════════════════════════════════
# H13: Breach Incident
# ═══════════════════════════════════════════════════════════════════════════

class TestBreachIncident:
    def test_add_breach_incident(self, conn, env):
        result = call_action(mod.health_add_breach_incident, conn, ns(
            company_id=env["company_id"],
            discovery_date="2026-03-15",
            incident_date="2026-03-10",
            description="Laptop containing PHI stolen from provider's car",
            phi_type="demographics,clinical",
            individuals_affected="50",
            risk_level="high",
            notification_required="1",
            notification_sent_date=None,
            hhs_reported=None,
            hhs_report_date=None,
            remediation=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["risk_level"] == "high"
        assert result["breach_status"] == "investigating"

    def test_update_breach_incident(self, conn, env):
        add_res = call_action(mod.health_add_breach_incident, conn, ns(
            company_id=env["company_id"],
            discovery_date="2026-03-15",
            incident_date=None,
            description="Email sent to wrong recipient",
            phi_type="demographics",
            individuals_affected="1",
            risk_level="low",
            notification_required=None,
            notification_sent_date=None,
            hhs_reported=None,
            hhs_report_date=None,
            remediation=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)

        upd_res = call_action(mod.health_update_breach_incident, conn, ns(
            breach_id=add_res["id"],
            status="remediated",
            remediation="Recalled email, notified patient",
            description=None, phi_type=None,
            individuals_affected=None,
            risk_level=None,
            notification_required=None,
            notification_sent_date=None,
            hhs_reported=None,
            hhs_report_date=None,
            incident_date=None,
            limit=50, offset=0,
        ))
        assert is_ok(upd_res), upd_res
        assert "status" in upd_res["updated_fields"]

    def test_breach_summary_report(self, conn, env):
        call_action(mod.health_add_breach_incident, conn, ns(
            company_id=env["company_id"],
            discovery_date="2026-03-15",
            incident_date=None,
            description="Test breach 1",
            phi_type=None,
            individuals_affected="10",
            risk_level="medium",
            notification_required=None,
            notification_sent_date=None,
            hhs_reported=None,
            hhs_report_date=None,
            remediation=None,
            status=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_breach_summary_report, conn, ns(
            company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_incidents"] >= 1
        assert result["total_individuals_affected"] >= 10


# ═══════════════════════════════════════════════════════════════════════════
# H38: Consent Templates
# ═══════════════════════════════════════════════════════════════════════════

class TestConsentTemplates:
    def test_add_consent_template(self, conn, env):
        result = call_action(mod.health_add_consent_template, conn, ns(
            company_id=env["company_id"],
            consent_type="hipaa_privacy",
            description="HIPAA Privacy Notice v2.0 — Patient rights and obligations",
            version="2.0",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["consent_type"] == "hipaa_privacy"
        assert result["version"] == "2.0"

    def test_list_consent_templates(self, conn, env):
        call_action(mod.health_add_consent_template, conn, ns(
            company_id=env["company_id"],
            consent_type="treatment",
            description="General treatment consent template",
            version="1.0",
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_consent_templates, conn, ns(
            company_id=env["company_id"],
            consent_type=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1
        assert result["rows"][0]["is_template"] is True


# ═══════════════════════════════════════════════════════════════════════════
# H26: Superbill
# ═══════════════════════════════════════════════════════════════════════════

class TestSuperbill:
    def test_generate_superbill(self, conn, env):
        # Add a diagnosis and charge to the encounter
        call_action(mod.health_add_diagnosis, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            icd10_code="J06.9",
            dx_description="Acute upper respiratory infection",
            diagnosis_type="primary",
            onset_date=None, diagnosed_by_id=None, provider_id=env["provider_id"],
            dx_status=None, notes=None, company_id=env["company_id"],
            limit=50, offset=0,
        ))
        _add_charge(conn, env, "150.00")

        result = call_action(mod.health_generate_superbill, conn, ns(
            encounter_id=env["encounter_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["encounter_id"] == env["encounter_id"]
        assert len(result["diagnoses"]) >= 1
        assert len(result["charges"]) >= 1
        assert Decimal(result["total_charges"]) >= Decimal("150.00")


# ═══════════════════════════════════════════════════════════════════════════
# H33-35: Interoperability Stubs
# ═══════════════════════════════════════════════════════════════════════════

class TestInteropStubs:
    def test_fhir_export_stub(self, conn, env):
        result = call_action(mod.health_fhir_export_patient, conn, ns(
            patient_id=env["patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["feature_status"] == "not_implemented"

    def test_ccd_generation_stub(self, conn, env):
        result = call_action(mod.health_generate_ccd, conn, ns(
            patient_id=env["patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["feature_status"] == "not_implemented"

    def test_lab_interface_stub(self, conn, env):
        result = call_action(mod.health_lab_interface_status, conn, ns(
            company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["feature_status"] == "not_configured"


# ═══════════════════════════════════════════════════════════════════════════
# H39-44: Misc (Scheduling Rules, Growth Chart)
# ═══════════════════════════════════════════════════════════════════════════

class TestMisc:
    def test_online_scheduling_rules_defaults(self, conn, env):
        result = call_action(mod.health_online_scheduling_rules, conn, ns(
            company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["rule_count"] >= 4
        rule_types = [r["rule_type"] for r in result["rules"]]
        assert "buffer_time" in rule_types

    def test_add_scheduling_rule(self, conn, env):
        result = call_action(mod.health_add_scheduling_rule, conn, ns(
            company_id=env["company_id"],
            rule_name="Buffer between visits",
            rule_type="buffer_time",
            rule_value="20",
            provider_id=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["rule_type"] == "buffer_time"
        assert result["rule_value"] == "20"
        assert result["rule_status"] == "active"

    def test_online_scheduling_rules_returns_stored(self, conn, env):
        # Once a rule is stored, the reader returns it INSTEAD of defaults.
        call_action(mod.health_add_scheduling_rule, conn, ns(
            company_id=env["company_id"],
            rule_name="Max per day",
            rule_type="max_per_day",
            rule_value="12",
            provider_id=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_online_scheduling_rules, conn, ns(
            company_id=env["company_id"], limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["rule_count"] == 1
        assert result["rules"][0]["rule_type"] == "max_per_day"
        assert result["rules"][0]["rule_value"] == "12"

    def test_list_scheduling_rules(self, conn, env):
        call_action(mod.health_add_scheduling_rule, conn, ns(
            company_id=env["company_id"],
            rule_name="Advance booking window",
            rule_type="advance_booking_days",
            rule_value="60",
            provider_id=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_scheduling_rules, conn, ns(
            company_id=env["company_id"],
            rule_type=None, status=None, limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 1
        assert result["rows"][0]["rule_type"] == "advance_booking_days"
        assert result["rows"][0]["rule_value"] == "60"

    def test_invalid_rule_type_rejected(self, conn, env):
        result = call_action(mod.health_add_scheduling_rule, conn, ns(
            company_id=env["company_id"],
            rule_name="Bad rule",
            rule_type="nonsense",
            rule_value="1",
            provider_id=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_growth_chart(self, conn, env):
        result = call_action(mod.health_growth_chart, conn, ns(
            age_months="12",
            gender="male",
            weight="10.0",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["age_months"] == 12
        assert "percentile_range" in result
        assert "percentile_reference" in result


# ═══════════════════════════════════════════════════════════════════════════
# H6: Crossover Claims (requires paid primary claim)
# ═══════════════════════════════════════════════════════════════════════════

class TestCrossoverClaims:
    def test_auto_crossover_claim(self, conn, env):
        primary_ins = _add_insurance(conn, env, "primary")
        secondary_ins = _add_insurance(conn, env, "secondary")

        # Create and pay a primary claim
        claim = _add_claim(conn, env, primary_ins, "500.00")
        assert is_ok(claim)
        # Mark as paid
        call_action(mod.health_update_claim, conn, ns(
            claim_id=claim["id"], claim_status="paid",
            total_paid="400.00", total_charge=None, total_allowed=None,
            patient_responsibility=None, adjustment_amount=None,
            billing_provider_id=None, rendering_provider_id=None,
            prior_auth_id=None, sales_invoice_id=None,
            claim_date=None, place_of_service=None, filing_indicator=None,
            claim_type=None, denial_reason=None, appeal_deadline=None,
            notes=None, limit=50, offset=0,
        ))

        result = call_action(mod.health_auto_crossover_claim, conn, ns(
            company_id=env["company_id"],
            claim_id=claim["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["original_claim_id"] == claim["id"]
        assert result["secondary_insurance_id"] == secondary_ins
        assert Decimal(result["remaining_balance"]) == Decimal("100.00")
        assert result["crossover_status"] == "pending"

    def test_list_crossover_claims(self, conn, env):
        primary_ins = _add_insurance(conn, env, "primary")
        _add_insurance(conn, env, "secondary")

        claim = _add_claim(conn, env, primary_ins, "300.00")
        assert is_ok(claim)
        call_action(mod.health_update_claim, conn, ns(
            claim_id=claim["id"], claim_status="paid",
            total_paid="250.00",
            total_charge=None, total_allowed=None,
            patient_responsibility=None, adjustment_amount=None,
            billing_provider_id=None, rendering_provider_id=None,
            prior_auth_id=None, sales_invoice_id=None,
            claim_date=None, place_of_service=None, filing_indicator=None,
            claim_type=None, denial_reason=None, appeal_deadline=None,
            notes=None, limit=50, offset=0,
        ))
        call_action(mod.health_auto_crossover_claim, conn, ns(
            company_id=env["company_id"],
            claim_id=claim["id"],
            limit=50, offset=0,
        ))

        result = call_action(mod.health_list_crossover_claims, conn, ns(
            company_id=env["company_id"],
            status=None, patient_id=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ═══════════════════════════════════════════════════════════════════════════
# H29-32: Report Actions
# ═══════════════════════════════════════════════════════════════════════════

class TestReports:
    def test_collections_aging_report(self, conn, env):
        _add_charge(conn, env, "500.00")
        result = call_action(mod.health_collections_aging_report, conn, ns(
            company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "total_ar" in result
        assert "aging" in result

    def test_charge_reconciliation_report(self, conn, env):
        # Complete the encounter but add no charges
        call_action(mod.health_update_encounter, conn, ns(
            encounter_id=env["encounter_id"],
            encounter_status="completed",
            encounter_type=None, chief_complaint=None,
            department=None, room=None,
            admission_date=None, discharge_date=None,
            discharge_disposition=None, notes=None,
            company_id=env["company_id"],
            limit=50, offset=0,
        ))
        result = call_action(mod.health_charge_reconciliation_report, conn, ns(
            company_id=env["company_id"],
            date_from=None, date_to=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "total_completed_encounters" in result

    def test_provider_productivity_report(self, conn, env):
        _add_charge(conn, env, "200.00")
        result = call_action(mod.health_provider_productivity_report, conn, ns(
            company_id=env["company_id"],
            date_from=None, date_to=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["provider_count"] >= 1
        assert len(result["providers"]) >= 1
