"""Tests for HealthClaw appointments domain.

Actions tested:
  - health-add-provider-schedule
  - health-update-provider-schedule
  - health-list-provider-schedules
  - health-add-schedule-block
  - health-list-schedule-blocks
  - health-add-appointment
  - health-update-appointment
  - health-get-appointment
  - health-list-appointments
  - health-check-in-appointment
  - health-check-out-appointment
  - health-cancel-appointment
  - health-add-waitlist
  - health-list-waitlist
"""
import pytest
from health_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Provider Schedules
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderSchedule:
    def test_add_schedule(self, conn, env):
        result = call_action(mod.health_add_provider_schedule, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            day_of_week="1",
            start_time="09:00",
            end_time="17:00",
            slot_duration="30",
            location="Room 101",
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["day_of_week"] == 1

    def test_add_schedule_missing_day(self, conn, env):
        result = call_action(mod.health_add_provider_schedule, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            day_of_week=None,
            start_time="09:00",
            end_time="17:00",
            slot_duration=None,
            location=None, status=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_schedule(self, conn, env):
        add_res = call_action(mod.health_add_provider_schedule, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            day_of_week="2",
            start_time="08:00",
            end_time="16:00",
            slot_duration=None,
            location=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(add_res)
        result = call_action(mod.health_update_provider_schedule, conn, ns(
            schedule_id=add_res["id"],
            company_id=env["company_id"],
            start_time=None, end_time=None,
            location="Room 202",
            status=None, slot_duration=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "location" in result["updated_fields"]

    def test_list_schedules(self, conn, env):
        call_action(mod.health_add_provider_schedule, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            day_of_week="3",
            start_time="09:00",
            end_time="17:00",
            slot_duration=None,
            location=None, status=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_provider_schedules, conn, ns(
            provider_id=env["provider_id"],
            company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Schedule Blocks
# ─────────────────────────────────────────────────────────────────────────────

class TestScheduleBlock:
    def test_add_block(self, conn, env):
        result = call_action(mod.health_add_schedule_block, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            block_date="2026-03-15",
            start_time="12:00",
            end_time="13:00",
            reason="meeting",
            notes="Staff meeting",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["reason"] == "meeting"

    def test_list_blocks(self, conn, env):
        call_action(mod.health_add_schedule_block, conn, ns(
            company_id=env["company_id"],
            provider_id=env["provider_id"],
            block_date="2026-03-20",
            start_time=None, end_time=None,
            reason="vacation",
            notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_schedule_blocks, conn, ns(
            provider_id=env["provider_id"],
            company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Appointments
# ─────────────────────────────────────────────────────────────────────────────

class TestAppointment:
    def _add_appointment(self, conn, env):
        return call_action(mod.health_add_appointment, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            appointment_date="2026-03-20",
            start_time="10:00",
            end_time="10:30",
            duration_minutes="30",
            appointment_type="follow_up",
            chief_complaint="Annual checkup",
            location="Room A",
            notes=None,
            cancellation_reason=None,
            new_provider_id=None,
            limit=50, offset=0, search=None, status=None,
        ))

    def test_add_appointment(self, conn, env):
        result = self._add_appointment(conn, env)
        assert is_ok(result), result
        assert "naming_series" in result
        assert "id" in result

    def test_add_appointment_missing_date(self, conn, env):
        result = call_action(mod.health_add_appointment, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            appointment_date=None,
            start_time="10:00",
            end_time="10:30",
            duration_minutes=None,
            appointment_type=None,
            chief_complaint=None,
            location=None, notes=None,
            cancellation_reason=None, new_provider_id=None,
            limit=50, offset=0, search=None, status=None,
        ))
        assert is_error(result)

    def test_get_appointment(self, conn, env):
        add_res = self._add_appointment(conn, env)
        assert is_ok(add_res)
        result = call_action(mod.health_get_appointment, conn, ns(
            appointment_id=add_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["id"] == add_res["id"]

    def test_update_appointment(self, conn, env):
        add_res = self._add_appointment(conn, env)
        assert is_ok(add_res)
        result = call_action(mod.health_update_appointment, conn, ns(
            appointment_id=add_res["id"],
            appointment_date=None, start_time=None, end_time=None,
            appointment_type=None,
            chief_complaint="Updated complaint",
            location=None, notes=None,
            duration_minutes=None,
            new_provider_id=None,
            cancellation_reason=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "chief_complaint" in result["updated_fields"]

    def test_list_appointments(self, conn, env):
        self._add_appointment(conn, env)
        result = call_action(mod.health_list_appointments, conn, ns(
            company_id=env["company_id"],
            patient_id=None, provider_id=None,
            appointment_date=None, status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Check-in / Check-out / Cancel
# ─────────────────────────────────────────────────────────────────────────────

class TestAppointmentWorkflow:
    def _add_appointment(self, conn, env):
        return call_action(mod.health_add_appointment, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            appointment_date="2026-03-25",
            start_time="14:00",
            end_time="14:30",
            duration_minutes=None,
            appointment_type="new_patient",
            chief_complaint=None,
            location=None, notes=None,
            cancellation_reason=None, new_provider_id=None,
            limit=50, offset=0, search=None, status=None,
        ))

    def test_check_in(self, conn, env):
        add_res = self._add_appointment(conn, env)
        assert is_ok(add_res)
        result = call_action(mod.health_check_in_appointment, conn, ns(
            appointment_id=add_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result.get("check_in_time") is not None

    def test_check_out(self, conn, env):
        add_res = self._add_appointment(conn, env)
        assert is_ok(add_res)
        # Check in first
        call_action(mod.health_check_in_appointment, conn, ns(
            appointment_id=add_res["id"],
            limit=50, offset=0,
        ))
        result = call_action(mod.health_check_out_appointment, conn, ns(
            appointment_id=add_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result.get("check_out_time") is not None

    def test_cancel(self, conn, env):
        add_res = self._add_appointment(conn, env)
        assert is_ok(add_res)
        result = call_action(mod.health_cancel_appointment, conn, ns(
            appointment_id=add_res["id"],
            cancellation_reason="Patient request",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "id" in result

    def test_cannot_check_in_completed(self, conn, env):
        add_res = self._add_appointment(conn, env)
        assert is_ok(add_res)
        call_action(mod.health_check_in_appointment, conn, ns(
            appointment_id=add_res["id"], limit=50, offset=0))
        call_action(mod.health_check_out_appointment, conn, ns(
            appointment_id=add_res["id"], limit=50, offset=0))
        result = call_action(mod.health_check_in_appointment, conn, ns(
            appointment_id=add_res["id"], limit=50, offset=0))
        assert is_error(result)


# ─────────────────────────────────────────────────────────────────────────────
# Waitlist
# ─────────────────────────────────────────────────────────────────────────────

class TestWaitlist:
    def test_add_waitlist(self, conn, env):
        result = call_action(mod.health_add_waitlist, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=env["provider_id"],
            preferred_date_start="2026-04-01",
            preferred_date_end="2026-04-15",
            preferred_time_start="09:00",
            preferred_time_end="12:00",
            appointment_type="follow_up",
            priority="high",
            notes=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["priority"] == "high"
        assert "id" in result

    def test_list_waitlist(self, conn, env):
        call_action(mod.health_add_waitlist, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            provider_id=None,
            preferred_date_start=None, preferred_date_end=None,
            preferred_time_start=None, preferred_time_end=None,
            appointment_type=None, priority=None,
            notes=None, status=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_waitlist, conn, ns(
            company_id=env["company_id"],
            patient_id=None, provider_id=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1
