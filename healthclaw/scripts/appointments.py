"""HealthClaw — appointments domain module

Actions for the appointments domain (5 tables, 14 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

try:
    import importlib.util
    if importlib.util.find_spec("erpclaw_lib") is None:
        sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Field, LiteralValue, Order, P, Q, Table, dynamic_update, fn, insert_row, now as sql_now, update_row

    # Register naming prefixes
    ENTITY_PREFIXES.setdefault("healthclaw_appointment", "APPT-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_APPT_TYPES = ("new_patient", "follow_up", "urgent", "walk_in", "telehealth", "procedure", "physical_exam", "consultation")
VALID_APPT_STATUSES = ("scheduled", "confirmed", "checked_in", "in_progress", "completed", "cancelled", "no_show", "rescheduled")
VALID_BLOCK_REASONS = ("vacation", "meeting", "personal", "maintenance", "holiday", "other")
VALID_WAITLIST_PRIORITIES = ("low", "normal", "high", "urgent")
VALID_WAITLIST_STATUSES = ("waiting", "offered", "accepted", "expired", "cancelled")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    if not conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (company_id,)).fetchone():
        err(f"Company {company_id} not found")


def _validate_patient(conn, patient_id):
    if not patient_id:
        err("--patient-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_patient")).select(Field("id")).where(Field("id") == P()).get_sql(), (patient_id,)).fetchone():
        err(f"Patient {patient_id} not found")


def _validate_provider(conn, provider_id):
    if not provider_id:
        err("--provider-id is required")
    if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (provider_id,)).fetchone():
        err(f"Provider (employee) {provider_id} not found")


# ---------------------------------------------------------------------------
# 1. add-provider-schedule
# ---------------------------------------------------------------------------
def add_provider_schedule(conn, args):
    _validate_company(conn, args.company_id)
    _validate_provider(conn, args.provider_id)
    day = getattr(args, "day_of_week", None)
    if day is None:
        err("--day-of-week is required (0=Mon, 6=Sun)")
    try:
        day = int(day)
    except (TypeError, ValueError):
        err("--day-of-week must be an integer 0-6")
    if day < 0 or day > 6:
        err("--day-of-week must be 0-6")
    start = getattr(args, "start_time", None)
    end = getattr(args, "end_time", None)
    if not start or not end:
        err("--start-time and --end-time are required (HH:MM)")

    sched_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_provider_schedule", {"id": P(), "provider_id": P(), "day_of_week": P(), "start_time": P(), "end_time": P(), "slot_duration": P(), "location": P(), "status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        sched_id, args.provider_id, day, start, end,
        int(getattr(args, "slot_duration", None) or 30),
        getattr(args, "location", None),
        "active", args.company_id, now, now,
    ))
    audit(conn, "healthclaw_provider_schedule", sched_id, "health-add-provider-schedule", args.company_id)
    conn.commit()
    ok({"id": sched_id, "provider_id": args.provider_id, "day_of_week": day})


# ---------------------------------------------------------------------------
# 2. update-provider-schedule
# ---------------------------------------------------------------------------
def update_provider_schedule(conn, args):
    sched_id = getattr(args, "schedule_id", None)
    if not sched_id:
        err("--schedule-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_provider_schedule")).select(Field("id")).where(Field("id") == P()).get_sql(), (sched_id,)).fetchone():
        err(f"Schedule {sched_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "start_time": "start_time", "end_time": "end_time",
        "location": "location", "status": "status",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            if col_name == "status":
                _validate_enum(val, ("active", "inactive"), "status")
            data[col_name] = val
            changed.append(col_name)
    slot = getattr(args, "slot_duration", None)
    if slot is not None:
        data["slot_duration"] = int(slot)
        changed.append("slot_duration")

    if not data:
        err("No fields to update")
    data["updated_at"] = sql_now()
    sql, params = dynamic_update("healthclaw_provider_schedule", data, {"id": sched_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_provider_schedule", sched_id, "health-update-provider-schedule", getattr(args, "company_id", None))
    conn.commit()
    ok({"id": sched_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 3. list-provider-schedules
# ---------------------------------------------------------------------------
def list_provider_schedules(conn, args):
    t = Table("healthclaw_provider_schedule")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "provider_id", None):
        q_count = q_count.where(t.provider_id == P())
        q_rows = q_rows.where(t.provider_id == P())
        params.append(args.provider_id)
    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(args.company_id)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.day_of_week, order=Order.asc).orderby(t.start_time, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 4. add-schedule-block
# ---------------------------------------------------------------------------
def add_schedule_block(conn, args):
    _validate_company(conn, args.company_id)
    _validate_provider(conn, args.provider_id)
    block_date = getattr(args, "block_date", None)
    if not block_date:
        err("--block-date is required")
    reason = getattr(args, "reason", None) or "other"
    _validate_enum(reason, VALID_BLOCK_REASONS, "reason")

    block_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_schedule_block", {"id": P(), "provider_id": P(), "block_date": P(), "start_time": P(), "end_time": P(), "reason": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        block_id, args.provider_id, block_date,
        getattr(args, "start_time", None),
        getattr(args, "end_time", None),
        reason, getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_schedule_block", block_id, "health-add-schedule-block", args.company_id)
    conn.commit()
    ok({"id": block_id, "block_date": block_date, "reason": reason})


# ---------------------------------------------------------------------------
# 5. list-schedule-blocks
# ---------------------------------------------------------------------------
def list_schedule_blocks(conn, args):
    t = Table("healthclaw_schedule_block")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "provider_id", None):
        q_count = q_count.where(t.provider_id == P())
        q_rows = q_rows.where(t.provider_id == P())
        params.append(args.provider_id)
    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(args.company_id)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.block_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 6. add-appointment
# ---------------------------------------------------------------------------
def add_appointment(conn, args):
    _validate_company(conn, args.company_id)
    _validate_patient(conn, args.patient_id)
    _validate_provider(conn, args.provider_id)

    appt_date = getattr(args, "appointment_date", None)
    start = getattr(args, "start_time", None)
    end = getattr(args, "end_time", None)
    if not appt_date:
        err("--appointment-date is required")
    if not start or not end:
        err("--start-time and --end-time are required")

    appt_type = getattr(args, "appointment_type", None) or "follow_up"
    _validate_enum(appt_type, VALID_APPT_TYPES, "health-appointment-type")

    appt_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_appointment", company_id=args.company_id)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_appointment", {"id": P(), "naming_series": P(), "patient_id": P(), "provider_id": P(), "appointment_date": P(), "start_time": P(), "end_time": P(), "duration_minutes": P(), "appointment_type": P(), "chief_complaint": P(), "location": P(), "status": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        appt_id, naming, args.patient_id, args.provider_id, appt_date,
        start, end,
        int(getattr(args, "duration_minutes", None) or 30),
        appt_type,
        getattr(args, "chief_complaint", None),
        getattr(args, "location", None),
        "scheduled", getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_appointment", appt_id, "health-add-appointment", args.company_id)
    conn.commit()
    ok({"id": appt_id, "naming_series": naming, "appointment_date": appt_date, "status": "scheduled"})


# ---------------------------------------------------------------------------
# 7. update-appointment
# ---------------------------------------------------------------------------
def update_appointment(conn, args):
    appt_id = getattr(args, "appointment_id", None)
    if not appt_id:
        err("--appointment-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_appointment")).select(Field("id")).where(Field("id") == P()).get_sql(), (appt_id,)).fetchone():
        err(f"Appointment {appt_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "appointment_date": "appointment_date", "start_time": "start_time",
        "end_time": "end_time", "appointment_type": "appointment_type",
        "chief_complaint": "chief_complaint", "location": "location",
        "notes": "notes", "cancellation_reason": "cancellation_reason",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            if col_name == "appointment_type":
                _validate_enum(val, VALID_APPT_TYPES, "health-appointment-type")
            data[col_name] = val
            changed.append(col_name)
    dur = getattr(args, "duration_minutes", None)
    if dur is not None:
        data["duration_minutes"] = int(dur)
        changed.append("duration_minutes")
    # Provider reassignment
    new_provider = getattr(args, "new_provider_id", None)
    if new_provider:
        _validate_provider(conn, new_provider)
        data["provider_id"] = new_provider
        changed.append("provider_id")

    if not data:
        err("No fields to update")
    data["updated_at"] = sql_now()
    sql, params = dynamic_update("healthclaw_appointment", data, {"id": appt_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_appointment", appt_id, "health-update-appointment", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": appt_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 8. get-appointment
# ---------------------------------------------------------------------------
def get_appointment(conn, args):
    appt_id = getattr(args, "appointment_id", None)
    if not appt_id:
        err("--appointment-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_appointment")).select(Table("healthclaw_appointment").star).where(Field("id") == P()).get_sql(), (appt_id,)).fetchone()
    if not row:
        err(f"Appointment {appt_id} not found")
    data = row_to_dict(row)

    # Enrich: patient name
    _pat_t = Table("healthclaw_patient")
    pat = conn.execute(Q.from_(_pat_t).select(_pat_t.full_name).where(_pat_t.id == P()).get_sql(), (data["patient_id"],)).fetchone()
    if pat:
        data["patient_name"] = pat[0]
    # Enrich: provider name
    _emp_t = Table("employee")
    prov = conn.execute(Q.from_(_emp_t).select(_emp_t.full_name).where(_emp_t.id == P()).get_sql(), (data["provider_id"],)).fetchone()
    if prov:
        data["provider_name"] = prov[0]
    ok(data)


# ---------------------------------------------------------------------------
# 9. list-appointments
# ---------------------------------------------------------------------------
def list_appointments(conn, args):
    t = Table("healthclaw_appointment")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P())
        q_rows = q_rows.where(t.patient_id == P())
        params.append(args.patient_id)
    if getattr(args, "provider_id", None):
        q_count = q_count.where(t.provider_id == P())
        q_rows = q_rows.where(t.provider_id == P())
        params.append(args.provider_id)
    if getattr(args, "appointment_date", None):
        q_count = q_count.where(t.appointment_date == P())
        q_rows = q_rows.where(t.appointment_date == P())
        params.append(args.appointment_date)
    if getattr(args, "status", None):
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(args.status)
    if getattr(args, "search", None):
        # Search joins patient name via subquery
        crit = LiteralValue("\"patient_id\" IN (SELECT \"id\" FROM \"healthclaw_patient\" WHERE LOWER(\"full_name\") LIKE LOWER(?))")
        q_count = q_count.where(crit)
        q_rows = q_rows.where(crit)
        params.append(f"%{args.search}%")

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.appointment_date, order=Order.desc).orderby(t.start_time, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 10. check-in-appointment
# ---------------------------------------------------------------------------
def check_in_appointment(conn, args):
    appt_id = getattr(args, "appointment_id", None)
    if not appt_id:
        err("--appointment-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_appointment")).select(Field("status")).where(Field("id") == P()).get_sql(), (appt_id,)).fetchone()
    if not row:
        err(f"Appointment {appt_id} not found")
    if row[0] not in ("scheduled", "confirmed"):
        err(f"Cannot check in appointment with status '{row[0]}'. Must be scheduled or confirmed.")

    now = _now_iso()
    sql = update_row("healthclaw_appointment",
        data={"status": "checked_in", "check_in_time": P(), "updated_at": sql_now()},
        where={"id": P()})
    conn.execute(sql, (now, appt_id))
    audit(conn, "healthclaw_appointment", appt_id, "health-check-in-appointment", None)
    conn.commit()
    ok({"id": appt_id, "status": "checked_in", "check_in_time": now})


# ---------------------------------------------------------------------------
# 11. check-out-appointment
# ---------------------------------------------------------------------------
def check_out_appointment(conn, args):
    appt_id = getattr(args, "appointment_id", None)
    if not appt_id:
        err("--appointment-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_appointment")).select(Field("status")).where(Field("id") == P()).get_sql(), (appt_id,)).fetchone()
    if not row:
        err(f"Appointment {appt_id} not found")
    if row[0] not in ("checked_in", "in_progress"):
        err(f"Cannot check out appointment with status '{row[0]}'. Must be checked_in or in_progress.")

    now = _now_iso()
    sql = update_row("healthclaw_appointment",
        data={"status": "completed", "check_out_time": P(), "updated_at": sql_now()},
        where={"id": P()})
    conn.execute(sql, (now, appt_id))
    audit(conn, "healthclaw_appointment", appt_id, "health-check-out-appointment", None)
    conn.commit()
    ok({"id": appt_id, "status": "completed", "check_out_time": now})


# ---------------------------------------------------------------------------
# 12. cancel-appointment
# ---------------------------------------------------------------------------
def cancel_appointment(conn, args):
    appt_id = getattr(args, "appointment_id", None)
    if not appt_id:
        err("--appointment-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_appointment")).select(Field("status")).where(Field("id") == P()).get_sql(), (appt_id,)).fetchone()
    if not row:
        err(f"Appointment {appt_id} not found")
    if row[0] in ("completed", "cancelled"):
        err(f"Cannot cancel appointment with status '{row[0]}'.")

    sql = update_row("healthclaw_appointment",
        data={"status": "cancelled", "cancellation_reason": P(), "updated_at": sql_now()},
        where={"id": P()})
    conn.execute(sql, (getattr(args, "cancellation_reason", None), appt_id))
    audit(conn, "healthclaw_appointment", appt_id, "health-cancel-appointment", None)
    conn.commit()
    ok({"id": appt_id, "status": "cancelled"})


# ---------------------------------------------------------------------------
# 13. add-waitlist
# ---------------------------------------------------------------------------
def add_waitlist(conn, args):
    _validate_company(conn, args.company_id)
    _validate_patient(conn, args.patient_id)

    priority = getattr(args, "priority", None) or "normal"
    _validate_enum(priority, VALID_WAITLIST_PRIORITIES, "priority")

    wl_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_waitlist", {"id": P(), "patient_id": P(), "provider_id": P(), "preferred_date_start": P(), "preferred_date_end": P(), "preferred_time_start": P(), "preferred_time_end": P(), "appointment_type": P(), "priority": P(), "status": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        wl_id, args.patient_id,
        getattr(args, "provider_id", None),
        getattr(args, "preferred_date_start", None),
        getattr(args, "preferred_date_end", None),
        getattr(args, "preferred_time_start", None),
        getattr(args, "preferred_time_end", None),
        getattr(args, "appointment_type", None) or "follow_up",
        priority, "waiting",
        getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_waitlist", wl_id, "health-add-waitlist", args.company_id)
    conn.commit()
    ok({"id": wl_id, "priority": priority, "status": "waiting"})


# ---------------------------------------------------------------------------
# 14. list-waitlist
# ---------------------------------------------------------------------------
def list_waitlist(conn, args):
    t = Table("healthclaw_waitlist")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P())
        q_rows = q_rows.where(t.patient_id == P())
        params.append(args.patient_id)
    if getattr(args, "provider_id", None):
        q_count = q_count.where(t.provider_id == P())
        q_rows = q_rows.where(t.provider_id == P())
        params.append(args.provider_id)
    if getattr(args, "status", None):
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(args.status)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.priority, order=Order.desc).orderby(t.created_at, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ===========================================================================
# H21: Multi-Resource Scheduling
# ===========================================================================

def check_room_availability(conn, args):
    """Check if a location/room is available for a time slot."""
    location = getattr(args, "location", None)
    if not location:
        err("--location is required")
    appt_date = getattr(args, "appointment_date", None)
    if not appt_date:
        err("--appointment-date is required")
    start = getattr(args, "start_time", None)
    end = getattr(args, "end_time", None)
    if not start or not end:
        err("--start-time and --end-time are required")

    t = Table("healthclaw_appointment")
    # Find conflicting appointments at the same location, date, and overlapping time
    # Overlap: existing.start < requested.end AND existing.end > requested.start
    conflicts = conn.execute(
        Q.from_(t)
        .select(t.id, t.patient_id, t.provider_id, t.start_time, t.end_time, t.status)
        .where(t.location == P())
        .where(t.appointment_date == P())
        .where(t.start_time < P())
        .where(t.end_time > P())
        .where(t.status.notin([P(), P()]))
        .get_sql(),
        (location, appt_date, end, start, "cancelled", "no_show")
    ).fetchall()

    conflict_list = [row_to_dict(r) for r in conflicts]
    available = len(conflict_list) == 0

    ok({
        "location": location,
        "date": appt_date,
        "start_time": start,
        "end_time": end,
        "available": available,
        "conflicts": conflict_list,
        "conflict_count": len(conflict_list),
    })


def schedule_multi_resource(conn, args):
    """Book appointment with provider + room + equipment check."""
    _validate_company(conn, args.company_id)
    _validate_patient(conn, args.patient_id)
    _validate_provider(conn, args.provider_id)

    appt_date = getattr(args, "appointment_date", None)
    start = getattr(args, "start_time", None)
    end = getattr(args, "end_time", None)
    location = getattr(args, "location", None)
    if not appt_date:
        err("--appointment-date is required")
    if not start or not end:
        err("--start-time and --end-time are required")

    warnings = []

    # Check provider availability (schedule blocks)
    block_t = Table("healthclaw_schedule_block")
    block_conflicts = conn.execute(
        Q.from_(block_t).select(fn.Count("*"))
        .where(block_t.provider_id == P())
        .where(block_t.block_date == P())
        .get_sql(),
        (args.provider_id, appt_date)
    ).fetchone()[0]
    if block_conflicts > 0:
        warnings.append(f"Provider has {block_conflicts} schedule block(s) on {appt_date}")

    # Check provider double-booking
    appt_t = Table("healthclaw_appointment")
    provider_conflicts = conn.execute(
        Q.from_(appt_t).select(fn.Count("*"))
        .where(appt_t.provider_id == P())
        .where(appt_t.appointment_date == P())
        .where(appt_t.start_time < P())
        .where(appt_t.end_time > P())
        .where(appt_t.status.notin([P(), P()]))
        .get_sql(),
        (args.provider_id, appt_date, end, start, "cancelled", "no_show")
    ).fetchone()[0]
    if provider_conflicts > 0:
        warnings.append(f"Provider has {provider_conflicts} overlapping appointment(s)")

    # Check room availability if location specified
    room_conflicts = 0
    if location:
        room_conflicts = conn.execute(
            Q.from_(appt_t).select(fn.Count("*"))
            .where(appt_t.location == P())
            .where(appt_t.appointment_date == P())
            .where(appt_t.start_time < P())
            .where(appt_t.end_time > P())
            .where(appt_t.status.notin([P(), P()]))
            .get_sql(),
            (location, appt_date, end, start, "cancelled", "no_show")
        ).fetchone()[0]
        if room_conflicts > 0:
            warnings.append(f"Room '{location}' has {room_conflicts} overlapping appointment(s)")

    # If there are hard conflicts (room or provider), error out
    if provider_conflicts > 0 or room_conflicts > 0:
        err(f"Scheduling conflict: {'; '.join(warnings)}")

    # Create the appointment
    appt_type = getattr(args, "appointment_type", None) or "follow_up"
    _validate_enum(appt_type, VALID_APPT_TYPES, "health-appointment-type")

    appt_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_appointment", company_id=args.company_id)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_appointment", {
        "id": P(), "naming_series": P(), "patient_id": P(), "provider_id": P(),
        "appointment_date": P(), "start_time": P(), "end_time": P(),
        "duration_minutes": P(), "appointment_type": P(),
        "chief_complaint": P(), "location": P(), "status": P(),
        "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P(),
    })
    conn.execute(sql, (
        appt_id, naming, args.patient_id, args.provider_id, appt_date,
        start, end,
        int(getattr(args, "duration_minutes", None) or 30),
        appt_type,
        getattr(args, "chief_complaint", None),
        location,
        "scheduled", getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_appointment", appt_id, "health-schedule-multi-resource", args.company_id)
    conn.commit()
    ok({
        "id": appt_id, "naming_series": naming,
        "appointment_date": appt_date, "appt_status": "scheduled",
        "location": location,
        "warnings": warnings,
    })


# ===========================================================================
# H22: Appointment Reminders
# ===========================================================================

VALID_REMINDER_TYPES = ("sms", "email", "phone", "in_app")
VALID_REMINDER_STATUSES = ("pending", "sent", "failed", "cancelled")


def add_reminder(conn, args):
    """Create an appointment reminder record."""
    appt_id = getattr(args, "appointment_id", None)
    if not appt_id:
        err("--appointment-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_appointment")).select(Field("id")).where(Field("id") == P()).get_sql(), (appt_id,)).fetchone():
        err(f"Appointment {appt_id} not found")

    reminder_type = getattr(args, "reminder_type", None)
    if not reminder_type:
        err("--reminder-type is required")
    _validate_enum(reminder_type, VALID_REMINDER_TYPES, "reminder-type")

    scheduled_at = getattr(args, "scheduled_at", None)
    if not scheduled_at:
        err("--scheduled-at is required")

    reminder_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_appointment_reminder", {
        "id": P(), "appointment_id": P(), "reminder_type": P(),
        "scheduled_at": P(), "sent_at": P(), "status": P(), "created_at": P(),
    })
    conn.execute(sql, (
        reminder_id, appt_id, reminder_type, scheduled_at,
        None, "pending", now,
    ))
    audit(conn, "healthclaw_appointment_reminder", reminder_id, "health-add-reminder", None)
    conn.commit()
    ok({"id": reminder_id, "appointment_id": appt_id, "reminder_type": reminder_type, "reminder_status": "pending"})


def list_reminders(conn, args):
    """List appointment reminders by status/date."""
    t = Table("healthclaw_appointment_reminder")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "appointment_id", None):
        q_count = q_count.where(t.appointment_id == P()); q_rows = q_rows.where(t.appointment_id == P()); params.append(args.appointment_id)
    if getattr(args, "status", None):
        q_count = q_count.where(t.status == P()); q_rows = q_rows.where(t.status == P()); params.append(args.status)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.scheduled_at, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


def process_reminders(conn, args):
    """Mark pending reminders as sent (batch process)."""
    t = Table("healthclaw_appointment_reminder")
    now = _now_iso()

    # Find all pending reminders whose scheduled_at has passed
    pending = conn.execute(
        Q.from_(t).select(t.id, t.appointment_id, t.reminder_type, t.scheduled_at)
        .where(t.status == P())
        .where(t.scheduled_at <= P())
        .orderby(t.scheduled_at, order=Order.asc)
        .get_sql(),
        ("pending", now)
    ).fetchall()

    processed = []
    for r in pending:
        rid = r[0]
        data = {"status": "sent", "sent_at": now}
        sql, params = dynamic_update("healthclaw_appointment_reminder", data, {"id": rid})
        conn.execute(sql, params)
        processed.append({
            "id": rid,
            "appointment_id": r[1],
            "reminder_type": r[2],
            "scheduled_at": r[3],
        })

    conn.commit()
    ok({"processed_count": len(processed), "processed": processed})


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-add-provider-schedule": add_provider_schedule,
    "health-update-provider-schedule": update_provider_schedule,
    "health-list-provider-schedules": list_provider_schedules,
    "health-add-schedule-block": add_schedule_block,
    "health-list-schedule-blocks": list_schedule_blocks,
    "health-add-appointment": add_appointment,
    "health-update-appointment": update_appointment,
    "health-get-appointment": get_appointment,
    "health-list-appointments": list_appointments,
    "health-check-in-appointment": check_in_appointment,
    "health-check-out-appointment": check_out_appointment,
    "health-cancel-appointment": cancel_appointment,
    "health-add-waitlist": add_waitlist,
    "health-list-waitlist": list_waitlist,
    # H21: Multi-Resource Scheduling
    "health-check-room-availability": check_room_availability,
    "health-schedule-multi-resource": schedule_multi_resource,
    # H22: Appointment Reminders
    "health-add-reminder": add_reminder,
    "health-list-reminders": list_reminders,
    "health-process-reminders": process_reminders,
}
