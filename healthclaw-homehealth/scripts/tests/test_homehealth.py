"""Tests for HealthClaw Home Health domain.

Actions tested (12):
  - homehealth-add-home-visit
  - homehealth-update-home-visit
  - homehealth-list-home-visits
  - homehealth-add-care-plan
  - homehealth-update-care-plan
  - homehealth-get-care-plan
  - homehealth-list-care-plans
  - homehealth-add-oasis-assessment
  - homehealth-list-oasis-assessments
  - homehealth-add-aide-assignment
  - homehealth-update-aide-assignment
  - homehealth-list-aide-assignments
"""
import json
import pytest
from homehealth_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Home Visits
# ─────────────────────────────────────────────────────────────────────────────

class TestHomeVisit:
    def test_add_home_visit(self, conn, env):
        result = call_action(mod.homehealth_add_home_visit, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            clinician_id=env["clinician_id"],
            visit_date="2026-03-15",
            visit_type="skilled_nursing",
            start_time="09:00",
            end_time="10:30",
            travel_time_minutes="20",
            mileage="12.50",
            visit_status=None,
            notes="Initial home visit",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["visit_type"] == "skilled_nursing"
        assert result["visit_date"] == "2026-03-15"

    def test_add_home_visit_missing_type(self, conn, env):
        result = call_action(mod.homehealth_add_home_visit, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            clinician_id=env["clinician_id"],
            visit_date="2026-03-15",
            visit_type=None,
            start_time=None, end_time=None,
            travel_time_minutes=None, mileage=None,
            visit_status=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_home_visit(self, conn, env):
        add_res = call_action(mod.homehealth_add_home_visit, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            clinician_id=env["clinician_id"],
            visit_date="2026-03-16",
            visit_type="pt",
            start_time=None, end_time=None,
            travel_time_minutes=None, mileage=None,
            visit_status=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.homehealth_update_home_visit, conn, ns(
            home_visit_id=add_res["id"],
            visit_date=None, visit_type=None,
            start_time="10:00", end_time="11:00",
            travel_time_minutes="15",
            mileage="8.50",
            visit_status="completed",
            notes="PT session completed",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "visit_status" in result["updated_fields"]

    def test_list_home_visits(self, conn, env):
        call_action(mod.homehealth_add_home_visit, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            clinician_id=env["clinician_id"],
            visit_date="2026-03-17",
            visit_type="ot",
            start_time=None, end_time=None,
            travel_time_minutes=None, mileage=None,
            visit_status=None, notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.homehealth_list_home_visits, conn, ns(
            patient_id=env["patient_id"],
            clinician_id=None, visit_type=None,
            visit_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Care Plans
# ─────────────────────────────────────────────────────────────────────────────

class TestCarePlan:
    def test_add_care_plan(self, conn, env):
        result = call_action(mod.homehealth_add_care_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            certifying_physician_id=env["physician_id"],
            start_of_care="2026-03-01",
            certification_period_start="2026-03-01",
            certification_period_end="2026-05-01",
            frequency='{"skilled_nursing": "3x/week", "pt": "2x/week"}',
            goals='["Improve mobility", "Wound care management"]',
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["start_of_care"] == "2026-03-01"

    def test_add_care_plan_missing_dates(self, conn, env):
        result = call_action(mod.homehealth_add_care_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            certifying_physician_id=None,
            start_of_care=None,
            certification_period_start=None,
            certification_period_end=None,
            frequency=None, goals=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_care_plan(self, conn, env):
        add_res = call_action(mod.homehealth_add_care_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            certifying_physician_id=None,
            start_of_care="2026-04-01",
            certification_period_start="2026-04-01",
            certification_period_end="2026-06-01",
            frequency=None, goals=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.homehealth_update_care_plan, conn, ns(
            care_plan_id=add_res["id"],
            certification_period_start=None,
            certification_period_end="2026-08-01",
            plan_status="recertified",
            frequency=None, goals=None,
            notes="Extended certification",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "plan_status" in result["updated_fields"]

    def test_get_care_plan(self, conn, env):
        add_res = call_action(mod.homehealth_add_care_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            certifying_physician_id=None,
            start_of_care="2026-05-01",
            certification_period_start="2026-05-01",
            certification_period_end="2026-07-01",
            frequency='{"skilled_nursing": "2x/week"}',
            goals='["Pain management"]',
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.homehealth_get_care_plan, conn, ns(
            care_plan_id=add_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["id"] == add_res["id"]
        # JSON fields should be parsed
        assert isinstance(result["frequency"], dict)
        assert isinstance(result["goals"], list)

    def test_list_care_plans(self, conn, env):
        result = call_action(mod.homehealth_list_care_plans, conn, ns(
            patient_id=env["patient_id"],
            plan_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result


# ─────────────────────────────────────────────────────────────────────────────
# OASIS Assessments
# ─────────────────────────────────────────────────────────────────────────────

class TestOasisAssessment:
    def test_add_oasis_assessment(self, conn, env):
        result = call_action(mod.homehealth_add_oasis_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            clinician_id=env["clinician_id"],
            assessment_type="soc",
            assessment_date="2026-03-01",
            m_items='{"M1033": "1", "M1800": "2", "M1810": "3"}',
            notes="Start of care assessment",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["assessment_type"] == "soc"

    def test_add_oasis_missing_type(self, conn, env):
        result = call_action(mod.homehealth_add_oasis_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            clinician_id=env["clinician_id"],
            assessment_type=None,
            assessment_date="2026-03-01",
            m_items=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_list_oasis_assessments(self, conn, env):
        call_action(mod.homehealth_add_oasis_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            clinician_id=env["clinician_id"],
            assessment_type="recert",
            assessment_date="2026-05-01",
            m_items=None, notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.homehealth_list_oasis_assessments, conn, ns(
            patient_id=env["patient_id"],
            assessment_type=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Aide Assignments
# ─────────────────────────────────────────────────────────────────────────────

class TestAideAssignment:
    def test_add_aide_assignment(self, conn, env):
        result = call_action(mod.homehealth_add_aide_assignment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            aide_id=env["aide_id"],
            assignment_start="2026-03-15",
            assignment_end="2026-06-15",
            days_of_week='["monday", "wednesday", "friday"]',
            visit_time="08:00",
            tasks='["bathing", "meal_prep", "light_housekeeping"]',
            supervisor_id=env["clinician_id"],
            supervision_due_date="2026-04-15",
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["aide_id"] == env["aide_id"]

    def test_add_aide_assignment_missing_start(self, conn, env):
        result = call_action(mod.homehealth_add_aide_assignment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            aide_id=env["aide_id"],
            assignment_start=None,
            assignment_end=None, days_of_week=None,
            visit_time=None, tasks=None,
            supervisor_id=None, supervision_due_date=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_aide_assignment(self, conn, env):
        add_res = call_action(mod.homehealth_add_aide_assignment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            aide_id=env["aide_id"],
            assignment_start="2026-04-01",
            assignment_end=None, days_of_week=None,
            visit_time=None, tasks=None,
            supervisor_id=None, supervision_due_date=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.homehealth_update_aide_assignment, conn, ns(
            aide_assignment_id=add_res["id"],
            assignment_end="2026-07-01",
            visit_time="09:00",
            supervision_due_date="2026-05-01",
            status="on_hold",
            days_of_week=None, tasks=None,
            supervisor_id=None, notes="Temporarily on hold",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "status" in result["updated_fields"]

    def test_list_aide_assignments(self, conn, env):
        call_action(mod.homehealth_add_aide_assignment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            aide_id=env["aide_id"],
            assignment_start="2026-05-01",
            assignment_end=None, days_of_week=None,
            visit_time=None, tasks=None,
            supervisor_id=None, supervision_due_date=None,
            notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.homehealth_list_aide_assignments, conn, ns(
            patient_id=env["patient_id"],
            aide_id=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1
