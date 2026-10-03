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
import uuid
import pytest
from homehealth_helpers import call_action, ns, is_error, is_ok, load_db_query, seed_patient
from erpclaw_lib.query import Q, P, Table
from erpclaw_lib.seam import table_exists

mod = load_db_query()


def _care_plan_row(conn, plan_id):
    t = Table("healthclaw_care_plan")
    q = Q.from_(t).select(t.star).where(t.id == P())
    return dict(conn.execute(q.get_sql(), (plan_id,)).fetchone())


def _care_plan_snapshot(conn):
    t = Table("healthclaw_care_plan")
    q = Q.from_(t).select(t.star)
    return sorted(json.dumps(dict(r), sort_keys=True, default=str) for r in conn.execute(q.get_sql()).fetchall())


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

    def test_list_care_plans(self, conn, env, db_path):
        assert table_exists("healthclaw_care_plan", db_path)
        first = call_action(mod.homehealth_add_care_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            certifying_physician_id=env["physician_id"],
            start_of_care="2026-03-01",
            certification_period_start="2026-03-01",
            certification_period_end="2026-05-01",
            frequency='{"skilled_nursing": "3x/week"}',
            goals='["Improve mobility"]',
            notes="first plan",
            limit=50, offset=0,
        ))
        assert is_ok(first), first
        second = call_action(mod.homehealth_add_care_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            certifying_physician_id=None,
            start_of_care="2026-05-01",
            certification_period_start="2026-05-01",
            certification_period_end="2026-07-01",
            frequency='{"pt": "2x/week"}',
            goals='["Pain management"]',
            notes="second plan",
            limit=50, offset=0,
        ))
        assert is_ok(second), second
        other_patient = seed_patient(conn, env["company_id"], "Other", "Patient")
        other = call_action(mod.homehealth_add_care_plan, conn, ns(
            patient_id=other_patient,
            company_id=env["company_id"],
            certifying_physician_id=None,
            start_of_care="2026-06-01",
            certification_period_start="2026-06-01",
            certification_period_end="2026-08-01",
            frequency=None, goals=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(other), other
        before = _care_plan_snapshot(conn)
        result = call_action(mod.homehealth_list_care_plans, conn, ns(
            patient_id=env["patient_id"],
            plan_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 2
        assert result["limit"] == 50
        assert result["offset"] == 0
        assert result["has_more"] is False
        assert [r["id"] for r in result["rows"]] == [second["id"], first["id"]]
        stored_first = _care_plan_row(conn, first["id"])
        assert stored_first["patient_id"] == env["patient_id"]
        assert stored_first["company_id"] == env["company_id"]
        assert stored_first["start_of_care"] == "2026-03-01"
        assert stored_first["certification_period_start"] == "2026-03-01"
        assert stored_first["certification_period_end"] == "2026-05-01"
        assert stored_first["frequency"] == '{"skilled_nursing": "3x/week"}'
        assert stored_first["goals"] == '["Improve mobility"]'
        assert stored_first["plan_status"] == "active"
        assert stored_first["notes"] == "first plan"
        stored_second = _care_plan_row(conn, second["id"])
        assert stored_second["patient_id"] == env["patient_id"]
        assert stored_second["start_of_care"] == "2026-05-01"
        assert stored_second["certification_period_start"] == "2026-05-01"
        assert stored_second["certification_period_end"] == "2026-07-01"
        assert stored_second["frequency"] == '{"pt": "2x/week"}'
        assert stored_second["goals"] == '["Pain management"]'
        assert stored_second["plan_status"] == "active"
        assert stored_second["notes"] == "second plan"
        by_id = {r["id"]: r for r in result["rows"]}
        for plan_id, stored in ((first["id"], stored_first), (second["id"], stored_second)):
            assert by_id[plan_id]["patient_id"] == stored["patient_id"]
            assert by_id[plan_id]["company_id"] == stored["company_id"]
            assert by_id[plan_id]["start_of_care"] == stored["start_of_care"]
            assert by_id[plan_id]["certification_period_start"] == stored["certification_period_start"]
            assert by_id[plan_id]["certification_period_end"] == stored["certification_period_end"]
            assert by_id[plan_id]["frequency"] == stored["frequency"]
            assert by_id[plan_id]["goals"] == stored["goals"]
            assert by_id[plan_id]["plan_status"] == stored["plan_status"]
        assert other["id"] not in by_id
        assert _care_plan_snapshot(conn) == before
        # This action is a read-only listing: it reaches no ledger table, so no
        # two-leg balance assertion can hold for it.

    def test_list_care_plans_filters_by_plan_status(self, conn, env):
        active = call_action(mod.homehealth_add_care_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            certifying_physician_id=None,
            start_of_care="2026-03-01",
            certification_period_start="2026-03-01",
            certification_period_end="2026-05-01",
            frequency=None, goals=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(active), active
        moving = call_action(mod.homehealth_add_care_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            certifying_physician_id=None,
            start_of_care="2026-04-01",
            certification_period_start="2026-04-01",
            certification_period_end="2026-06-01",
            frequency=None, goals=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(moving), moving
        upd = call_action(mod.homehealth_update_care_plan, conn, ns(
            care_plan_id=moving["id"],
            certification_period_start=None,
            certification_period_end=None,
            plan_status="discharged",
            frequency=None, goals=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(upd), upd
        before = _care_plan_snapshot(conn)
        discharged = call_action(mod.homehealth_list_care_plans, conn, ns(
            patient_id=env["patient_id"],
            plan_status="discharged",
            limit=50, offset=0,
        ))
        assert is_ok(discharged), discharged
        assert discharged["total_count"] == 1
        assert [r["id"] for r in discharged["rows"]] == [moving["id"]]
        stored = _care_plan_row(conn, moving["id"])
        assert stored["plan_status"] == "discharged"
        assert discharged["rows"][0]["plan_status"] == stored["plan_status"] == "discharged"
        assert discharged["rows"][0]["start_of_care"] == stored["start_of_care"] == "2026-04-01"
        still_active = call_action(mod.homehealth_list_care_plans, conn, ns(
            patient_id=env["patient_id"],
            plan_status="active",
            limit=50, offset=0,
        ))
        assert is_ok(still_active), still_active
        assert still_active["total_count"] == 1
        assert [r["id"] for r in still_active["rows"]] == [active["id"]]
        assert _care_plan_snapshot(conn) == before

    def test_list_care_plans_pagination(self, conn, env):
        made = []
        for start in ("2026-03-01", "2026-04-01", "2026-05-01"):
            res = call_action(mod.homehealth_add_care_plan, conn, ns(
                patient_id=env["patient_id"],
                company_id=env["company_id"],
                certifying_physician_id=None,
                start_of_care=start,
                certification_period_start=start,
                certification_period_end="2026-08-01",
                frequency=None, goals=None, notes=None,
                limit=50, offset=0,
            ))
            assert is_ok(res), res
            made.append((start, res["id"]))
        before = _care_plan_snapshot(conn)
        page1 = call_action(mod.homehealth_list_care_plans, conn, ns(
            patient_id=env["patient_id"],
            plan_status=None,
            limit=2, offset=0,
        ))
        assert is_ok(page1), page1
        assert page1["total_count"] == 3
        assert page1["has_more"] is True
        assert [r["id"] for r in page1["rows"]] == [made[2][1], made[1][1]]
        page2 = call_action(mod.homehealth_list_care_plans, conn, ns(
            patient_id=env["patient_id"],
            plan_status=None,
            limit=2, offset=2,
        ))
        assert is_ok(page2), page2
        assert page2["total_count"] == 3
        assert page2["has_more"] is False
        assert [r["id"] for r in page2["rows"]] == [made[0][1]]
        stored = _care_plan_row(conn, made[0][1])
        assert page2["rows"][0]["start_of_care"] == stored["start_of_care"] == "2026-03-01"
        assert _care_plan_snapshot(conn) == before

    def test_list_care_plans_unknown_filter_returns_empty_and_writes_nothing(self, conn, env):
        seeded = call_action(mod.homehealth_add_care_plan, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            certifying_physician_id=None,
            start_of_care="2026-03-01",
            certification_period_start="2026-03-01",
            certification_period_end="2026-05-01",
            frequency=None, goals=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(seeded), seeded
        before = _care_plan_snapshot(conn)
        missing_patient = call_action(mod.homehealth_list_care_plans, conn, ns(
            patient_id=str(uuid.uuid4()),
            plan_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(missing_patient), missing_patient
        assert missing_patient["total_count"] == 0
        assert missing_patient["rows"] == []
        assert missing_patient["has_more"] is False
        assert missing_patient["limit"] == 50
        assert missing_patient["offset"] == 0
        unknown_status = call_action(mod.homehealth_list_care_plans, conn, ns(
            patient_id=env["patient_id"],
            plan_status="no-such-status",
            limit=50, offset=0,
        ))
        assert is_ok(unknown_status), unknown_status
        assert unknown_status["total_count"] == 0
        assert unknown_status["rows"] == []
        assert unknown_status["has_more"] is False
        assert _care_plan_snapshot(conn) == before
        # list-care-plans declares no required flag and never reports an error for
        # filter values, so there is no input-refusal path to exercise; an unknown
        # filter truthfully returning zero rows with a byte-identical table is the
        # nearest refusal analogue and proves the read half-writes nothing.


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
