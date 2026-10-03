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
  - health-update-prior-auth
  - health-list-prior-auths
"""
import pytest
from health_helpers import call_action, ns, is_error, is_ok, load_db_query

from erpclaw_lib.query import Field, P, Q, Table, fn

mod = load_db_query()


def _read_row(conn, table, row_id):
    """Read one stored row back through a PyPika-built query."""
    t = Table(table)
    row = conn.execute(
        Q.from_(t).select(t.star).where(Field("id") == P()).get_sql(),
        (row_id,),
    ).fetchone()
    assert row is not None, f"expected a row in {table} id={row_id}"
    return dict(row)


def _table_count(conn, table):
    t = Table(table)
    return conn.execute(
        Q.from_(t).select(fn.Count("*")).get_sql()).fetchone()[0]


def _refusal_message(result):
    return result.get("message", "") + result.get("error", "")


# ─────────────────────────────────────────────────────────────────────────────
# Lab Orders
# ─────────────────────────────────────────────────────────────────────────────

class TestLabOrder:
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

    def test_update_lab_order(self, conn, env):
        # Behavioural: the update must rewrite the stored lab-order row, not
        # just return an ok envelope. Read the row before and after through
        # PyPika-built queries, and cross-check through the get action.
        before = _read_row(conn, "healthclaw_lab_order", env["lab_order_id"])
        assert before["order_status"] == "ordered"
        assert before["collection_date"] is None

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
        assert set(result["updated_fields"]) == {
            "collection_date", "notes", "order_status"}

        after = _read_row(conn, "healthclaw_lab_order", env["lab_order_id"])
        assert (after["order_status"], after["collection_date"],
                after["notes"]) == (
            "collected", "2026-03-16", "Sample collected")
        for col in ("id", "naming_series", "encounter_id", "patient_id",
                    "ordering_provider_id", "order_date", "priority",
                    "fasting_required", "specimen_type", "received_date",
                    "company_id", "created_at"):
            assert after[col] == before[col], col

        fetched = call_action(mod.health_get_lab_order, conn, ns(
            lab_order_id=env["lab_order_id"],
            limit=50, offset=0,
        ))
        assert is_ok(fetched), fetched
        assert (fetched["order_status"], fetched["collection_date"],
                fetched["notes"]) == (
            "collected", "2026-03-16", "Sample collected")

        # This action writes only its own row (plus an audit row); it does
        # not reach the general ledger, so there are no legs to assert.
        assert _table_count(conn, "gl_entry") == 0

    def test_update_lab_order_refusal_writes_nothing(self, conn, env):
        before = _read_row(conn, "healthclaw_lab_order", env["lab_order_id"])
        count_before = _table_count(conn, "healthclaw_lab_order")

        result = call_action(mod.health_update_lab_order, conn, ns(
            lab_order_id=env["lab_order_id"],
            lab_order_status="bogus",
            collection_date=None,
            received_date=None,
            notes=None,
            priority=None, fasting_required=None,
            specimen_type=None,
            limit=50, offset=0,
        ))
        assert is_error(result)
        assert _refusal_message(result) == (
            "Invalid order_status: bogus. Must be one of: ordered, collected, "
            "received, in_progress, completed, cancelled")
        assert _read_row(conn, "healthclaw_lab_order",
                         env["lab_order_id"]) == before
        assert _table_count(conn, "healthclaw_lab_order") == count_before

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
        before = _read_row(conn, "healthclaw_referral", add_res["id"])
        assert before["status"] == "pending"
        assert before["notes"] is None

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
        assert set(result["updated_fields"]) == {"notes", "status"}

        after = _read_row(conn, "healthclaw_referral", add_res["id"])
        assert (after["status"], after["notes"]) == (
            "sent", "Referral sent via fax")
        for col in ("id", "naming_series", "patient_id", "referring_provider_id",
                    "referred_to_provider", "referred_to_specialty",
                    "referral_date", "reason", "priority", "company_id",
                    "created_at"):
            assert after[col] == before[col], col

        fetched = call_action(mod.health_get_referral, conn, ns(
            referral_id=add_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(fetched), fetched
        assert fetched["document_status"] == "sent"
        assert fetched["notes"] == "Referral sent via fax"

        # This action writes only its own row (plus an audit row); it does
        # not reach the general ledger, so there are no legs to assert.
        assert _table_count(conn, "gl_entry") == 0

    def test_update_referral_refusal_writes_nothing(self, conn, env):
        add_res = call_action(mod.health_add_referral, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            referring_provider_id=env["provider_id"],
            referred_to_provider="Dr. Refuse",
            referred_to_specialty="Neurology",
            referred_to_facility=None, referred_to_phone=None,
            referred_to_fax=None, referral_date="2026-03-15",
            reason="Headache", priority=None,
            prior_auth_required=None, notes=None,
            referral_status=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        before = _read_row(conn, "healthclaw_referral", add_res["id"])
        count_before = _table_count(conn, "healthclaw_referral")

        result = call_action(mod.health_update_referral, conn, ns(
            referral_id=add_res["id"],
            referral_status="bogus",
            referred_to_specialty=None, referred_to_facility=None,
            referred_to_phone=None, referred_to_fax=None,
            notes=None,
            priority=None,
            limit=50, offset=0,
        ))
        assert is_error(result)
        assert _refusal_message(result) == (
            "Invalid status: bogus. Must be one of: pending, sent, accepted, "
            "declined, completed, expired, cancelled")
        assert _read_row(conn, "healthclaw_referral",
                         add_res["id"]) == before
        assert _table_count(conn, "healthclaw_referral") == count_before

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

    def test_update_prior_auth(self, conn, env):
        # Behavioural: the update must rewrite the stored prior-auth row, not
        # just return an ok envelope. Read the row before and after through
        # PyPika-built queries, and cross-check through the get action.
        ins_id = self._seed_insurance(conn, env)
        add_res = call_action(mod.health_add_prior_auth, conn, ns(
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
        assert is_ok(add_res)
        before = _read_row(conn, "healthclaw_prior_auth", add_res["id"])
        assert before["status"] == "pending"
        assert before["units_approved"] is None
        assert before["decision_date"] is None

        result = call_action(mod.health_update_prior_auth, conn, ns(
            prior_auth_id=add_res["id"],
            auth_number="AUTH-PAY-001",
            service_type=None,
            cpt_codes=None,
            icd10_codes=None,
            description=None,
            units_requested=None,
            units_approved="2",
            request_date=None,
            effective_date=None,
            expiration_date=None,
            decision_date="2026-03-20",
            auth_status="approved",
            denial_reason=None,
            appeal_deadline=None,
            notes=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert set(result["updated_fields"]) == {
            "auth_number", "decision_date", "status", "units_approved"}

        after = _read_row(conn, "healthclaw_prior_auth", add_res["id"])
        assert (after["status"], after["decision_date"],
                after["units_approved"], after["auth_number"]) == (
            "approved", "2026-03-20", 2, "AUTH-PAY-001")
        for col in ("id", "naming_series", "patient_id", "insurance_id",
                    "requesting_provider_id", "service_type", "cpt_codes",
                    "icd10_codes", "description", "units_requested",
                    "request_date", "effective_date", "expiration_date",
                    "company_id", "created_at"):
            assert after[col] == before[col], col

        fetched = call_action(mod.health_get_prior_auth, conn, ns(
            prior_auth_id=add_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(fetched), fetched
        assert fetched["document_status"] == "approved"
        assert fetched["units_approved"] == 2
        assert fetched["auth_number"] == "AUTH-PAY-001"

        # This action writes only its own row (plus an audit row); it does
        # not reach the general ledger, so there are no legs to assert.
        assert _table_count(conn, "gl_entry") == 0

    def test_update_prior_auth_refusal_writes_nothing(self, conn, env):
        ins_id = self._seed_insurance(conn, env)
        add_res = call_action(mod.health_add_prior_auth, conn, ns(
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
        assert is_ok(add_res)
        before = _read_row(conn, "healthclaw_prior_auth", add_res["id"])
        count_before = _table_count(conn, "healthclaw_prior_auth")

        result = call_action(mod.health_update_prior_auth, conn, ns(
            prior_auth_id=add_res["id"],
            auth_number=None,
            service_type=None,
            cpt_codes=None,
            icd10_codes=None,
            description=None,
            units_requested=None,
            units_approved=None,
            request_date=None,
            effective_date=None,
            expiration_date=None,
            decision_date=None,
            auth_status="bogus",
            denial_reason=None,
            appeal_deadline=None,
            notes=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_error(result)
        assert _refusal_message(result) == (
            "Invalid status: bogus. Must be one of: pending, approved, "
            "denied, partially_approved, expired, cancelled, appealed")
        assert _read_row(conn, "healthclaw_prior_auth",
                         add_res["id"]) == before
        assert _table_count(conn, "healthclaw_prior_auth") == count_before

    def test_list_prior_auths(self, conn, env):
        result = call_action(mod.health_list_prior_auths, conn, ns(
            company_id=env["company_id"],
            patient_id=None, auth_status=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
