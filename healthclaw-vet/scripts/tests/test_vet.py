"""Tests for HealthClaw Vet domain.

Actions tested (12):
  - vet-add-animal-patient
  - vet-update-animal-patient
  - vet-get-animal-patient
  - vet-list-animal-patients
  - vet-add-boarding
  - vet-update-boarding
  - vet-list-boardings
  - vet-calculate-dose
  - vet-list-dosing-history
  - vet-add-owner-link
  - vet-update-owner-link
  - vet-list-owner-links
"""
import pytest
from vet_helpers import call_action, ns, is_error, is_ok, load_db_query, seed_patient

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Animal Patients
# ─────────────────────────────────────────────────────────────────────────────

class TestAnimalPatient:
    def test_add_animal_patient(self, conn, env):
        # Create a new patient record for this animal
        pid = seed_patient(conn, env["company_id"], "Max", "Cat")
        result = call_action(mod.vet_add_animal_patient, conn, ns(
            company_id=env["company_id"],
            patient_id=pid,
            species="feline",
            breed="Persian",
            color="white",
            weight_kg="5.50",
            microchip_id="CHIP-001",
            spay_neuter_status="spayed",
            reproductive_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["species"] == "feline"

    def test_add_animal_patient_missing_species(self, conn, env):
        pid = seed_patient(conn, env["company_id"], "NoSpecies", "Pet")
        result = call_action(mod.vet_add_animal_patient, conn, ns(
            company_id=env["company_id"],
            patient_id=pid,
            species=None,
            breed=None, color=None, weight_kg=None,
            microchip_id=None, spay_neuter_status=None,
            reproductive_status=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_animal_patient(self, conn, env):
        result = call_action(mod.vet_update_animal_patient, conn, ns(
            animal_patient_id=env["animal_patient_id"],
            breed="Golden Retriever",
            color=None, weight_kg="32.50",
            microchip_id=None, species=None,
            spay_neuter_status=None, reproductive_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "breed" in result["updated_fields"]
        assert "weight_kg" in result["updated_fields"]

    def test_get_animal_patient(self, conn, env):
        result = call_action(mod.vet_get_animal_patient, conn, ns(
            animal_patient_id=env["animal_patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["id"] == env["animal_patient_id"]
        assert result["species"] == "canine"

    def test_list_animal_patients(self, conn, env):
        result = call_action(mod.vet_list_animal_patients, conn, ns(
            company_id=env["company_id"],
            species=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Boarding
# ─────────────────────────────────────────────────────────────────────────────

class TestBoarding:
    def test_add_boarding(self, conn, env):
        result = call_action(mod.vet_add_boarding, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            check_in_date="2026-03-15",
            check_out_date="2026-03-20",
            kennel_number="K-05",
            feeding_instructions="2x daily, 1 cup kibble",
            medication_schedule="Heartworm pill morning",
            special_needs=None,
            daily_rate="45.00",
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["animal_patient_id"] == env["animal_patient_id"]

    def test_add_boarding_missing_date(self, conn, env):
        result = call_action(mod.vet_add_boarding, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            check_in_date=None,
            check_out_date=None, kennel_number=None,
            feeding_instructions=None, medication_schedule=None,
            special_needs=None, daily_rate=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_boarding(self, conn, env):
        add_res = call_action(mod.vet_add_boarding, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            check_in_date="2026-04-01",
            check_out_date=None, kennel_number="K-10",
            feeding_instructions=None, medication_schedule=None,
            special_needs=None, daily_rate="50.00", notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.vet_update_boarding, conn, ns(
            boarding_id=add_res["id"],
            check_out_date="2026-04-05",
            kennel_number=None,
            feeding_instructions=None, medication_schedule=None,
            special_needs=None, daily_rate=None,
            status="checked_out",
            notes="Picked up by owner",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "status" in result["updated_fields"]

    def test_list_boardings(self, conn, env):
        call_action(mod.vet_add_boarding, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            check_in_date="2026-05-01",
            check_out_date=None, kennel_number=None,
            feeding_instructions=None, medication_schedule=None,
            special_needs=None, daily_rate=None, notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.vet_list_boardings, conn, ns(
            animal_patient_id=env["animal_patient_id"],
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Weight-Based Dosing
# ─────────────────────────────────────────────────────────────────────────────

class TestDosing:
    def test_calculate_dose(self, conn, env):
        result = call_action(mod.vet_calculate_dose, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            medication_name="Carprofen",
            dose_per_kg="2.2",
            weight_kg=None,  # uses animal's stored weight (30.00)
            dose_unit="mg",
            route="oral",
            frequency="2x daily",
            weight_date=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["medication_name"] == "Carprofen"
        assert result["weight_kg"] == "30.00"
        assert result["calculated_dose"] == "66.00"  # 30 * 2.2 = 66

    def test_calculate_dose_with_explicit_weight(self, conn, env):
        result = call_action(mod.vet_calculate_dose, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            medication_name="Amoxicillin",
            dose_per_kg="10",
            weight_kg="25.00",
            dose_unit="mg",
            route="oral",
            frequency=None,
            weight_date="2026-03-15",
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["calculated_dose"] == "250.00"  # 25 * 10

    def test_calculate_dose_missing_medication(self, conn, env):
        result = call_action(mod.vet_calculate_dose, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            medication_name=None,
            dose_per_kg="2.2",
            weight_kg=None, dose_unit=None,
            route=None, frequency=None,
            weight_date=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_list_dosing_history(self, conn, env):
        # Seed a dose calculation first
        call_action(mod.vet_calculate_dose, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            medication_name="TestMed",
            dose_per_kg="5",
            weight_kg=None, dose_unit=None,
            route=None, frequency=None,
            weight_date=None, notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.vet_list_dosing_history, conn, ns(
            animal_patient_id=env["animal_patient_id"],
            medication_name=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Owner Links
# ─────────────────────────────────────────────────────────────────────────────

class TestOwnerLink:
    def test_add_owner_link(self, conn, env):
        result = call_action(mod.vet_add_owner_link, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            owner_name="John Smith",
            owner_phone="555-0100",
            owner_email="john@example.com",
            relationship="owner",
            is_primary=1,
            financial_responsibility=1,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["owner_name"] == "John Smith"

    def test_add_owner_link_missing_name(self, conn, env):
        result = call_action(mod.vet_add_owner_link, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            owner_name=None,
            owner_phone=None, owner_email=None,
            relationship=None,
            is_primary=None, financial_responsibility=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_owner_link(self, conn, env):
        add_res = call_action(mod.vet_add_owner_link, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            owner_name="Jane Doe",
            owner_phone=None, owner_email=None,
            relationship=None,
            is_primary=0, financial_responsibility=1,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.vet_update_owner_link, conn, ns(
            owner_link_id=add_res["id"],
            owner_name=None,
            owner_phone="555-0200",
            owner_email="jane@example.com",
            relationship="co_owner",
            is_primary=None, financial_responsibility=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "owner_phone" in result["updated_fields"]

    def test_list_owner_links(self, conn, env):
        call_action(mod.vet_add_owner_link, conn, ns(
            company_id=env["company_id"],
            animal_patient_id=env["animal_patient_id"],
            owner_name="List Test Owner",
            owner_phone=None, owner_email=None,
            relationship=None,
            is_primary=0, financial_responsibility=1,
            notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.vet_list_owner_links, conn, ns(
            animal_patient_id=env["animal_patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1
