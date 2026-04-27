"""Tests for HealthClaw patients domain.

Actions tested:
  - health-add-patient
  - health-get-patient
  - health-update-patient
  - health-list-patients
  - health-add-patient-insurance
  - health-update-patient-insurance
  - health-list-patient-insurances
  - health-add-allergy
  - health-update-allergy
  - health-list-allergies
  - health-add-medical-history
  - health-update-medical-history
  - health-list-medical-history
  - health-add-patient-contact
  - health-update-patient-contact
  - health-add-consent
"""
import pytest
from health_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Patient CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestAddPatient:
    def test_basic_patient(self, conn, env):
        result = call_action(mod.health_add_patient, conn, ns(
            company_id=env["company_id"],
            first_name="Alice",
            last_name="Johnson",
            date_of_birth="1985-03-15",
            gender="female",
            ssn=None,
            marital_status=None,
            race=None,
            ethnicity=None,
            preferred_language=None,
            primary_phone="555-0100",
            secondary_phone=None,
            email="alice@example.com",
            address_line1="123 Main St",
            address_line2=None,
            city="Springfield",
            state="IL",
            zip_code="62701",
            primary_provider_id=None,
            customer_id=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "id" in result
        assert result["full_name"] == "Alice Johnson"
        assert "naming_series" in result
        assert "mrn" in result

    def test_patient_with_ssn_encryption(self, conn, env):
        result = call_action(mod.health_add_patient, conn, ns(
            company_id=env["company_id"],
            first_name="Bob",
            last_name="Smith",
            date_of_birth="1990-06-20",
            gender="male",
            ssn="123-45-6789",  # fake test fixture for SEC-03
            marital_status="single",
            race=None,
            ethnicity="not_hispanic_latino",
            preferred_language="English",
            primary_phone=None,
            secondary_phone=None,
            email=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            zip_code=None,
            primary_provider_id=None,
            customer_id=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        # SSN should be encrypted in DB
        row = conn.execute(
            "SELECT ssn, ssn_last4 FROM healthclaw_patient WHERE id = ?",
            (result["id"],)
        ).fetchone()
        assert row["ssn_last4"] == "6789"
        assert row["ssn"].startswith("enc:")

    def test_patient_with_provider(self, conn, env):
        result = call_action(mod.health_add_patient, conn, ns(
            company_id=env["company_id"],
            first_name="Carol",
            last_name="White",
            date_of_birth="1978-11-30",
            gender="female",
            ssn=None,
            marital_status="married",
            race=None,
            ethnicity=None,
            preferred_language=None,
            primary_phone=None,
            secondary_phone=None,
            email=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            zip_code=None,
            primary_provider_id=env["provider_id"],
            customer_id=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result

    def test_missing_required_fields(self, conn, env):
        # Missing first_name
        result = call_action(mod.health_add_patient, conn, ns(
            company_id=env["company_id"],
            first_name=None,
            last_name="Test",
            date_of_birth="1990-01-01",
            gender="male",
            ssn=None, marital_status=None, race=None, ethnicity=None,
            preferred_language=None, primary_phone=None, secondary_phone=None,
            email=None, address_line1=None, address_line2=None,
            city=None, state=None, zip_code=None,
            primary_provider_id=None, customer_id=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_invalid_gender(self, conn, env):
        result = call_action(mod.health_add_patient, conn, ns(
            company_id=env["company_id"],
            first_name="Test",
            last_name="Patient",
            date_of_birth="1990-01-01",
            gender="invalid",
            ssn=None, marital_status=None, race=None, ethnicity=None,
            preferred_language=None, primary_phone=None, secondary_phone=None,
            email=None, address_line1=None, address_line2=None,
            city=None, state=None, zip_code=None,
            primary_provider_id=None, customer_id=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)


class TestGetPatient:
    def test_get_existing(self, conn, env):
        result = call_action(mod.health_get_patient, conn, ns(
            patient_id=env["patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["id"] == env["patient_id"]
        assert "ssn_last4" in result or result.get("ssn_last4") is None
        assert "active_insurance_count" in result
        assert "active_allergy_count" in result

    def test_get_nonexistent(self, conn, env):
        result = call_action(mod.health_get_patient, conn, ns(
            patient_id="nonexistent-id",
            limit=50, offset=0,
        ))
        assert is_error(result)


class TestUpdatePatient:
    def test_update_email(self, conn, env):
        result = call_action(mod.health_update_patient, conn, ns(
            patient_id=env["patient_id"],
            first_name=None, last_name=None, date_of_birth=None,
            gender=None, ssn=None, marital_status=None, race=None,
            ethnicity=None, preferred_language=None, primary_phone=None,
            secondary_phone=None, email="updated@example.com",
            address_line1=None, address_line2=None, city=None,
            state=None, zip_code=None, primary_provider_id=None,
            status=None, notes=None, customer_id=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "email" in result["updated_fields"]

    def test_update_name_recomputes_full_name(self, conn, env):
        result = call_action(mod.health_update_patient, conn, ns(
            patient_id=env["patient_id"],
            first_name="Updated", last_name=None, date_of_birth=None,
            gender=None, ssn=None, marital_status=None, race=None,
            ethnicity=None, preferred_language=None, primary_phone=None,
            secondary_phone=None, email=None,
            address_line1=None, address_line2=None, city=None,
            state=None, zip_code=None, primary_provider_id=None,
            status=None, notes=None, customer_id=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        row = conn.execute(
            "SELECT full_name FROM healthclaw_patient WHERE id = ?",
            (env["patient_id"],)
        ).fetchone()
        assert "Updated" in row["full_name"]

    def test_no_fields_to_update(self, conn, env):
        result = call_action(mod.health_update_patient, conn, ns(
            patient_id=env["patient_id"],
            first_name=None, last_name=None, date_of_birth=None,
            gender=None, ssn=None, marital_status=None, race=None,
            ethnicity=None, preferred_language=None, primary_phone=None,
            secondary_phone=None, email=None,
            address_line1=None, address_line2=None, city=None,
            state=None, zip_code=None, primary_provider_id=None,
            status=None, notes=None, customer_id=None,
            limit=50, offset=0,
        ))
        assert is_error(result)


class TestListPatients:
    def test_list_all(self, conn, env):
        result = call_action(mod.health_list_patients, conn, ns(
            company_id=env["company_id"],
            status=None, primary_provider_id=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1
        assert len(result["rows"]) >= 1

    def test_list_with_search(self, conn, env):
        result = call_action(mod.health_list_patients, conn, ns(
            company_id=env["company_id"],
            status=None, primary_provider_id=None, search="Jane",
            limit=50, offset=0,
        ))
        assert is_ok(result), result


# ─────────────────────────────────────────────────────────────────────────────
# Insurance
# ─────────────────────────────────────────────────────────────────────────────

class TestPatientInsurance:
    def test_add_insurance(self, conn, env):
        result = call_action(mod.health_add_patient_insurance, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            insurance_type="primary",
            payer_name="BlueCross",
            payer_id=None,
            plan_name="Gold Plan",
            plan_type="ppo",
            group_number="GRP-001",
            member_id="MEM-12345",
            subscriber_name="Jane Smith",
            subscriber_dob="1990-01-01",
            subscriber_relationship="self",
            copay_amount="25.00",
            deductible="1000.00",
            deductible_met="200.00",
            out_of_pocket_max="5000.00",
            effective_date="2026-01-01",
            termination_date=None,
            preauth_required=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["insurance_type"] == "primary"
        assert "naming_series" in result

    def test_add_insurance_missing_payer_name(self, conn, env):
        result = call_action(mod.health_add_patient_insurance, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            insurance_type="primary",
            payer_name=None,
            payer_id=None,
            plan_name=None,
            plan_type=None,
            group_number=None,
            member_id="MEM-99",
            subscriber_name=None, subscriber_dob=None, subscriber_relationship=None,
            copay_amount=None, deductible=None, deductible_met=None,
            out_of_pocket_max=None, effective_date="2026-01-01",
            termination_date=None, preauth_required=None, status=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_insurance(self, conn, env):
        # First add insurance
        add_res = call_action(mod.health_add_patient_insurance, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            insurance_type="primary",
            payer_name="Aetna",
            payer_id=None, plan_name=None, plan_type=None,
            group_number=None, member_id="MEM-UPD",
            subscriber_name=None, subscriber_dob=None,
            subscriber_relationship=None,
            copay_amount=None, deductible=None, deductible_met=None,
            out_of_pocket_max=None, effective_date="2026-01-01",
            termination_date=None, preauth_required=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res), add_res
        ins_id = add_res["id"]

        result = call_action(mod.health_update_patient_insurance, conn, ns(
            insurance_id=ins_id,
            insurance_type=None, payer_name=None, payer_id=None,
            plan_name="Updated Plan", plan_type=None, group_number=None,
            member_id=None, subscriber_name=None, subscriber_dob=None,
            subscriber_relationship=None, effective_date=None,
            termination_date=None, status=None,
            copay_amount=None, deductible=None, deductible_met=None,
            out_of_pocket_max=None, preauth_required=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "plan_name" in result["updated_fields"]

    def test_list_insurances(self, conn, env):
        # Add one first
        call_action(mod.health_add_patient_insurance, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            insurance_type="primary",
            payer_name="Cigna",
            payer_id=None, plan_name=None, plan_type=None,
            group_number=None, member_id="MEM-LIST",
            subscriber_name=None, subscriber_dob=None,
            subscriber_relationship=None,
            copay_amount=None, deductible=None, deductible_met=None,
            out_of_pocket_max=None, effective_date="2026-01-01",
            termination_date=None, preauth_required=None, status=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_patient_insurances, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            status=None, insurance_type=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Allergies
# ─────────────────────────────────────────────────────────────────────────────

class TestAllergies:
    def test_add_allergy(self, conn, env):
        result = call_action(mod.health_add_allergy, conn, ns(
            patient_id=env["patient_id"],
            allergen="Penicillin",
            allergen_type="drug",
            reaction="Hives",
            severity="moderate",
            onset_date="2020-01-01",
            noted_by_id=None,
            notes="Documented allergy",
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["allergen"] == "Penicillin"
        assert result["severity"] == "moderate"

    def test_add_allergy_missing_allergen(self, conn, env):
        result = call_action(mod.health_add_allergy, conn, ns(
            patient_id=env["patient_id"],
            allergen=None,
            allergen_type="drug",
            reaction=None, severity=None,
            onset_date=None, noted_by_id=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_allergy(self, conn, env):
        add_res = call_action(mod.health_add_allergy, conn, ns(
            patient_id=env["patient_id"],
            allergen="Pollen",
            allergen_type="environmental",
            reaction=None, severity="mild",
            onset_date=None, noted_by_id=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.health_update_allergy, conn, ns(
            allergy_id=add_res["id"],
            allergen=None, allergen_type=None,
            reaction="Sneezing", severity=None,
            onset_date=None, status=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "reaction" in result["updated_fields"]

    def test_list_allergies(self, conn, env):
        call_action(mod.health_add_allergy, conn, ns(
            patient_id=env["patient_id"],
            allergen="Shellfish",
            allergen_type="food",
            reaction=None, severity="severe",
            onset_date=None, noted_by_id=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_allergies, conn, ns(
            patient_id=env["patient_id"],
            status=None, allergen_type=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Medical History
# ─────────────────────────────────────────────────────────────────────────────

class TestMedicalHistory:
    def test_add_medical_history(self, conn, env):
        result = call_action(mod.health_add_medical_history, conn, ns(
            patient_id=env["patient_id"],
            condition="Hypertension",
            icd10_code="I10",
            diagnosis_date="2020-06-15",
            resolution_date=None,
            medhist_status="active",
            notes=None,
            limit=50, offset=0, search=None,
        ))
        assert is_ok(result), result
        assert result["condition"] == "Hypertension"

    def test_add_medical_history_missing_condition(self, conn, env):
        result = call_action(mod.health_add_medical_history, conn, ns(
            patient_id=env["patient_id"],
            condition=None,
            icd10_code=None, diagnosis_date=None,
            resolution_date=None, medhist_status=None, notes=None,
            limit=50, offset=0, search=None,
        ))
        assert is_error(result)

    def test_update_medical_history(self, conn, env):
        add_res = call_action(mod.health_add_medical_history, conn, ns(
            patient_id=env["patient_id"],
            condition="Diabetes Type 2",
            icd10_code="E11",
            diagnosis_date="2019-01-01",
            resolution_date=None, medhist_status="chronic",
            notes=None, limit=50, offset=0, search=None,
        ))
        assert is_ok(add_res)
        result = call_action(mod.health_update_medical_history, conn, ns(
            medical_history_id=add_res["id"],
            condition=None, icd10_code=None,
            diagnosis_date=None, resolution_date=None,
            medhist_status="resolved", notes="Well controlled",
            limit=50, offset=0, search=None,
        ))
        assert is_ok(result), result
        assert "status" in result["updated_fields"]

    def test_list_medical_history(self, conn, env):
        call_action(mod.health_add_medical_history, conn, ns(
            patient_id=env["patient_id"],
            condition="Asthma",
            icd10_code="J45",
            diagnosis_date=None, resolution_date=None,
            medhist_status=None, notes=None,
            limit=50, offset=0, search=None,
        ))
        result = call_action(mod.health_list_medical_history, conn, ns(
            patient_id=env["patient_id"],
            medhist_status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Patient Contact & Consent
# ─────────────────────────────────────────────────────────────────────────────

class TestPatientContact:
    def test_add_contact(self, conn, env):
        result = call_action(mod.health_add_patient_contact, conn, ns(
            patient_id=env["patient_id"],
            contact_name="John Doe",
            contact_type="emergency",
            relationship="spouse",
            contact_phone="555-1234",
            contact_email="john@example.com",
            contact_address="456 Oak St",
            is_primary="1",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["name"] == "John Doe"
        assert result["contact_type"] == "emergency"

    def test_add_contact_missing_name(self, conn, env):
        result = call_action(mod.health_add_patient_contact, conn, ns(
            patient_id=env["patient_id"],
            contact_name=None,
            contact_type="emergency",
            relationship=None, contact_phone=None,
            contact_email=None, contact_address=None, is_primary=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_contact(self, conn, env):
        add_res = call_action(mod.health_add_patient_contact, conn, ns(
            patient_id=env["patient_id"],
            contact_name="Mary Doe",
            contact_type="next_of_kin",
            relationship="parent", contact_phone="555-5678",
            contact_email=None, contact_address=None, is_primary=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.health_update_patient_contact, conn, ns(
            contact_id=add_res["id"],
            contact_type=None, contact_name=None,
            relationship=None, contact_phone="555-9999",
            contact_email=None, contact_address=None, is_primary=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "phone" in result["updated_fields"]


class TestConsent:
    def test_add_consent(self, conn, env):
        result = call_action(mod.health_add_consent, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            consent_type="hipaa_privacy",
            description="HIPAA notice of privacy practices",
            granted_date="2026-01-15",
            expiration_date="2027-01-15",
            witness_name="Nurse Smith",
            obtained_by_id=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["consent_type"] == "hipaa_privacy"
        assert "id" in result

    def test_add_consent_missing_type(self, conn, env):
        result = call_action(mod.health_add_consent, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            consent_type=None,
            description=None, granted_date="2026-01-15",
            expiration_date=None, witness_name=None,
            obtained_by_id=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_add_consent_missing_granted_date(self, conn, env):
        result = call_action(mod.health_add_consent, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            consent_type="treatment",
            description=None, granted_date=None,
            expiration_date=None, witness_name=None,
            obtained_by_id=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)
