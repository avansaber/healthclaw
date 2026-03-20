"""Tests for HealthClaw Mental Health domain.

Actions tested (14):
  - mentalhealth-add-therapy-session
  - mentalhealth-update-therapy-session
  - mentalhealth-list-therapy-sessions
  - mentalhealth-add-assessment
  - mentalhealth-get-assessment
  - mentalhealth-list-assessments
  - mentalhealth-compare-assessments
  - mentalhealth-add-treatment-goal
  - mentalhealth-update-treatment-goal
  - mentalhealth-list-treatment-goals
  - mentalhealth-add-group-session
  - mentalhealth-update-group-session
  - mentalhealth-list-group-sessions
  - mentalhealth-get-group-session
"""
import json
import pytest
from mental_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Therapy Sessions
# ─────────────────────────────────────────────────────────────────────────────

class TestTherapySession:
    def test_add_therapy_session(self, conn, env):
        result = call_action(mod.mentalhealth_add_therapy_session, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_type="individual",
            modality="cbt",
            duration_minutes="50",
            session_number="1",
            notes="Initial CBT session",
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["session_type"] == "individual"

    def test_add_therapy_session_missing_type(self, conn, env):
        result = call_action(mod.mentalhealth_add_therapy_session, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_type=None,
            modality=None, duration_minutes=None,
            session_number=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_therapy_session(self, conn, env):
        add_res = call_action(mod.mentalhealth_add_therapy_session, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_type="individual",
            modality=None, duration_minutes=None,
            session_number=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.mentalhealth_update_therapy_session, conn, ns(
            therapy_session_id=add_res["id"],
            session_type=None,
            modality="dbt",
            duration_minutes="60",
            notes="Updated to DBT",
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "modality" in result["updated_fields"]

    def test_list_therapy_sessions(self, conn, env):
        call_action(mod.mentalhealth_add_therapy_session, conn, ns(
            encounter_id=env["encounter_id"],
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_type="couples",
            modality=None, duration_minutes=None,
            session_number=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.mentalhealth_list_therapy_sessions, conn, ns(
            patient_id=env["patient_id"],
            provider_id=None, status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Assessments (PHQ-9, GAD-7, AUDIT auto-scoring)
# ─────────────────────────────────────────────────────────────────────────────

class TestAssessment:
    def test_add_assessment_phq9_auto_score(self, conn, env):
        # PHQ-9: 9 items, score 0-27. [1,1,2,1,0,1,2,0,1] = 9 -> mild
        result = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument="PHQ-9",
            administered_date="2026-03-15",
            administered_by_id=env["provider_id"],
            responses="[1,1,2,1,0,1,2,0,1]",
            score=None,
            severity=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["instrument"] == "PHQ-9"
        assert result["score"] == 9
        assert result["severity"] == "mild"

    def test_add_assessment_gad7_auto_score(self, conn, env):
        # GAD-7: 7 items, score 0-21. [2,2,3,2,2,3,2] = 16 -> severe
        result = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument="GAD-7",
            administered_date="2026-03-15",
            administered_by_id=env["provider_id"],
            responses="[2,2,3,2,2,3,2]",
            score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["score"] == 16
        assert result["severity"] == "severe"

    def test_add_assessment_audit_auto_score(self, conn, env):
        # AUDIT: 10 items, score 0-40. [0,0,0,0,0,0,0,0,0,0] = 0 -> low_risk
        result = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument="AUDIT",
            administered_date="2026-03-15",
            administered_by_id=None,
            responses="[0,0,0,0,0,0,0,0,0,0]",
            score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["score"] == 0
        assert result["severity"] == "low_risk"

    def test_add_assessment_missing_instrument(self, conn, env):
        result = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument=None,
            administered_date="2026-03-15",
            administered_by_id=None,
            responses=None, score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_get_assessment(self, conn, env):
        add_res = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument="PHQ-9",
            administered_date="2026-03-15",
            administered_by_id=None,
            responses="[0,0,0,0,0,0,0,0,0]",
            score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.mentalhealth_get_assessment, conn, ns(
            assessment_id=add_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["id"] == add_res["id"]
        # responses should be parsed to list
        assert isinstance(result["responses"], list)

    def test_list_assessments(self, conn, env):
        result = call_action(mod.mentalhealth_list_assessments, conn, ns(
            patient_id=env["patient_id"],
            instrument=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result

    def test_compare_assessments(self, conn, env):
        # First assessment: moderate depression (score 12)
        res1 = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument="PHQ-9",
            administered_date="2026-01-15",
            administered_by_id=None,
            responses="[2,1,2,1,1,2,1,1,1]",
            score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        # Second assessment: mild (score 5)
        res2 = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument="PHQ-9",
            administered_date="2026-03-15",
            administered_by_id=None,
            responses="[1,0,1,0,1,0,1,0,1]",
            score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(res1) and is_ok(res2)
        result = call_action(mod.mentalhealth_compare_assessments, conn, ns(
            assessment_id_1=res1["id"],
            assessment_id_2=res2["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["improved"] is True
        assert result["score_change"] < 0


# ─────────────────────────────────────────────────────────────────────────────
# Treatment Goals
# ─────────────────────────────────────────────────────────────────────────────

class TestTreatmentGoal:
    def test_add_treatment_goal(self, conn, env):
        result = call_action(mod.mentalhealth_add_treatment_goal, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            goal_description="Reduce anxiety symptoms to mild range on GAD-7",
            target_date="2026-06-15",
            baseline_measure="GAD-7 score: 16 (severe)",
            current_measure=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["goal_description"] == "Reduce anxiety symptoms to mild range on GAD-7"

    def test_update_treatment_goal(self, conn, env):
        add_res = call_action(mod.mentalhealth_add_treatment_goal, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=None,
            goal_description="Improve sleep hygiene",
            target_date=None, baseline_measure=None,
            current_measure=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.mentalhealth_update_treatment_goal, conn, ns(
            treatment_goal_id=add_res["id"],
            goal_description=None,
            target_date=None,
            current_measure="Sleeping 7 hours, up from 4",
            goal_status="achieved",
            notes="Goal met",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "goal_status" in result["updated_fields"]

    def test_list_treatment_goals(self, conn, env):
        call_action(mod.mentalhealth_add_treatment_goal, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            provider_id=None,
            goal_description="List test goal",
            target_date=None, baseline_measure=None,
            current_measure=None, notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.mentalhealth_list_treatment_goals, conn, ns(
            patient_id=env["patient_id"],
            goal_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Group Sessions
# ─────────────────────────────────────────────────────────────────────────────

class TestGroupSession:
    def test_add_group_session(self, conn, env):
        result = call_action(mod.mentalhealth_add_group_session, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_date="2026-03-20",
            group_name="Anxiety Management Group",
            group_type="psychoeducation",
            topic="Cognitive restructuring",
            max_participants=12,
            participant_ids=json.dumps([env["patient_id"]]),
            duration_minutes="90",
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["group_name"] == "Anxiety Management Group"

    def test_add_group_session_missing_name(self, conn, env):
        result = call_action(mod.mentalhealth_add_group_session, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_date="2026-03-20",
            group_name=None,
            group_type=None, topic=None,
            max_participants=None, participant_ids=None,
            duration_minutes=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_group_session(self, conn, env):
        add_res = call_action(mod.mentalhealth_add_group_session, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_date="2026-03-25",
            group_name="Update Test Group",
            group_type=None, topic=None,
            max_participants=None, participant_ids=None,
            duration_minutes=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.mentalhealth_update_group_session, conn, ns(
            group_session_id=add_res["id"],
            group_name=None,
            topic="Updated topic",
            group_type="support",
            duration_minutes="120",
            max_participants=None,
            participant_ids=None,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "topic" in result["updated_fields"]

    def test_get_group_session(self, conn, env):
        add_res = call_action(mod.mentalhealth_add_group_session, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_date="2026-03-28",
            group_name="Get Test Group",
            group_type=None, topic=None,
            max_participants=None,
            participant_ids=json.dumps([env["patient_id"]]),
            duration_minutes=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.mentalhealth_get_group_session, conn, ns(
            group_session_id=add_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["id"] == add_res["id"]
        # participant_ids should be parsed to list
        assert isinstance(result["participant_ids"], list)

    def test_list_group_sessions(self, conn, env):
        result = call_action(mod.mentalhealth_list_group_sessions, conn, ns(
            provider_id=env["provider_id"],
            status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
