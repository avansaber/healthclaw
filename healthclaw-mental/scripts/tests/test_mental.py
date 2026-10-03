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
from mental_helpers import call_action, ns, is_error, is_ok, load_db_query, seed_employee, seed_patient

from erpclaw_lib.query import Q, P, Table, fn, Order
from erpclaw_lib import seam

mod = load_db_query()


def _snapshot_assessments(conn):
    t = Table("healthclaw_assessment")
    q = Q.from_(t).select(
        t.id, t.company_id, t.patient_id, t.instrument, t.responses,
        t.score, t.severity, t.administered_date, t.notes,
    ).orderby(t.id)
    return [dict(r) for r in conn.execute(q.get_sql()).fetchall()]


def _snapshot_group_sessions(conn):
    t = Table("healthclaw_group_session")
    q = Q.from_(t).select(
        t.id, t.company_id, t.provider_id, t.session_date, t.group_name,
        t.group_type, t.topic, t.max_participants, t.participant_ids,
        t.duration_minutes, t.notes, t.status,
    ).orderby(t.id)
    return [dict(r) for r in conn.execute(q.get_sql()).fetchall()]


def _gl_count(conn):
    t = Table("gl_entry")
    return conn.execute(Q.from_(t).select(fn.Count("*")).get_sql()).fetchone()[0]


