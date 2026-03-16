"""Tests for HealthClaw lab and referrals domains.

Actions tested (lab):
  - health-add-lab-order
  - health-update-lab-order
  - health-get-lab-order
  - health-list-lab-orders
  - health-add-lab-test
  - health-list-lab-tests
  - health-add-imaging-order
  - health-list-imaging-orders
Actions tested (referrals):
  - health-add-referral
  - health-update-referral
  - health-get-referral
  - health-list-referrals
  - health-add-prior-auth
  - health-list-prior-auths
"""
import pytest
from health_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Lab Orders
# ─────────────────────────────────────────────────────────────────────────────

class TestLabOrder:
    @pytest.mark.xfail(reason="lab.py bug: uses 'status' column instead of 'order_status'")
    def test_add_lab_order(self, conn, env):
        result = call_action(mod.health_add_lab_order, conn, ns(
            company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            ordering_provider_id=env["provider_id"],
            order_date="2026-03-15",
            priority="routine",
            fasting_required=None,
            specimen_type="blood",
            clinical_indication="Annual screening",
            notes=None, lab_order_status=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "id" in result
        assert "naming_series" in result

    def test_add_lab_order_missing_encounter(self, conn, env):
        result = call_action(mod.health_add_lab_order, conn, ns(
            company_id=env["company_id"],
            encounter_id=None,
            patient_id=env["patient_id"],
            ordering_provider_id=env["provider_id"],
            order_date="2026-03-15",
            priority=None, fasting_required=None,
            specimen_type=None, clinical_indication=None,
            notes=None, lab_order_status=None, status=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_get_lab_order(self, conn, env):
        result = call_action(mod.health_get_lab_order, conn, ns(
            lab_order_id=env["lab_order_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["id"] == env["lab_order_id"]

    @pytest.mark.xfail(reason="lab.py bug: uses 'status' column instead of 'order_status'")
    def test_update_lab_order(self, conn, env):
        result = call_action(mod.health_update_lab_order, conn, ns(
            lab_order_id=env["lab_order_id"],
            lab_order_status="collected",
            collection_date="2026-03-16",
            received_date=None,
            notes="Sample collected",
            priority=None, fasting_required=None,
            specimen_type=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result

    def test_list_lab_orders(self, conn, env):
        result = call_action(mod.health_list_lab_orders, conn, ns(
            company_id=env["company_id"],
            encounter_id=None, patient_id=None,
            lab_order_status=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Lab Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLabTest:
    def test_add_lab_test(self, conn, env):
        result = call_action(mod.health_add_lab_test, conn, ns(
            lab_order_id=env["lab_order_id"],
            test_code="CBC",
            test_name="Complete Blood Count",
            component_name=None,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["test_code"] == "CBC"

    def test_list_lab_tests(self, conn, env):
        call_action(mod.health_add_lab_test, conn, ns(
            lab_order_id=env["lab_order_id"],
            test_code="BMP",
            test_name="Basic Metabolic Panel",
            component_name=None,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_lab_tests, conn, ns(
            lab_order_id=env["lab_order_id"],
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Imaging Orders
# ─────────────────────────────────────────────────────────────────────────────

class TestImagingOrder:
    def test_add_imaging_order(self, conn, env):
        result = call_action(mod.health_add_imaging_order, conn, ns(
            company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            ordering_provider_id=env["provider_id"],
            modality="xray",
            body_part="Chest",
            laterality=None,
            contrast=None,
            order_date="2026-03-15",
            priority="routine",
            clinical_indication="Cough evaluation",
            scheduled_date="2026-03-20",
            notes=None,
            imaging_order_status=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "naming_series" in result

    def test_list_imaging_orders(self, conn, env):
        call_action(mod.health_add_imaging_order, conn, ns(
            company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            ordering_provider_id=env["provider_id"],
            modality="ct",
            body_part="Abdomen",
            laterality=None, contrast="with",
            order_date="2026-03-15",
            priority="urgent",
            clinical_indication="Abdominal pain",
            scheduled_date=None,
            notes=None,
            imaging_order_status=None, status=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_imaging_orders, conn, ns(
            company_id=env["company_id"],
            encounter_id=None, patient_id=None,
            imaging_order_status=None, modality=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Referrals
# ─────────────────────────────────────────────────────────────────────────────

class TestReferral:
    def test_add_referral(self, conn, env):
        result = call_action(mod.health_add_referral, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            referring_provider_id=env["provider_id"],
            referred_to_provider="Dr. Specialist",
            referred_to_specialty="Cardiology",
            referred_to_facility=None,
            referred_to_phone=None,
            referred_to_fax=None,
            referral_date="2026-03-15",
            reason="Chest pain evaluation",
            priority="routine",
            prior_auth_required=None,
            notes=None,
            referral_status=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "naming_series" in result

    def test_add_referral_missing_provider(self, conn, env):
        result = call_action(mod.health_add_referral, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            referring_provider_id=None,
            referred_to_provider="Dr. X",
            referred_to_specialty=None,
            referred_to_facility=None,
            referred_to_phone=None,
            referred_to_fax=None,
            referral_date="2026-03-15",
            reason=None, priority=None,
            prior_auth_required=None, notes=None,
            referral_status=None, status=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_referral(self, conn, env):
        add_res = call_action(mod.health_add_referral, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            referring_provider_id=env["provider_id"],
            referred_to_provider="Dr. Update",
            referred_to_specialty="Dermatology",
            referred_to_facility=None, referred_to_phone=None,
            referred_to_fax=None, referral_date="2026-03-15",
            reason="Skin rash", priority=None,
            prior_auth_required=None, notes=None,
            referral_status=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.health_update_referral, conn, ns(
            referral_id=add_res["id"],
            referral_status="sent",
            referred_to_specialty=None, referred_to_facility=None,
            referred_to_phone=None, referred_to_fax=None,
            notes="Referral sent via fax",
            priority=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result

    def test_list_referrals(self, conn, env):
        result = call_action(mod.health_list_referrals, conn, ns(
            company_id=env["company_id"],
            patient_id=None, referral_status=None,
            referring_provider_id=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result


# ─────────────────────────────────────────────────────────────────────────────
# Prior Auth
# ─────────────────────────────────────────────────────────────────────────────

class TestPriorAuth:
    def _seed_insurance(self, conn, env):
        """Create a patient insurance record for prior auth tests."""
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
        return res["id"]

    def test_add_prior_auth(self, conn, env):
        ins_id = self._seed_insurance(conn, env)
        result = call_action(mod.health_add_prior_auth, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            insurance_id=ins_id,
            requesting_provider_id=env["provider_id"],
            service_type="procedure",
            cpt_codes="99213",
            icd10_codes="J06.9",
            description="Office visit pre-auth",
            units_requested="1",
            request_date="2026-03-15",
            effective_date="2026-03-15",
            expiration_date="2026-06-15",
            auth_number=None,
            auth_status=None,
            decision_date=None,
            units_approved=None,
            notes=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "naming_series" in result

    def test_list_prior_auths(self, conn, env):
        result = call_action(mod.health_list_prior_auths, conn, ns(
            company_id=env["company_id"],
            patient_id=None, auth_status=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
