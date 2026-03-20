"""Tests for HealthClaw Phase 8: Clinical Depth — 8 HIGH gaps.

Actions tested:
  H14: health-add-problem, health-list-active-problems
  H15: health-add-med-reconciliation, health-list-med-reconciliations, health-get-med-reconciliation
  H16: health-add-immunization, health-update-immunization, health-list-immunizations,
       health-get-immunization-record, health-immunizations-due-report
  H19: health-add-provider-credential, health-list-provider-credentials,
       health-check-expiring-credentials, health-provider-credential-report
  H20: health-add-payer-enrollment, health-list-payer-enrollments, health-check-enrollment-revalidation
  H21: health-check-room-availability, health-schedule-multi-resource
  H22: health-add-reminder, health-list-reminders, health-process-reminders
  H42: health-merge-patients
"""
import pytest
from health_helpers import call_action, ns, is_error, is_ok, load_db_query, seed_patient, seed_employee, seed_encounter

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# H14: Problem List
# ─────────────────────────────────────────────────────────────────────────────

class TestProblemList:
    def test_add_problem_delegates_to_medical_history(self, conn, env):
        """health-add-problem should create a medical_history entry."""
        result = call_action(mod.health_add_problem, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            condition="Hypertension", icd10_code="I10",
            diagnosis_date="2025-01-15", resolution_date=None,
            medhist_status="chronic", notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "id" in result
        assert result["condition"] == "Hypertension"

    def test_list_active_problems_filters_active_chronic(self, conn, env):
        """health-list-active-problems should only return active/chronic."""
        # Add active problem
        call_action(mod.health_add_medical_history, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            condition="Diabetes Type 2", icd10_code="E11.9",
            diagnosis_date="2024-06-01", resolution_date=None,
            medhist_status="active", notes=None,
            limit=50, offset=0,
        ))
        # Add chronic problem
        call_action(mod.health_add_medical_history, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            condition="Asthma", icd10_code="J45.909",
            diagnosis_date="2020-01-01", resolution_date=None,
            medhist_status="chronic", notes=None,
            limit=50, offset=0,
        ))
        # Add resolved problem (should NOT appear)
        call_action(mod.health_add_medical_history, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            condition="Appendicitis", icd10_code="K35.80",
            diagnosis_date="2023-03-01", resolution_date="2023-03-05",
            medhist_status="resolved", notes=None,
            limit=50, offset=0,
        ))

        result = call_action(mod.health_list_active_problems, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 2
        for row in result["rows"]:
            assert row["status"] in ("active", "chronic")

    def test_list_active_problems_missing_patient(self, conn, env):
        result = call_action(mod.health_list_active_problems, conn, ns(
            patient_id=None, company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_error(result)


# ─────────────────────────────────────────────────────────────────────────────
# H15: Medication Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

class TestMedReconciliation:
    def test_add_med_reconciliation(self, conn, env):
        result = call_action(mod.health_add_med_reconciliation, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            reconciliation_type="admission",
            medications_reviewed="Metformin 500mg, Lisinopril 10mg",
            medications_added="Aspirin 81mg",
            medications_removed=None,
            medications_changed="Metformin increased to 1000mg",
            reconciled_by=env["provider_id"],
            notes="Admission med reconciliation",
            status=None, reconciliation_id=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["reconciliation_type"] == "admission"
        assert result["recon_status"] == "pending"

    def test_add_med_reconciliation_missing_type(self, conn, env):
        result = call_action(mod.health_add_med_reconciliation, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            encounter_id=None, reconciliation_type=None,
            medications_reviewed=None, medications_added=None,
            medications_removed=None, medications_changed=None,
            reconciled_by=None, notes=None, status=None,
            reconciliation_id=None, limit=50, offset=0,
        ))
        assert is_error(result)

    def test_list_med_reconciliations(self, conn, env):
        # Create one first
        call_action(mod.health_add_med_reconciliation, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            encounter_id=None, reconciliation_type="annual_review",
            medications_reviewed="Lisinopril 10mg", medications_added=None,
            medications_removed=None, medications_changed=None,
            reconciled_by=None, notes=None, status=None,
            reconciliation_id=None, limit=50, offset=0,
        ))
        result = call_action(mod.health_list_med_reconciliations, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            status=None, limit=50, offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] >= 1

    def test_get_med_reconciliation(self, conn, env):
        add_res = call_action(mod.health_add_med_reconciliation, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            encounter_id=None, reconciliation_type="discharge",
            medications_reviewed="All", medications_added=None,
            medications_removed=None, medications_changed=None,
            reconciled_by=None, notes=None, status=None,
            reconciliation_id=None, limit=50, offset=0,
        ))
        result = call_action(mod.health_get_med_reconciliation, conn, ns(
            reconciliation_id=add_res["id"], limit=50, offset=0,
        ))
        assert is_ok(result)
        assert result["reconciliation_type"] == "discharge"


# ─────────────────────────────────────────────────────────────────────────────
# H16: Immunization Registry
# ─────────────────────────────────────────────────────────────────────────────

class TestImmunization:
    def test_add_immunization(self, conn, env):
        result = call_action(mod.health_add_immunization, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            vaccine_name="COVID-19 mRNA (Pfizer-BioNTech)",
            vaccine_code="CVX-208", lot_number="EK9788",
            manufacturer="Pfizer", administration_date="2026-01-15",
            administration_site="left deltoid",
            administered_by=env["provider_id"],
            dose_number="2", series_complete="1",
            vis_date="2025-12-01", next_due_date=None,
            reaction_notes=None, immunization_id=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["vaccine_name"] == "COVID-19 mRNA (Pfizer-BioNTech)"

    def test_add_immunization_missing_vaccine(self, conn, env):
        result = call_action(mod.health_add_immunization, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            vaccine_name=None, vaccine_code=None, lot_number=None,
            manufacturer=None, administration_date="2026-01-15",
            administration_site=None, administered_by=None,
            dose_number=None, series_complete=None,
            vis_date=None, next_due_date=None,
            reaction_notes=None, immunization_id=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_immunization(self, conn, env):
        add_res = call_action(mod.health_add_immunization, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            vaccine_name="Influenza", vaccine_code="CVX-158",
            lot_number="FL2026", manufacturer="Sanofi",
            administration_date="2026-01-10",
            administration_site="right deltoid",
            administered_by=None, dose_number="1",
            series_complete="0", vis_date=None,
            next_due_date="2027-01-10", reaction_notes=None,
            immunization_id=None, limit=50, offset=0,
        ))
        result = call_action(mod.health_update_immunization, conn, ns(
            immunization_id=add_res["id"],
            reaction_notes="Mild soreness at injection site",
            vaccine_name=None, vaccine_code=None, lot_number=None,
            manufacturer=None, administration_date=None,
            administration_site=None, administered_by=None,
            dose_number=None, series_complete=None,
            vis_date=None, next_due_date=None,
            limit=50, offset=0,
        ))
        assert is_ok(result)
        assert "reaction_notes" in result["updated_fields"]

    def test_list_immunizations(self, conn, env):
        call_action(mod.health_add_immunization, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            vaccine_name="Tetanus", vaccine_code="CVX-115",
            lot_number="TT1001", manufacturer="GSK",
            administration_date="2025-06-01",
            administration_site="left deltoid",
            administered_by=None, dose_number="1",
            series_complete="0", vis_date=None,
            next_due_date="2035-06-01", reaction_notes=None,
            immunization_id=None, limit=50, offset=0,
        ))
        result = call_action(mod.health_list_immunizations, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] >= 1

    def test_get_immunization_record(self, conn, env):
        add_res = call_action(mod.health_add_immunization, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            vaccine_name="Hepatitis B", vaccine_code="CVX-43",
            lot_number="HB200", manufacturer="Merck",
            administration_date="2026-02-01",
            administration_site="right deltoid",
            administered_by=None, dose_number="1",
            series_complete="0", vis_date=None,
            next_due_date="2026-03-01", reaction_notes=None,
            immunization_id=None, limit=50, offset=0,
        ))
        result = call_action(mod.health_get_immunization_record, conn, ns(
            immunization_id=add_res["id"], limit=50, offset=0,
        ))
        assert is_ok(result)
        assert result["vaccine_name"] == "Hepatitis B"

    def test_immunizations_due_report(self, conn, env):
        # Add immunization with future due date
        call_action(mod.health_add_immunization, conn, ns(
            patient_id=env["patient_id"], company_id=env["company_id"],
            vaccine_name="Pneumococcal", vaccine_code="CVX-33",
            lot_number="PN100", manufacturer="Pfizer",
            administration_date="2025-01-01",
            administration_site="left deltoid",
            administered_by=None, dose_number="1",
            series_complete="0", vis_date=None,
            next_due_date="2026-06-01", reaction_notes=None,
            immunization_id=None, limit=50, offset=0,
        ))
        result = call_action(mod.health_immunizations_due_report, conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result)
        assert result["count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# H19: Provider Credentialing
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderCredential:
    def test_add_provider_credential(self, conn, env):
        result = call_action(mod.health_add_provider_credential, conn, ns(
            company_id=env["company_id"], provider_id=env["provider_id"],
            credential_type="medical_license",
            credential_number="ML-123456",
            issuing_authority="California Medical Board",
            issue_date="2020-01-01", expiration_date="2028-01-01",
            verification_date="2025-12-01", verified_by="Admin",
            notes=None, status=None, days=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["credential_type"] == "medical_license"
        assert result["credential_status"] == "active"

    def test_add_provider_credential_invalid_type(self, conn, env):
        result = call_action(mod.health_add_provider_credential, conn, ns(
            company_id=env["company_id"], provider_id=env["provider_id"],
            credential_type="invalid_type",
            credential_number="X", issuing_authority=None,
            issue_date=None, expiration_date=None,
            verification_date=None, verified_by=None,
            notes=None, status=None, days=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_list_provider_credentials(self, conn, env):
        call_action(mod.health_add_provider_credential, conn, ns(
            company_id=env["company_id"], provider_id=env["provider_id"],
            credential_type="dea", credential_number="DEA-7890",
            issuing_authority="DEA", issue_date="2024-01-01",
            expiration_date="2027-01-01", verification_date=None,
            verified_by=None, notes=None, status=None, days=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_provider_credentials, conn, ns(
            company_id=env["company_id"], provider_id=env["provider_id"],
            credential_type=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] >= 1

    def test_check_expiring_credentials(self, conn, env):
        # Add credential expiring soon
        call_action(mod.health_add_provider_credential, conn, ns(
            company_id=env["company_id"], provider_id=env["provider_id"],
            credential_type="npi", credential_number="NPI-111",
            issuing_authority="CMS", issue_date="2020-01-01",
            expiration_date="2026-04-01",  # Expires soon
            verification_date=None, verified_by=None,
            notes=None, status=None, days=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_check_expiring_credentials, conn, ns(
            company_id=env["company_id"], days="365",
            provider_id=None, credential_type=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result)
        assert "expiring" in result or "already_expired" in result

    def test_provider_credential_report(self, conn, env):
        call_action(mod.health_add_provider_credential, conn, ns(
            company_id=env["company_id"], provider_id=env["provider_id"],
            credential_type="board_certification",
            credential_number="BC-456",
            issuing_authority="ABIM", issue_date="2022-01-01",
            expiration_date="2032-01-01", verification_date=None,
            verified_by=None, notes=None, status=None, days=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_provider_credential_report, conn, ns(
            provider_id=env["provider_id"],
            company_id=None, credential_type=None, status=None, days=None,
            limit=50, offset=0,
        ))
        assert is_ok(result)
        assert result["total_credentials"] >= 1
        assert "active" in result


# ─────────────────────────────────────────────────────────────────────────────
# H20: Payer Enrollment
# ─────────────────────────────────────────────────────────────────────────────

def _add_payer(conn, env, name="TestPayer"):
    """Helper: create a payer and return result."""
    return call_action(mod.health_add_payer, conn, ns(
        company_id=env["company_id"], name=name, payer_type="commercial",
        edi_payer_id=None, electronic_filing_id=None,
        address=None, city=None, state=None, zip_code=None, phone=None,
        claims_address=None, claims_city=None, claims_state=None, claims_zip=None,
        submission_method=None, timely_filing_days=None, era_enrollment=None,
        notes=None, limit=50, offset=0,
    ))


class TestPayerEnrollment:
    def test_add_payer_enrollment(self, conn, env):
        payer = _add_payer(conn, env, name="Aetna Commercial")
        result = call_action(mod.health_add_payer_enrollment, conn, ns(
            company_id=env["company_id"], provider_id=env["provider_id"],
            payer_id=payer["id"], enrollment_status="active",
            effective_date="2025-01-01", termination_date=None,
            revalidation_date="2028-01-01",
            provider_number="PRV-12345", group_npi="1234567890",
            notes=None, days=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["enrollment_status"] == "active"

    def test_add_payer_enrollment_missing_payer(self, conn, env):
        result = call_action(mod.health_add_payer_enrollment, conn, ns(
            company_id=env["company_id"], provider_id=env["provider_id"],
            payer_id=None, enrollment_status="active",
            effective_date=None, termination_date=None,
            revalidation_date=None, provider_number=None,
            group_npi=None, notes=None, days=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_list_payer_enrollments(self, conn, env):
        payer = _add_payer(conn, env, name="BCBS")
        call_action(mod.health_add_payer_enrollment, conn, ns(
            company_id=env["company_id"], provider_id=env["provider_id"],
            payer_id=payer["id"], enrollment_status="active",
            effective_date="2025-01-01", termination_date=None,
            revalidation_date=None, provider_number=None,
            group_npi=None, notes=None, days=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_payer_enrollments, conn, ns(
            company_id=env["company_id"], provider_id=env["provider_id"],
            payer_id=None, enrollment_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# H21: Multi-Resource Scheduling
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiResourceScheduling:
    def test_check_room_availability_empty(self, conn, env):
        """Room with no appointments should be available."""
        result = call_action(mod.health_check_room_availability, conn, ns(
            location="Room 101", appointment_date="2026-03-25",
            start_time="09:00", end_time="10:00",
            company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["available"] is True
        assert result["conflict_count"] == 0

    def test_check_room_availability_conflict(self, conn, env):
        """Room with an existing appointment should show conflict."""
        # Book an appointment in Room 102
        call_action(mod.health_add_appointment, conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            appointment_date="2026-03-25", start_time="09:00", end_time="10:00",
            appointment_type="follow_up", chief_complaint=None,
            location="Room 102", duration_minutes=None, notes=None,
            status=None, new_provider_id=None, cancellation_reason=None,
            appointment_id=None, search=None,
            limit=50, offset=0,
        ))
        # Check same room, overlapping time
        result = call_action(mod.health_check_room_availability, conn, ns(
            location="Room 102", appointment_date="2026-03-25",
            start_time="09:30", end_time="10:30",
            company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result)
        assert result["available"] is False
        assert result["conflict_count"] == 1

    def test_schedule_multi_resource_success(self, conn, env):
        result = call_action(mod.health_schedule_multi_resource, conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            appointment_date="2026-04-01", start_time="14:00", end_time="15:00",
            location="Room 201", appointment_type="consultation",
            chief_complaint="Annual checkup", duration_minutes=None,
            notes=None, status=None, new_provider_id=None,
            cancellation_reason=None, appointment_id=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["appt_status"] == "scheduled"
        assert result["location"] == "Room 201"

    def test_schedule_multi_resource_room_conflict(self, conn, env):
        """Booking a room that's already taken should fail."""
        # Book first
        call_action(mod.health_schedule_multi_resource, conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            appointment_date="2026-04-02", start_time="09:00", end_time="10:00",
            location="Room 301", appointment_type="follow_up",
            chief_complaint=None, duration_minutes=None,
            notes=None, status=None, new_provider_id=None,
            cancellation_reason=None, appointment_id=None, search=None,
            limit=50, offset=0,
        ))
        # Use second provider to avoid provider conflict
        result = call_action(mod.health_schedule_multi_resource, conn, ns(
            company_id=env["company_id"], patient_id=env["patient_id"],
            provider_id=env["provider2_id"],
            appointment_date="2026-04-02", start_time="09:00", end_time="10:00",
            location="Room 301", appointment_type="follow_up",
            chief_complaint=None, duration_minutes=None,
            notes=None, status=None, new_provider_id=None,
            cancellation_reason=None, appointment_id=None, search=None,
            limit=50, offset=0,
        ))
        assert is_error(result)
        assert "conflict" in result.get("error", result.get("message", "")).lower()


# ─────────────────────────────────────────────────────────────────────────────
# H22: Appointment Reminders
# ─────────────────────────────────────────────────────────────────────────────

def _add_appointment(conn, env, date="2026-04-10"):
    return call_action(mod.health_add_appointment, conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"],
        appointment_date=date, start_time="10:00", end_time="11:00",
        appointment_type="follow_up", chief_complaint=None,
        location=None, duration_minutes=None, notes=None,
        status=None, new_provider_id=None, cancellation_reason=None,
        appointment_id=None, search=None,
        limit=50, offset=0,
    ))


class TestAppointmentReminders:
    def test_add_reminder(self, conn, env):
        appt = _add_appointment(conn, env)
        result = call_action(mod.health_add_reminder, conn, ns(
            appointment_id=appt["id"], reminder_type="email",
            scheduled_at="2026-04-09T08:00:00Z",
            status=None, limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["reminder_type"] == "email"
        assert result["reminder_status"] == "pending"

    def test_add_reminder_missing_type(self, conn, env):
        appt = _add_appointment(conn, env)
        result = call_action(mod.health_add_reminder, conn, ns(
            appointment_id=appt["id"], reminder_type=None,
            scheduled_at="2026-04-09T08:00:00Z",
            status=None, limit=50, offset=0,
        ))
        assert is_error(result)

    def test_list_reminders(self, conn, env):
        appt = _add_appointment(conn, env)
        call_action(mod.health_add_reminder, conn, ns(
            appointment_id=appt["id"], reminder_type="sms",
            scheduled_at="2026-04-09T10:00:00Z",
            status=None, limit=50, offset=0,
        ))
        result = call_action(mod.health_list_reminders, conn, ns(
            appointment_id=appt["id"], status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] >= 1

    def test_process_reminders(self, conn, env):
        appt = _add_appointment(conn, env)
        # Schedule reminder in the past so it gets processed
        call_action(mod.health_add_reminder, conn, ns(
            appointment_id=appt["id"], reminder_type="phone",
            scheduled_at="2020-01-01T08:00:00Z",
            status=None, limit=50, offset=0,
        ))
        result = call_action(mod.health_process_reminders, conn, ns(
            limit=50, offset=0,
        ))
        assert is_ok(result)
        assert result["processed_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# H42: Patient Merge
# ─────────────────────────────────────────────────────────────────────────────

class TestPatientMerge:
    def test_merge_patients_basic(self, conn, env):
        """Merge source into target, verify source deactivated."""
        source_id = seed_patient(conn, env["company_id"], "Alice", "Source")
        target_id = env["patient_id"]

        # Add some records to source patient
        call_action(mod.health_add_allergy, conn, ns(
            patient_id=source_id, allergen="Penicillin",
            allergen_type="drug", reaction="Rash", severity="moderate",
            onset_date=None, noted_by_id=None, notes=None, status=None,
            allergy_id=None, limit=50, offset=0,
        ))

        result = call_action(mod.health_merge_patients, conn, ns(
            source_patient_id=source_id,
            target_patient_id=target_id,
            patient_id=None, company_id=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["source_status"] == "inactive"
        assert result["total_records_repointed"] >= 1

        # Verify allergy now points to target
        allergy_res = call_action(mod.health_list_allergies, conn, ns(
            patient_id=target_id, status=None, allergen_type=None,
            limit=50, offset=0,
        ))
        assert is_ok(allergy_res)
        found = any(r["allergen"] == "Penicillin" for r in allergy_res["rows"])
        assert found, "Allergy should be repointed to target patient"

    def test_merge_patients_same_id_error(self, conn, env):
        result = call_action(mod.health_merge_patients, conn, ns(
            source_patient_id=env["patient_id"],
            target_patient_id=env["patient_id"],
            patient_id=None, company_id=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_merge_patients_missing_source(self, conn, env):
        result = call_action(mod.health_merge_patients, conn, ns(
            source_patient_id=None,
            target_patient_id=env["patient_id"],
            patient_id=None, company_id=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_merge_patients_nonexistent_target(self, conn, env):
        source_id = seed_patient(conn, env["company_id"], "Bob", "MergeTest")
        result = call_action(mod.health_merge_patients, conn, ns(
            source_patient_id=source_id,
            target_patient_id="nonexistent-id",
            patient_id=None, company_id=None,
            limit=50, offset=0,
        ))
        assert is_error(result)