def _msg(result):
    return result.get("message", "") + result.get("error", "")


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
        # Deepened (was shape-only: asserted is_ok and nothing else).
        # Behavioural now: seeds two stored assessments, then proves the list
        # returns exactly those rows with exact values in administered_date
        # DESC order, and that the list itself writes nothing.
        # No ledger: mentalhealth-list-assessments is a pure read; it never
        # posts to gl_entry, so no two-leg balance assertion can hold. Pinned
        # at zero before and after instead.
        # No money: healthclaw_assessment carries no money column (score is an
        # INTEGER count), so no Decimal assertion applies.
        assert seam.table_exists("healthclaw_assessment")
        assert _gl_count(conn) == 0
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
        assert is_ok(res1), res1
        assert res1["score"] == 12
        assert res1["severity"] == "moderate"
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
        assert is_ok(res2), res2
        assert res2["score"] == 5
        assert res2["severity"] == "mild"

        before = _snapshot_assessments(conn)
        assert len(before) == 2
        result = call_action(mod.mentalhealth_list_assessments, conn, ns(
            patient_id=env["patient_id"],
            instrument=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 2
        assert result["limit"] == 50 and result["offset"] == 0
        assert result["has_more"] is False
        rows = result["rows"]
        assert len(rows) == 2
        assert rows[0]["id"] == res2["id"]
        assert rows[0]["instrument"] == "PHQ-9"
        assert rows[0]["score"] == 5
        assert rows[0]["severity"] == "mild"
        assert rows[0]["administered_date"] == "2026-03-15"
        assert rows[0]["patient_id"] == env["patient_id"]
        assert rows[0]["responses"] == "[1,0,1,0,1,0,1,0,1]"
        assert rows[1]["id"] == res1["id"]
        assert rows[1]["instrument"] == "PHQ-9"
        assert rows[1]["score"] == 12
        assert rows[1]["severity"] == "moderate"
        assert rows[1]["administered_date"] == "2026-01-15"
        assert rows[1]["patient_id"] == env["patient_id"]
        assert rows[1]["responses"] == "[2,1,2,1,1,2,1,1,1]"
        again = {r["id"]: r for r in _snapshot_assessments(conn)}
        assert again[res2["id"]]["score"] == 5
        assert again[res2["id"]]["severity"] == "mild"
        assert again[res1["id"]]["score"] == 12
        assert again[res1["id"]]["severity"] == "moderate"
        assert _snapshot_assessments(conn) == before
        assert _gl_count(conn) == 0

    def test_list_assessments_filters_and_pagination(self, conn, env):
        # Effect, not envelope: the instrument filter returns exactly the
        # matching stored rows, other patients' rows are excluded, and
        # limit/offset pages through the DESC date order.
        res_jan = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument="PHQ-9",
            administered_date="2026-01-15",
            administered_by_id=None,
            responses="[2,1,2,1,1,2,1,1,1]",
            score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        res_feb = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument="GAD-7",
            administered_date="2026-02-10",
            administered_by_id=None,
            responses="[2,2,2,2,2,2,2]",
            score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        res_mar = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument="PHQ-9",
            administered_date="2026-03-15",
            administered_by_id=None,
            responses="[1,0,1,0,1,0,1,0,1]",
            score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(res_jan) and is_ok(res_feb) and is_ok(res_mar)
        assert res_feb["score"] == 14
        assert res_feb["severity"] == "moderate"
        other_patient = seed_patient(conn, env["company_id"], "Other", "Patient")
        res_other = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=other_patient,
            company_id=env["company_id"],
            instrument="PHQ-9",
            administered_date="2026-02-01",
            administered_by_id=None,
            responses="[0,0,0,0,0,0,0,0,0]",
            score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(res_other), res_other
        assert res_other["score"] == 0
        assert res_other["severity"] == "minimal"

        before = _snapshot_assessments(conn)
        assert len(before) == 4
        phq = call_action(mod.mentalhealth_list_assessments, conn, ns(
            patient_id=env["patient_id"],
            instrument="PHQ-9",
            limit=50, offset=0,
        ))
        assert is_ok(phq), phq
        assert phq["total_count"] == 2
        assert [r["id"] for r in phq["rows"]] == [res_mar["id"], res_jan["id"]]
        assert [r["score"] for r in phq["rows"]] == [5, 12]
        gad = call_action(mod.mentalhealth_list_assessments, conn, ns(
            patient_id=env["patient_id"],
            instrument="GAD-7",
            limit=50, offset=0,
        ))
        assert is_ok(gad), gad
        assert gad["total_count"] == 1
        assert gad["rows"][0]["id"] == res_feb["id"]
        assert gad["rows"][0]["score"] == 14
        assert gad["rows"][0]["severity"] == "moderate"
        other = call_action(mod.mentalhealth_list_assessments, conn, ns(
            patient_id=other_patient,
            instrument=None,
            limit=50, offset=0,
        ))
        assert is_ok(other), other
        assert other["total_count"] == 1
        assert other["rows"][0]["id"] == res_other["id"]
        page1 = call_action(mod.mentalhealth_list_assessments, conn, ns(
            patient_id=env["patient_id"],
            instrument=None,
            limit=1, offset=0,
        ))
        assert is_ok(page1), page1
        assert page1["total_count"] == 3
        assert page1["has_more"] is True
        assert [r["id"] for r in page1["rows"]] == [res_mar["id"]]
        page2 = call_action(mod.mentalhealth_list_assessments, conn, ns(
            patient_id=env["patient_id"],
            instrument=None,
            limit=1, offset=1,
        ))
        assert is_ok(page2), page2
        assert [r["id"] for r in page2["rows"]] == [res_feb["id"]]
        assert page2["has_more"] is True
        page3 = call_action(mod.mentalhealth_list_assessments, conn, ns(
            patient_id=env["patient_id"],
            instrument=None,
            limit=1, offset=2,
        ))
        assert is_ok(page3), page3
        assert [r["id"] for r in page3["rows"]] == [res_jan["id"]]
        assert page3["has_more"] is False
        assert _snapshot_assessments(conn) == before
        assert _gl_count(conn) == 0

    def test_list_assessments_refusal_leaves_db_byte_identical(self, conn, env):
        # mentalhealth-list-assessments itself validates no input: every
        # filter is optional and the handler has no err branch, so no refusal
        # of the list action can be constructed. Documented real behaviour:
        # an unknown patient truthfully returns ok with zero rows and writes
        # nothing. The true refusal in this action's orbit is the owning write
        # (add-assessment without --instrument): it must refuse with a
        # truthful message and leave the listed table byte-identical.
        res = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument="PHQ-9",
            administered_date="2026-01-15",
            administered_by_id=None,
            responses="[2,1,2,1,1,2,1,1,1]",
            score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(res), res
        before = _snapshot_assessments(conn)
        assert len(before) == 1
        empty = call_action(mod.mentalhealth_list_assessments, conn, ns(
            patient_id="patient-that-does-not-exist",
            instrument=None,
            limit=50, offset=0,
        ))
        assert is_ok(empty), empty
        assert empty["total_count"] == 0
        assert empty["rows"] == []
        assert _snapshot_assessments(conn) == before
        bad = call_action(mod.mentalhealth_add_assessment, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            instrument=None,
            administered_date="2026-03-15",
            administered_by_id=None,
            responses=None, score=None, severity=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(bad), bad
        assert "--instrument is required" in _msg(bad)
        assert _snapshot_assessments(conn) == before
        result = call_action(mod.mentalhealth_list_assessments, conn, ns(
            patient_id=env["patient_id"],
            instrument=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 1
        assert result["rows"][0]["id"] == res["id"]
        assert result["rows"][0]["score"] == 12
        assert _gl_count(conn) == 0

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
        # Deepened (was routability-only: asserted is_ok and nothing else).
        # Behavioural now: seeds two stored group sessions, then proves the
        # list returns exactly those rows with exact values in session_date
        # DESC order, and that the list itself writes nothing.
        # No ledger: mentalhealth-list-group-sessions is a pure read; it never
        # posts to gl_entry, so no two-leg balance assertion can hold. Pinned
        # at zero before and after instead.
        # No money: healthclaw_group_session carries no money column
        # (durations and counts are INTEGERs), so no Decimal assertion applies.
        assert seam.table_exists("healthclaw_group_session")
        assert _gl_count(conn) == 0
        participants = json.dumps([env["patient_id"]])
        g1 = call_action(mod.mentalhealth_add_group_session, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_date="2026-03-20",
            group_name="Anxiety Management Group",
            group_type="psychoeducation",
            topic="Cognitive restructuring",
            max_participants=12,
            participant_ids=participants,
            duration_minutes=90,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(g1), g1
        assert g1["group_name"] == "Anxiety Management Group"
        assert g1["session_status"] == "completed"
        g2 = call_action(mod.mentalhealth_add_group_session, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_date="2026-03-25",
            group_name="Grief Support Circle",
            group_type="support",
            topic="Coping with loss",
            max_participants=8,
            participant_ids=None,
            duration_minutes=60,
            notes=None, status="scheduled",
            limit=50, offset=0,
        ))
        assert is_ok(g2), g2

        before = _snapshot_group_sessions(conn)
        assert len(before) == 2
        result = call_action(mod.mentalhealth_list_group_sessions, conn, ns(
            provider_id=env["provider_id"],
            status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 2
        assert result["has_more"] is False
        rows = result["rows"]
        assert len(rows) == 2
        assert rows[0]["id"] == g2["id"]
        assert rows[0]["group_name"] == "Grief Support Circle"
        assert rows[0]["session_date"] == "2026-03-25"
        assert rows[0]["group_type"] == "support"
        assert rows[0]["topic"] == "Coping with loss"
        assert rows[0]["max_participants"] == 8
        assert rows[0]["duration_minutes"] == 60
        assert rows[0]["status"] == "scheduled"
        assert rows[0]["provider_id"] == env["provider_id"]
        assert rows[0]["company_id"] == env["company_id"]
        assert rows[1]["id"] == g1["id"]
        assert rows[1]["group_name"] == "Anxiety Management Group"
        assert rows[1]["session_date"] == "2026-03-20"
        assert rows[1]["group_type"] == "psychoeducation"
        assert rows[1]["topic"] == "Cognitive restructuring"
        assert rows[1]["max_participants"] == 12
        assert rows[1]["duration_minutes"] == 90
        assert rows[1]["status"] == "completed"
        assert rows[1]["provider_id"] == env["provider_id"]
        assert rows[1]["participant_ids"] == participants
        again = {r["id"]: r for r in _snapshot_group_sessions(conn)}
        assert again[g2["id"]]["group_name"] == "Grief Support Circle"
        assert again[g2["id"]]["status"] == "scheduled"
        assert again[g1["id"]]["group_name"] == "Anxiety Management Group"
        assert again[g1["id"]]["participant_ids"] == participants
        assert _snapshot_group_sessions(conn) == before
        assert _gl_count(conn) == 0

    def test_list_group_sessions_filters_and_pagination(self, conn, env):
        # Effect, not envelope: the status and search filters return exactly
        # the matching stored rows, another provider's rows are excluded, and
        # limit/offset pages through the DESC date order.
        g1 = call_action(mod.mentalhealth_add_group_session, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_date="2026-03-20",
            group_name="Anxiety Management Group",
            group_type="psychoeducation",
            topic="Cognitive restructuring",
            max_participants=12,
            participant_ids=json.dumps([env["patient_id"]]),
            duration_minutes=90,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        g2 = call_action(mod.mentalhealth_add_group_session, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_date="2026-03-25",
            group_name="Grief Support Circle",
            group_type="support",
            topic="Coping with loss",
            max_participants=8,
            participant_ids=None,
            duration_minutes=60,
            notes=None, status="scheduled",
            limit=50, offset=0,
        ))
        assert is_ok(g1) and is_ok(g2)
        other_provider = seed_employee(conn, env["company_id"], "Dr. Other")
        g3 = call_action(mod.mentalhealth_add_group_session, conn, ns(
            company_id=env["company_id"],
            provider_id=other_provider,
            session_date="2026-03-28",
            group_name="Stress Skills Lab",
            group_type="skills_training",
            topic="Relaxation drills",
            max_participants=10,
            participant_ids=None,
            duration_minutes=45,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(g3), g3

        before = _snapshot_group_sessions(conn)
        assert len(before) == 3
        scheduled = call_action(mod.mentalhealth_list_group_sessions, conn, ns(
            provider_id=env["provider_id"],
            status="scheduled", search=None,
            limit=50, offset=0,
        ))
        assert is_ok(scheduled), scheduled
        assert scheduled["total_count"] == 1
        assert scheduled["rows"][0]["id"] == g2["id"]
        grief = call_action(mod.mentalhealth_list_group_sessions, conn, ns(
            provider_id=env["provider_id"],
            status=None, search="Grief",
            limit=50, offset=0,
        ))
        assert is_ok(grief), grief
        assert grief["total_count"] == 1
        assert grief["rows"][0]["id"] == g2["id"]
        cognitive = call_action(mod.mentalhealth_list_group_sessions, conn, ns(
            provider_id=env["provider_id"],
            status=None, search="Cognitive",
            limit=50, offset=0,
        ))
        assert is_ok(cognitive), cognitive
        assert cognitive["total_count"] == 1
        assert cognitive["rows"][0]["id"] == g1["id"]
        others = call_action(mod.mentalhealth_list_group_sessions, conn, ns(
            provider_id=other_provider,
            status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(others), others
        assert others["total_count"] == 1
        assert others["rows"][0]["id"] == g3["id"]
        mine = call_action(mod.mentalhealth_list_group_sessions, conn, ns(
            provider_id=env["provider_id"],
            status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(mine), mine
        assert mine["total_count"] == 2
        assert [r["id"] for r in mine["rows"]] == [g2["id"], g1["id"]]
        page1 = call_action(mod.mentalhealth_list_group_sessions, conn, ns(
            provider_id=env["provider_id"],
            status=None, search=None,
            limit=1, offset=0,
        ))
        assert is_ok(page1), page1
        assert page1["total_count"] == 2
        assert page1["has_more"] is True
        assert [r["id"] for r in page1["rows"]] == [g2["id"]]
        page2 = call_action(mod.mentalhealth_list_group_sessions, conn, ns(
            provider_id=env["provider_id"],
            status=None, search=None,
            limit=1, offset=1,
        ))
        assert is_ok(page2), page2
        assert [r["id"] for r in page2["rows"]] == [g1["id"]]
        assert page2["has_more"] is False
        assert _snapshot_group_sessions(conn) == before
        assert _gl_count(conn) == 0

    def test_list_group_sessions_refusal_leaves_db_byte_identical(self, conn, env):
        # mentalhealth-list-group-sessions itself validates no input: every
        # filter is optional and the handler has no err branch, so no refusal
        # of the list action can be constructed. Documented real behaviour:
        # an unknown provider truthfully returns ok with zero rows and writes
        # nothing. The true refusal in this action's orbit is the owning write
        # (add-group-session without --group-name): it must refuse with a
        # truthful message and leave the listed table byte-identical.
        g1 = call_action(mod.mentalhealth_add_group_session, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_date="2026-03-20",
            group_name="Anxiety Management Group",
            group_type="psychoeducation",
            topic="Cognitive restructuring",
            max_participants=12,
            participant_ids=json.dumps([env["patient_id"]]),
            duration_minutes=90,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(g1), g1
        before = _snapshot_group_sessions(conn)
        assert len(before) == 1
        empty = call_action(mod.mentalhealth_list_group_sessions, conn, ns(
            provider_id="provider-that-does-not-exist",
            status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(empty), empty
        assert empty["total_count"] == 0
        assert empty["rows"] == []
        assert _snapshot_group_sessions(conn) == before
        bad = call_action(mod.mentalhealth_add_group_session, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            session_date="2026-03-20",
            group_name=None,
            group_type=None, topic=None,
            max_participants=None, participant_ids=None,
            duration_minutes=None, notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_error(bad), bad
        assert "--group-name is required" in _msg(bad)
        assert _snapshot_group_sessions(conn) == before
        result = call_action(mod.mentalhealth_list_group_sessions, conn, ns(
            provider_id=env["provider_id"],
            status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 1
        assert result["rows"][0]["id"] == g1["id"]
        assert result["rows"][0]["group_name"] == "Anxiety Management Group"
        assert _gl_count(conn) == 0
