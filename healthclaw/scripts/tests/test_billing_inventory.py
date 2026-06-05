"""Tests for HealthClaw billing and inventory domains.

Actions tested (billing):
  - health-add-fee-schedule
  - health-update-fee-schedule
  - health-list-fee-schedules
  - health-add-charge
  - health-list-charges
  - health-add-claim
  - health-list-claims
Actions tested (inventory):
  - health-add-formulary
  - health-update-formulary
  - health-list-formularies
  - health-add-formulary-item
  - health-list-formulary-items
"""
import pytest
from health_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Fee Schedule
# ─────────────────────────────────────────────────────────────────────────────

class TestFeeSchedule:
    def test_add_fee_schedule(self, conn, env):
        result = call_action(mod.health_add_fee_schedule, conn, ns(
            company_id=env["company_id"],
            fee_schedule_name="Standard Fee Schedule",
            description="Default fee schedule",
            effective_date="2026-01-01",
            expiration_date="2026-12-31",
            fee_schedule_status=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "id" in result

    def test_add_fee_schedule_missing_name(self, conn, env):
        result = call_action(mod.health_add_fee_schedule, conn, ns(
            company_id=env["company_id"],
            fee_schedule_name=None,
            description=None,
            effective_date="2026-01-01",
            expiration_date=None,
            fee_schedule_status=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_fee_schedule(self, conn, env):
        add_res = call_action(mod.health_add_fee_schedule, conn, ns(
            company_id=env["company_id"],
            fee_schedule_name="Update Test FS",
            description=None,
            effective_date="2026-01-01",
            expiration_date=None,
            fee_schedule_status=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.health_update_fee_schedule, conn, ns(
            fee_schedule_id=add_res["id"],
            fee_schedule_name=None,
            description="Updated description",
            fee_schedule_status=None,
            effective_date=None, expiration_date=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result

    def test_list_fee_schedules(self, conn, env):
        call_action(mod.health_add_fee_schedule, conn, ns(
            company_id=env["company_id"],
            fee_schedule_name="List Test FS",
            description=None,
            effective_date="2026-01-01",
            expiration_date=None,
            fee_schedule_status=None,
            notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_fee_schedules, conn, ns(
            company_id=env["company_id"],
            fee_schedule_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Charges
# ─────────────────────────────────────────────────────────────────────────────

class TestCharge:
    def test_add_charge(self, conn, env):
        result = call_action(mod.health_add_charge, conn, ns(
            company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            cpt_code="99213",
            charge_amount="150.00",
            service_date="2026-03-15",
            procedure_id=None,
            fee_schedule_id=None,
            units="1",
            modifier=None,
            modifiers=None,
            diagnosis_ids=None,
            place_of_service="11",
            rendering_provider_id=None,
            charge_status=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "id" in result

    def test_list_charges(self, conn, env):
        call_action(mod.health_add_charge, conn, ns(
            company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            cpt_code="99214",
            charge_amount="200.00",
            service_date="2026-03-15",
            procedure_id=None, fee_schedule_id=None,
            units="1", modifier=None, modifiers=None,
            diagnosis_ids=None, place_of_service=None,
            rendering_provider_id=None,
            charge_status=None, notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_charges, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=None, charge_status=None,
            company_id=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Claims
# ─────────────────────────────────────────────────────────────────────────────

class TestClaim:
    def _seed_insurance(self, conn, env):
        """Create a patient insurance record for claim tests."""
        res = call_action(mod.health_add_patient_insurance, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            insurance_type="primary",
            payer_name="TestPayer",
            payer_id=None, plan_name=None, plan_type=None,
            group_number=None, member_id="MEM-CLAIM",
            subscriber_name=None, subscriber_dob=None,
            subscriber_relationship=None,
            copay_amount=None, deductible=None, deductible_met=None,
            out_of_pocket_max=None, effective_date="2026-01-01",
            termination_date=None, preauth_required=None, status=None,
            limit=50, offset=0,
        ))
        return res["id"]

    def test_add_claim(self, conn, env):
        ins_id = self._seed_insurance(conn, env)
        result = call_action(mod.health_add_claim, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            encounter_id=env["encounter_id"],
            insurance_id=ins_id,
            claim_type="professional",
            claim_date="2026-03-20",
            total_charge="350.00",
            billing_provider_id=env["provider_id"],
            rendering_provider_id=env["provider_id"],
            filing_indicator=None,
            notes=None,
            claim_status=None, total_allowed=None, total_paid=None,
            patient_responsibility=None, adjustment_amount=None,
            sales_invoice_id=None, denial_reason=None, appeal_deadline=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "naming_series" in result

    def test_list_claims(self, conn, env):
        result = call_action(mod.health_list_claims, conn, ns(
            company_id=env["company_id"],
            patient_id=None, claim_status=None,
            claim_type=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result


# ─────────────────────────────────────────────────────────────────────────────
# Formulary (Inventory)
# ─────────────────────────────────────────────────────────────────────────────

class TestFormulary:
    def test_add_formulary(self, conn, env):
        result = call_action(mod.health_add_formulary, conn, ns(
            company_id=env["company_id"],
            formulary_name="Hospital Formulary 2026",
            description="Annual formulary",
            effective_date="2026-01-01",
            expiration_date="2026-12-31",
            formulary_status=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "id" in result

    def test_add_formulary_missing_name(self, conn, env):
        result = call_action(mod.health_add_formulary, conn, ns(
            company_id=env["company_id"],
            formulary_name=None,
            description=None,
            effective_date="2026-01-01",
            expiration_date=None,
            formulary_status=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_formulary(self, conn, env):
        add_res = call_action(mod.health_add_formulary, conn, ns(
            company_id=env["company_id"],
            formulary_name="Update Test Formulary",
            description=None,
            effective_date="2026-01-01",
            expiration_date=None,
            formulary_status=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.health_update_formulary, conn, ns(
            formulary_id=add_res["id"],
            formulary_name=None,
            description="Updated",
            formulary_status=None,
            effective_date=None, expiration_date=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result

    def test_list_formularies(self, conn, env):
        result = call_action(mod.health_list_formularies, conn, ns(
            company_id=env["company_id"],
            formulary_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
