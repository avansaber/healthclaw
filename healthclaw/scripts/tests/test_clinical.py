"""Tests for HealthClaw clinical domain.

Actions tested:
  - health-add-encounter
  - health-update-encounter
  - health-get-encounter
  - health-list-encounters
  - health-add-vitals
  - health-list-vitals
  - health-add-diagnosis
  - health-update-diagnosis
  - health-list-diagnoses
  - health-add-prescription
  - health-update-prescription
  - health-list-prescriptions
  - health-add-procedure
  - health-list-procedures
  - health-add-clinical-note
  - health-update-clinical-note
  - health-list-clinical-notes
  - health-add-order
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
# Encounters
# ─────────────────────────────────────────────────────────────────────────────

class TestEncounter:
    def test_add_encounter(self, conn, env):
        result = call_action(mod.health_add_encounter, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            encounter_date="2026-03-15",
            encounter_type="outpatient",
            encounter_status=None,
            department="Internal Medicine",
            room="Room 5",
            appointment_id=None,
            admission_date=None, discharge_date=None,
            discharge_disposition=None, notes=None,
            status=None,
            limit=50, offset=0, search=None,
        ))
        assert is_ok(result), result
        assert "id" in result
        assert "naming_series" in result

    def test_add_encounter_missing_patient(self, conn, env):
        result = call_action(mod.health_add_encounter, conn, ns(
            company_id=env["company_id"],
            patient_id=None,
            provider_id=env["provider_id"],
            encounter_date="2026-03-15",
            encounter_type="outpatient",
            encounter_status=None,
            department=None, room=None, appointment_id=None,
            admission_date=None, discharge_date=None,
            discharge_disposition=None, notes=None,
            status=None,
            limit=50, offset=0, search=None,
        ))
        assert is_error(result)

    def test_get_encounter(self, conn, env):
        result = call_action(mod.health_get_encounter, conn, ns(
            encounter_id=env["encounter_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["id"] == env["encounter_id"]

    def test_update_encounter(self, conn, env):
        result = call_action(mod.health_update_encounter, conn, ns(
            encounter_id=env["encounter_id"],
            encounter_type=None, encounter_status=None,
            department="Updated Dept", room=None,
            discharge_date=None, discharge_disposition=None,
            notes="Updated notes", status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "department" in result["updated_fields"]

    def test_list_encounters(self, conn, env):
        result = call_action(mod.health_list_encounters, conn, ns(
            company_id=env["company_id"],
            patient_id=None, provider_id=None,
            encounter_type=None, status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Vitals
# ─────────────────────────────────────────────────────────────────────────────

class TestVitals:
    def test_add_vitals(self, conn, env):
        result = call_action(mod.health_add_vitals, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            recorded_by_id=env["provider_id"],
            temperature="98.6", temperature_site="oral",
            heart_rate="72", respiratory_rate="16",
            bp_systolic="120", bp_diastolic="80",
            oxygen_saturation="98",
            weight="180", height="72",
            bmi="24.4", pain_level="2",
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "id" in result

    def test_add_vitals_missing_encounter(self, conn, env):
        result = call_action(mod.health_add_vitals, conn, ns(
            encounter_id=None,
            patient_id=env["patient_id"],
            recorded_by_id=env["provider_id"],
            temperature="98.6", temperature_site=None,
            heart_rate=None, respiratory_rate=None,
            bp_systolic=None, bp_diastolic=None,
            oxygen_saturation=None,
            weight=None, height=None,
            bmi=None, pain_level=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_list_vitals(self, conn, env):
        call_action(mod.health_add_vitals, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            recorded_by_id=env["provider_id"],
            temperature="99.0", temperature_site=None,
            heart_rate="80", respiratory_rate=None,
            bp_systolic=None, bp_diastolic=None,
            oxygen_saturation=None,
            weight=None, height=None,
            bmi=None, pain_level=None,
            notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_vitals, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Diagnosis
# ─────────────────────────────────────────────────────────────────────────────

class TestDiagnosis:
    def test_add_diagnosis(self, conn, env):
        result = call_action(mod.health_add_diagnosis, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            icd10_code="J06.9",
            dx_description="Acute upper respiratory infection",
            diagnosis_type="primary",
            dx_status=None,
            diagnosed_by_id=env["provider_id"],
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["icd10_code"] == "J06.9"

    def test_update_diagnosis(self, conn, env):
        add_res = call_action(mod.health_add_diagnosis, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            icd10_code="E11.9",
            dx_description="Type 2 diabetes",
            diagnosis_type="secondary",
            dx_status=None,
            diagnosed_by_id=env["provider_id"],
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.health_update_diagnosis, conn, ns(
            diagnosis_id=add_res["id"],
            icd10_code=None, dx_description=None,
            diagnosis_type=None, dx_status="resolved",
            notes="Resolved with treatment",
            limit=50, offset=0,
        ))
        assert is_ok(result), result

    def test_list_diagnoses(self, conn, env):
        call_action(mod.health_add_diagnosis, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            icd10_code="I10",
            dx_description="Hypertension",
            diagnosis_type="primary",
            dx_status=None,
            diagnosed_by_id=env["provider_id"],
            notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_diagnoses, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=None, dx_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Prescriptions
# ─────────────────────────────────────────────────────────────────────────────

class TestPrescription:
    def test_add_prescription(self, conn, env):
        result = call_action(mod.health_add_prescription, conn, ns(
            company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            prescriber_id=env["provider_id"],
            medication_name="Amoxicillin",
            ndc_code=None,
            dosage="500mg",
            frequency="3x daily",
            route="oral",
            quantity="30",
            refills="0",
            daw=None,
            rx_start_date="2026-03-15",
            rx_end_date="2026-03-25",
            controlled_schedule=None,
            pharmacy_notes=None,
            rx_status=None,
            discontinued_reason=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["medication_name"] == "Amoxicillin"

    def test_update_prescription(self, conn, env):
        add_res = call_action(mod.health_add_prescription, conn, ns(
            company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            prescriber_id=env["provider_id"],
            medication_name="Ibuprofen",
            ndc_code=None, dosage="400mg", frequency="as needed",
            route="oral", quantity="60", refills="2",
            daw=None, rx_start_date="2026-03-15", rx_end_date=None,
            controlled_schedule=None, pharmacy_notes=None,
            rx_status=None, discontinued_reason=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        # Behavioural: the update must rewrite the stored prescription row,
        # not just return an ok envelope. Read the row before and after
        # through PyPika-built queries, and cross-check through list.
        before = _read_row(conn, "healthclaw_prescription", add_res["id"])
        assert before["status"] == "active"
        assert before["discontinued_reason"] is None

        result = call_action(mod.health_update_prescription, conn, ns(
            prescription_id=add_res["id"],
            medication_name=None, ndc_code=None, dosage=None,
            frequency=None, route=None, quantity=None, refills=None,
            daw=None, rx_start_date=None, rx_end_date=None,
            controlled_schedule=None, pharmacy_notes=None,
            rx_status="discontinued",
            discontinued_reason="Patient intolerance",
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert set(result["updated_fields"]) == {
            "status", "discontinued_reason"}

        after = _read_row(conn, "healthclaw_prescription", add_res["id"])
        assert (after["status"],
                after["discontinued_reason"]) == (
            "discontinued", "Patient intolerance")
        for col in ("id", "naming_series", "encounter_id", "patient_id",
                    "prescriber_id", "medication_name", "dosage", "frequency",
                    "route", "quantity", "refills", "company_id",
                    "created_at"):
            assert after[col] == before[col], col

        listed = call_action(mod.health_list_prescriptions, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=None, rx_status="discontinued",
            limit=50, offset=0,
        ))
        assert is_ok(listed), listed
        assert [r["id"] for r in listed["rows"]] == [add_res["id"]]
        assert listed["rows"][0]["discontinued_reason"] == (
            "Patient intolerance")

        # This action writes only its own row (plus an audit row); it does
        # not reach the general ledger, so there are no legs to assert.
        assert _table_count(conn, "gl_entry") == 0

    def test_update_prescription_refusal_writes_nothing(self, conn, env):
        add_res = call_action(mod.health_add_prescription, conn, ns(
            company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            prescriber_id=env["provider_id"],
            medication_name="Loratadine",
            ndc_code=None, dosage="10mg", frequency="daily",
            route="oral", quantity="30", refills="1",
            daw=None, rx_start_date="2026-03-15", rx_end_date=None,
            controlled_schedule=None, pharmacy_notes=None,
            rx_status=None, discontinued_reason=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        before = _read_row(conn, "healthclaw_prescription", add_res["id"])
        count_before = _table_count(conn, "healthclaw_prescription")

        result = call_action(mod.health_update_prescription, conn, ns(
            prescription_id=add_res["id"],
            medication_name=None, ndc_code=None, dosage=None,
            frequency=None, route=None, quantity=None, refills=None,
            daw=None, rx_start_date=None, rx_end_date=None,
            controlled_schedule=None, pharmacy_notes=None,
            rx_status="bogus",
            discontinued_reason=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)
        assert _refusal_message(result) == (
            "Invalid status: bogus. Must be one of: active, completed, "
            "discontinued, cancelled, on_hold")
        assert _read_row(conn, "healthclaw_prescription",
                         add_res["id"]) == before
        assert _table_count(conn, "healthclaw_prescription") == count_before

    def test_list_prescriptions(self, conn, env):
        result = call_action(mod.health_list_prescriptions, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=None, rx_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result


# ─────────────────────────────────────────────────────────────────────────────
# Procedures & Clinical Notes & Orders
# ─────────────────────────────────────────────────────────────────────────────

class TestProcedure:
    def test_add_procedure(self, conn, env):
        result = call_action(mod.health_add_procedure, conn, ns(
            company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            cpt_code="99213",
            proc_description="Office visit, established patient",
            procedure_date="2026-03-15",
            modifiers=None,
            diagnosis_ids=None,
            anesthesia_type=None,
            body_site=None,
            laterality=None,
            notes=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["cpt_code"] == "99213"

    def test_list_procedures(self, conn, env):
        call_action(mod.health_add_procedure, conn, ns(
            company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            cpt_code="99214",
            proc_description="Office visit, detailed",
            procedure_date="2026-03-15",
            modifiers=None, diagnosis_ids=None,
            anesthesia_type=None, body_site=None,
            laterality=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_procedures, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=None, cpt_code=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


class TestClinicalNote:
    def test_add_soap_note(self, conn, env):
        result = call_action(mod.health_add_clinical_note, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            author_id=env["provider_id"],
            note_type="soap",
            subjective="Patient complains of headache",
            objective="Vitals normal",
            assessment="Tension headache",
            plan_text="OTC pain relief, follow up in 2 weeks",
            body=None,
            addendum=None,
            note_status=None,
            sign=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result

    def test_update_clinical_note(self, conn, env):
        add_res = call_action(mod.health_add_clinical_note, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            author_id=env["provider_id"],
            note_type="progress",
            subjective=None, objective=None, assessment=None,
            plan_text=None, body="Progress note body",
            addendum=None, note_status=None, sign=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.health_update_clinical_note, conn, ns(
            note_id=add_res["id"],
            note_type=None, subjective=None, objective=None,
            assessment=None, plan_text=None,
            body="Updated body", addendum=None,
            note_status=None, sign=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result

    def test_list_clinical_notes(self, conn, env):
        result = call_action(mod.health_list_clinical_notes, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=None, note_type=None,
            note_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result


class TestOrder:
    def test_add_order(self, conn, env):
        result = call_action(mod.health_add_order, conn, ns(
            company_id=env["company_id"],
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            ordering_provider_id=env["provider_id"],
            order_type="lab",
            order_date="2026-03-15",
            priority="routine",
            clinical_indication="Annual screening",
            description=None,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
