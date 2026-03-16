"""Tests for HealthClaw Dental domain.

Actions tested (12):
  - dental-add-tooth-chart-entry
  - dental-update-tooth-chart-entry
  - dental-get-tooth-chart
  - dental-add-dental-procedure
  - dental-list-dental-procedures
  - dental-add-treatment-plan
  - dental-update-treatment-plan
  - dental-list-treatment-plans
  - dental-add-perio-exam
  - dental-get-perio-exam
  - dental-list-perio-exams
  - dental-compare-perio-exams
"""
import json
import pytest
from dental_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Tooth Chart
# ─────────────────────────────────────────────────────────────────────────────

class TestToothChart:
    def test_add_tooth_chart_entry(self, conn, env):
        result = call_action(mod.dental_add_tooth_chart_entry, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            tooth_number="14",
            condition="cavity",
            noted_date="2026-03-15",
            tooth_system=None,
            surface="MO",
            condition_detail="Class II",
            noted_by_id=env["provider_id"],
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["tooth_number"] == "14"
        assert result["condition"] == "cavity"

    def test_add_tooth_chart_entry_missing_tooth(self, conn, env):
        result = call_action(mod.dental_add_tooth_chart_entry, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            tooth_number=None,
            condition="cavity",
            noted_date="2026-03-15",
            tooth_system=None, surface=None,
            condition_detail=None, noted_by_id=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_add_tooth_chart_entry_invalid_tooth(self, conn, env):
        result = call_action(mod.dental_add_tooth_chart_entry, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            tooth_number="99",
            condition="cavity",
            noted_date="2026-03-15",
            tooth_system=None, surface=None,
            condition_detail=None, noted_by_id=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_tooth_chart_entry(self, conn, env):
        add_res = call_action(mod.dental_add_tooth_chart_entry, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            tooth_number="3",
            condition="fracture",
            noted_date="2026-03-15",
            tooth_system=None, surface=None,
            condition_detail=None, noted_by_id=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.dental_update_tooth_chart_entry, conn, ns(
            tooth_chart_id=add_res["id"],
            condition="restored",
            condition_detail=None,
            surface=None,
            status="resolved",
            notes="Restored with crown",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "condition" in result["updated_fields"]

    def test_get_tooth_chart(self, conn, env):
        call_action(mod.dental_add_tooth_chart_entry, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            tooth_number="19",
            condition="decay",
            noted_date="2026-03-15",
            tooth_system=None, surface="MOD",
            condition_detail=None, noted_by_id=None, notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.dental_get_tooth_chart, conn, ns(
            patient_id=env["patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["tooth_count"] >= 1
        assert result["total_entries"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Dental Procedures
# ─────────────────────────────────────────────────────────────────────────────

class TestDentalProcedure:
    def test_add_dental_procedure(self, conn, env):
        result = call_action(mod.dental_add_dental_procedure, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            cdt_code="D2391",
            cdt_description="Resin-based composite, one surface, posterior",
            tooth_number="14",
            surface="MO",
            quadrant=None,
            procedure_date="2026-03-15",
            fee="250.00",
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["cdt_code"] == "D2391"
        assert result["fee"] == "250.00"

    def test_add_dental_procedure_missing_cdt(self, conn, env):
        result = call_action(mod.dental_add_dental_procedure, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            cdt_code=None,
            cdt_description=None,
            tooth_number=None, surface=None, quadrant=None,
            procedure_date="2026-03-15",
            fee=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_list_dental_procedures(self, conn, env):
        call_action(mod.dental_add_dental_procedure, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            cdt_code="D0150",
            cdt_description="Comprehensive oral evaluation",
            tooth_number=None, surface=None, quadrant=None,
            procedure_date="2026-03-15",
            fee="85.00", notes=None, status=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.dental_list_dental_procedures, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=None, cdt_code=None,
            status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Treatment Plans
# ─────────────────────────────────────────────────────────────────────────────

class TestTreatmentPlan:
    def test_add_treatment_plan(self, conn, env):
        result = call_action(mod.dental_add_treatment_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            plan_name="Comprehensive Restoration Plan",
            plan_date="2026-03-15",
            phases='[{"phase": 1, "description": "Fillings"}, {"phase": 2, "description": "Crown"}]',
            estimated_total="1500.00",
            insurance_estimate="900.00",
            patient_estimate="600.00",
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["plan_name"] == "Comprehensive Restoration Plan"
        assert result["estimated_total"] == "1500.00"

    def test_add_treatment_plan_missing_name(self, conn, env):
        result = call_action(mod.dental_add_treatment_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            plan_name=None,
            plan_date="2026-03-15",
            phases=None, estimated_total=None,
            insurance_estimate=None, patient_estimate=None,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_treatment_plan(self, conn, env):
        add_res = call_action(mod.dental_add_treatment_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            plan_name="Update Test Plan",
            plan_date="2026-03-15",
            phases=None, estimated_total=None,
            insurance_estimate=None, patient_estimate=None,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.dental_update_treatment_plan, conn, ns(
            treatment_plan_id=add_res["id"],
            plan_name=None,
            status="accepted",
            estimated_total="2000.00",
            insurance_estimate=None,
            patient_estimate=None,
            phases=None, notes="Patient accepted plan",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "status" in result["updated_fields"]

    def test_list_treatment_plans(self, conn, env):
        call_action(mod.dental_add_treatment_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            plan_name="List Test Plan",
            plan_date="2026-03-15",
            phases=None, estimated_total=None,
            insurance_estimate=None, patient_estimate=None,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.dental_list_treatment_plans, conn, ns(
            patient_id=env["patient_id"],
            status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Perio Exams
# ─────────────────────────────────────────────────────────────────────────────

class TestPerioExam:
    def _add_perio_exam(self, conn, env, exam_date="2026-03-15", measurements=None, bleeding_sites=None):
        return call_action(mod.dental_add_perio_exam, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            exam_date=exam_date,
            measurements=measurements or '{"3": [3, 2, 3, 2, 3, 2], "14": [4, 3, 4, 3, 4, 3]}',
            bleeding_sites=bleeding_sites or '["3", "14"]',
            furcation_data=None,
            mobility_data=None,
            recession_data=None,
            plaque_score="25",
            notes=None,
            limit=50, offset=0,
        ))

    def test_add_perio_exam(self, conn, env):
        result = self._add_perio_exam(conn, env)
        assert is_ok(result), result
        assert result["exam_date"] == "2026-03-15"

    def test_get_perio_exam(self, conn, env):
        add_res = self._add_perio_exam(conn, env)
        assert is_ok(add_res)
        result = call_action(mod.dental_get_perio_exam, conn, ns(
            perio_exam_id=add_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["id"] == add_res["id"]
        # measurements should be parsed to dict
        assert isinstance(result["measurements"], dict)

    def test_list_perio_exams(self, conn, env):
        self._add_perio_exam(conn, env)
        result = call_action(mod.dental_list_perio_exams, conn, ns(
            patient_id=env["patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1

    def test_compare_perio_exams(self, conn, env):
        res1 = self._add_perio_exam(conn, env, exam_date="2026-01-15",
            measurements='{"3": [4, 5, 4, 5, 4, 5], "14": [5, 4, 5, 4, 5, 4]}',
            bleeding_sites='["3", "14", "19"]')
        res2 = self._add_perio_exam(conn, env, exam_date="2026-06-15",
            measurements='{"3": [2, 2, 2, 2, 2, 2], "14": [3, 3, 3, 3, 3, 3]}',
            bleeding_sites='["3"]')
        assert is_ok(res1) and is_ok(res2)
        result = call_action(mod.dental_compare_perio_exams, conn, ns(
            exam_id_1=res1["id"],
            exam_id_2=res2["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "improvements" in result
        assert result["bleeding_change"] < 0  # fewer bleeding sites

    def test_compare_perio_exams_missing_id(self, conn, env):
        result = call_action(mod.dental_compare_perio_exams, conn, ns(
            exam_id_1=None,
            exam_id_2=None,
            limit=50, offset=0,
        ))
        assert is_error(result)
