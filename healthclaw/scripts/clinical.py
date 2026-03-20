"""HealthClaw — clinical domain module

Actions for the clinical domain (7 tables, 18 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update, update_row

    # Register naming prefixes
    ENTITY_PREFIXES.setdefault("healthclaw_encounter", "ENC-")
    ENTITY_PREFIXES.setdefault("healthclaw_prescription", "RX-")
    ENTITY_PREFIXES.setdefault("healthclaw_procedure", "PROC-")
    ENTITY_PREFIXES.setdefault("healthclaw_order", "ORD-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_ENC_TYPES = ("outpatient", "inpatient", "emergency", "observation", "telehealth", "home_visit")
VALID_ENC_STATUSES = ("open", "in_progress", "completed", "cancelled")
VALID_DX_TYPES = ("primary", "secondary", "admitting", "discharge", "rule_out")
VALID_DX_STATUSES = ("active", "resolved", "chronic", "rule_out")
VALID_RX_ROUTES = ("oral", "iv", "im", "subq", "topical", "inhaled", "rectal", "ophthalmic", "otic", "nasal", "sublingual", "transdermal", "other")
VALID_RX_STATUSES = ("active", "completed", "discontinued", "cancelled", "on_hold")
VALID_PROC_STATUSES = ("planned", "in_progress", "completed", "cancelled")
VALID_ANESTHESIA = ("none", "local", "regional", "general", "sedation")
VALID_LATERALITY = ("left", "right", "bilateral", "not_applicable")
VALID_NOTE_TYPES = ("progress", "soap", "hpi", "consultation", "discharge", "operative", "procedure", "nursing", "other")
VALID_NOTE_STATUSES = ("draft", "signed", "cosigned", "amended", "addended")
VALID_ORDER_TYPES = ("lab", "imaging", "referral", "procedure", "other")
VALID_ORDER_PRIORITIES = ("stat", "urgent", "routine", "elective")
VALID_ORDER_STATUSES = ("pending", "in_progress", "completed", "cancelled")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


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


def _validate_encounter(conn, encounter_id):
    if not encounter_id:
        err("--encounter-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_encounter")).select(Field("id")).where(Field("id") == P()).get_sql(), (encounter_id,)).fetchone():
        err(f"Encounter {encounter_id} not found")


# ---------------------------------------------------------------------------
# 1. add-encounter
# ---------------------------------------------------------------------------
def add_encounter(conn, args):
    if not args.company_id:
        err("--company-id is required")
    _validate_patient(conn, args.patient_id)
    _validate_provider(conn, args.provider_id)

    enc_date = getattr(args, "encounter_date", None)
    if not enc_date:
        err("--encounter-date is required")
    enc_type = getattr(args, "encounter_type", None) or "outpatient"
    _validate_enum(enc_type, VALID_ENC_TYPES, "health-encounter-type")

    # Optional appointment link
    appt_id = getattr(args, "appointment_id", None)
    if appt_id:
        if not conn.execute(Q.from_(Table("healthclaw_appointment")).select(Field("id")).where(Field("id") == P()).get_sql(), (appt_id,)).fetchone():
            err(f"Appointment {appt_id} not found")

    enc_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_encounter", company_id=args.company_id)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_encounter", {"id": P(), "naming_series": P(), "patient_id": P(), "appointment_id": P(), "provider_id": P(), "encounter_date": P(), "encounter_type": P(), "chief_complaint": P(), "department": P(), "room": P(), "admission_date": P(), "discharge_date": P(), "status": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        enc_id, naming, args.patient_id, appt_id, args.provider_id,
        enc_date, enc_type,
        getattr(args, "chief_complaint", None),
        getattr(args, "department", None),
        getattr(args, "room", None),
        getattr(args, "admission_date", None),
        None, "open",
        getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_encounter", enc_id, "health-add-encounter", args.company_id)
    conn.commit()
    ok({"id": enc_id, "naming_series": naming, "encounter_date": enc_date, "status": "open"})


# ---------------------------------------------------------------------------
# 2. update-encounter
# ---------------------------------------------------------------------------
def update_encounter(conn, args):
    enc_id = getattr(args, "encounter_id", None)
    _validate_encounter(conn, enc_id)

    data, changed = {}, []
    for arg_name, col_name in {
        "encounter_type": "encounter_type", "chief_complaint": "chief_complaint",
        "department": "department", "room": "room",
        "admission_date": "admission_date", "discharge_date": "discharge_date",
        "discharge_disposition": "discharge_disposition",
        "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            if col_name == "encounter_type":
                _validate_enum(val, VALID_ENC_TYPES, "health-encounter-type")
            data[col_name] = val
            changed.append(col_name)

    enc_status = getattr(args, "encounter_status", None)
    if enc_status is not None:
        _validate_enum(enc_status, VALID_ENC_STATUSES, "status")
        data["status"] = enc_status
        changed.append("status")

    if not data:
        err("No fields to update")
    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("healthclaw_encounter", data, {"id": enc_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_encounter", enc_id, "health-update-encounter", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": enc_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 3. get-encounter
# ---------------------------------------------------------------------------
def get_encounter(conn, args):
    enc_id = getattr(args, "encounter_id", None)
    _validate_encounter(conn, enc_id)
    row = conn.execute(Q.from_(Table("healthclaw_encounter")).select(Table("healthclaw_encounter").star).where(Field("id") == P()).get_sql(), (enc_id,)).fetchone()
    data = row_to_dict(row)
    # Enrich
    _pat_t = Table("healthclaw_patient")
    pat = conn.execute(Q.from_(_pat_t).select(_pat_t.full_name).where(_pat_t.id == P()).get_sql(), (data["patient_id"],)).fetchone()
    if pat:
        data["patient_name"] = pat[0]
    _emp_t = Table("employee")
    prov = conn.execute(Q.from_(_emp_t).select(_emp_t.full_name).where(_emp_t.id == P()).get_sql(), (data["provider_id"],)).fetchone()
    if prov:
        data["provider_name"] = prov[0]
    data["diagnosis_count"] = conn.execute(Q.from_(Table("healthclaw_diagnosis")).select(fn.Count("*")).where(Field("encounter_id") == P()).get_sql(), (enc_id,)).fetchone()[0]
    data["prescription_count"] = conn.execute(Q.from_(Table("healthclaw_prescription")).select(fn.Count("*")).where(Field("encounter_id") == P()).get_sql(), (enc_id,)).fetchone()[0]
    ok(data)


# ---------------------------------------------------------------------------
# 4. list-encounters
# ---------------------------------------------------------------------------
def list_encounters(conn, args):
    t = Table("healthclaw_encounter")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P()); q_rows = q_rows.where(t.company_id == P()); params.append(args.company_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    if getattr(args, "provider_id", None):
        q_count = q_count.where(t.provider_id == P()); q_rows = q_rows.where(t.provider_id == P()); params.append(args.provider_id)
    if getattr(args, "encounter_status", None):
        q_count = q_count.where(t.status == P()); q_rows = q_rows.where(t.status == P()); params.append(args.encounter_status)
    if getattr(args, "encounter_type", None):
        q_count = q_count.where(t.encounter_type == P()); q_rows = q_rows.where(t.encounter_type == P()); params.append(args.encounter_type)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.encounter_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 5. add-vitals
# ---------------------------------------------------------------------------
def add_vitals(conn, args):
    enc_id = getattr(args, "encounter_id", None)
    _validate_encounter(conn, enc_id)
    _validate_patient(conn, args.patient_id)

    vitals_id = str(uuid.uuid4())
    recorded_by = getattr(args, "recorded_by_id", None)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_vitals", {"id": P(), "encounter_id": P(), "patient_id": P(), "recorded_by_id": P(), "recorded_at": P(), "temperature": P(), "temperature_site": P(), "heart_rate": P(), "respiratory_rate": P(), "blood_pressure_systolic": P(), "blood_pressure_diastolic": P(), "oxygen_saturation": P(), "weight": P(), "height": P(), "bmi": P(), "pain_level": P(), "notes": P(), "created_at": P()})
    conn.execute(sql, (
        vitals_id, enc_id, args.patient_id, recorded_by, now,
        getattr(args, "temperature", None),
        getattr(args, "temperature_site", None),
        int(args.heart_rate) if getattr(args, "heart_rate", None) else None,
        int(args.respiratory_rate) if getattr(args, "respiratory_rate", None) else None,
        int(args.bp_systolic) if getattr(args, "bp_systolic", None) else None,
        int(args.bp_diastolic) if getattr(args, "bp_diastolic", None) else None,
        getattr(args, "oxygen_saturation", None),
        getattr(args, "weight", None),
        getattr(args, "height", None),
        getattr(args, "bmi", None),
        int(args.pain_level) if getattr(args, "pain_level", None) else None,
        getattr(args, "notes", None), now,
    ))
    audit(conn, "healthclaw_vitals", vitals_id, "health-add-vitals", None)
    conn.commit()
    ok({"id": vitals_id, "encounter_id": enc_id})


# ---------------------------------------------------------------------------
# 6. list-vitals
# ---------------------------------------------------------------------------
def list_vitals(conn, args):
    t = Table("healthclaw_vitals")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "encounter_id", None):
        q_count = q_count.where(t.encounter_id == P()); q_rows = q_rows.where(t.encounter_id == P()); params.append(args.encounter_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.recorded_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 7. add-diagnosis
# ---------------------------------------------------------------------------
def add_diagnosis(conn, args):
    enc_id = getattr(args, "encounter_id", None)
    _validate_encounter(conn, enc_id)
    _validate_patient(conn, args.patient_id)

    icd10 = getattr(args, "icd10_code", None)
    if not icd10:
        err("--icd10-code is required")
    desc = getattr(args, "dx_description", None)
    if not desc:
        err("--dx-description is required")

    dx_type = getattr(args, "diagnosis_type", None) or "primary"
    _validate_enum(dx_type, VALID_DX_TYPES, "health-diagnosis-type")

    dx_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_diagnosis", {"id": P(), "encounter_id": P(), "patient_id": P(), "icd10_code": P(), "description": P(), "diagnosis_type": P(), "status": P(), "onset_date": P(), "diagnosed_by_id": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        dx_id, enc_id, args.patient_id, icd10, desc,
        dx_type, "active",
        getattr(args, "onset_date", None),
        getattr(args, "diagnosed_by_id", None) or getattr(args, "provider_id", None),
        getattr(args, "notes", None), now, now,
    ))
    audit(conn, "healthclaw_diagnosis", dx_id, "health-add-diagnosis", None)
    conn.commit()
    ok({"id": dx_id, "icd10_code": icd10, "diagnosis_type": dx_type})


# ---------------------------------------------------------------------------
# 8. update-diagnosis
# ---------------------------------------------------------------------------
def update_diagnosis(conn, args):
    dx_id = getattr(args, "diagnosis_id", None)
    if not dx_id:
        err("--diagnosis-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_diagnosis")).select(Field("id")).where(Field("id") == P()).get_sql(), (dx_id,)).fetchone():
        err(f"Diagnosis {dx_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "icd10_code": "icd10_code", "dx_description": "description",
        "diagnosis_type": "diagnosis_type", "dx_status": "status",
        "onset_date": "onset_date", "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            if col_name == "diagnosis_type":
                _validate_enum(val, VALID_DX_TYPES, "health-diagnosis-type")
            elif col_name == "status":
                _validate_enum(val, VALID_DX_STATUSES, "status")
            data[col_name] = val; changed.append(col_name)

    if not data:
        err("No fields to update")
    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("healthclaw_diagnosis", data, {"id": dx_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_diagnosis", dx_id, "health-update-diagnosis", getattr(args, "company_id", None))
    conn.commit()
    ok({"id": dx_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 9. list-diagnoses
# ---------------------------------------------------------------------------
def list_diagnoses(conn, args):
    t = Table("healthclaw_diagnosis")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "encounter_id", None):
        q_count = q_count.where(t.encounter_id == P()); q_rows = q_rows.where(t.encounter_id == P()); params.append(args.encounter_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    if getattr(args, "dx_status", None):
        q_count = q_count.where(t.status == P()); q_rows = q_rows.where(t.status == P()); params.append(args.dx_status)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.diagnosis_type, order=Order.asc).orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 10. add-prescription
# ---------------------------------------------------------------------------
def add_prescription(conn, args):
    enc_id = getattr(args, "encounter_id", None)
    _validate_encounter(conn, enc_id)
    _validate_patient(conn, args.patient_id)

    prescriber_id = getattr(args, "prescriber_id", None) or getattr(args, "provider_id", None)
    if not prescriber_id:
        err("--prescriber-id or --provider-id is required")

    med_name = getattr(args, "medication_name", None)
    if not med_name:
        err("--medication-name is required")
    dosage = getattr(args, "dosage", None)
    if not dosage:
        err("--dosage is required")
    frequency = getattr(args, "frequency", None)
    if not frequency:
        err("--frequency is required")
    start_date = getattr(args, "rx_start_date", None)
    if not start_date:
        err("--rx-start-date is required")

    route = getattr(args, "route", None) or "oral"
    _validate_enum(route, VALID_RX_ROUTES, "route")

    rx_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_prescription", company_id=args.company_id)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_prescription", {"id": P(), "naming_series": P(), "encounter_id": P(), "patient_id": P(), "prescriber_id": P(), "medication_name": P(), "ndc_code": P(), "dosage": P(), "frequency": P(), "route": P(), "quantity": P(), "refills": P(), "daw": P(), "start_date": P(), "end_date": P(), "diagnosis_id": P(), "controlled_schedule": P(), "pharmacy_notes": P(), "status": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        rx_id, naming, enc_id, args.patient_id, prescriber_id,
        med_name, getattr(args, "ndc_code", None),
        dosage, frequency, route,
        getattr(args, "quantity", None) or "0",
        int(getattr(args, "refills", None) or 0),
        1 if getattr(args, "daw", None) == "1" else 0,
        start_date, getattr(args, "rx_end_date", None),
        getattr(args, "diagnosis_id", None),
        getattr(args, "controlled_schedule", None),
        getattr(args, "pharmacy_notes", None),
        "active", getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_prescription", rx_id, "health-add-prescription", args.company_id)
    conn.commit()
    ok({"id": rx_id, "naming_series": naming, "medication_name": med_name, "status": "active"})


# ---------------------------------------------------------------------------
# 11. update-prescription
# ---------------------------------------------------------------------------
def update_prescription(conn, args):
    rx_id = getattr(args, "prescription_id", None)
    if not rx_id:
        err("--prescription-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_prescription")).select(Field("id")).where(Field("id") == P()).get_sql(), (rx_id,)).fetchone():
        err(f"Prescription {rx_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "dosage": "dosage", "frequency": "frequency", "route": "route",
        "rx_end_date": "end_date", "pharmacy_notes": "pharmacy_notes",
        "rx_status": "status", "discontinued_reason": "discontinued_reason",
        "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            if col_name == "route":
                _validate_enum(val, VALID_RX_ROUTES, "route")
            elif col_name == "status":
                _validate_enum(val, VALID_RX_STATUSES, "status")
            data[col_name] = val; changed.append(col_name)
    refills = getattr(args, "refills", None)
    if refills is not None:
        data["refills"] = int(refills); changed.append("refills")

    if not data:
        err("No fields to update")
    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("healthclaw_prescription", data, {"id": rx_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_prescription", rx_id, "health-update-prescription", getattr(args, "company_id", None))
    conn.commit()
    ok({"id": rx_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 12. list-prescriptions
# ---------------------------------------------------------------------------
def list_prescriptions(conn, args):
    t = Table("healthclaw_prescription")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "encounter_id", None):
        q_count = q_count.where(t.encounter_id == P()); q_rows = q_rows.where(t.encounter_id == P()); params.append(args.encounter_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    if getattr(args, "rx_status", None):
        q_count = q_count.where(t.status == P()); q_rows = q_rows.where(t.status == P()); params.append(args.rx_status)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 13. add-procedure
# ---------------------------------------------------------------------------
def add_procedure(conn, args):
    enc_id = getattr(args, "encounter_id", None)
    _validate_encounter(conn, enc_id)
    _validate_patient(conn, args.patient_id)
    _validate_provider(conn, args.provider_id)

    cpt = getattr(args, "cpt_code", None)
    if not cpt:
        err("--cpt-code is required")
    proc_desc = getattr(args, "proc_description", None)
    if not proc_desc:
        err("--proc-description is required")
    proc_date = getattr(args, "procedure_date", None)
    if not proc_date:
        err("--procedure-date is required")

    proc_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_procedure", company_id=args.company_id)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_procedure", {"id": P(), "naming_series": P(), "encounter_id": P(), "patient_id": P(), "provider_id": P(), "cpt_code": P(), "description": P(), "procedure_date": P(), "start_time": P(), "end_time": P(), "modifiers": P(), "diagnosis_ids": P(), "anesthesia_type": P(), "body_site": P(), "laterality": P(), "status": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        proc_id, naming, enc_id, args.patient_id, args.provider_id,
        cpt, proc_desc, proc_date,
        getattr(args, "start_time", None), getattr(args, "end_time", None),
        getattr(args, "modifiers", None), getattr(args, "diagnosis_ids", None),
        getattr(args, "anesthesia_type", None),
        getattr(args, "body_site", None), getattr(args, "laterality", None),
        "completed", getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_procedure", proc_id, "health-add-procedure", args.company_id)
    conn.commit()
    ok({"id": proc_id, "naming_series": naming, "cpt_code": cpt, "status": "completed"})


# ---------------------------------------------------------------------------
# 14. list-procedures
# ---------------------------------------------------------------------------
def list_procedures(conn, args):
    t = Table("healthclaw_procedure")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "encounter_id", None):
        q_count = q_count.where(t.encounter_id == P()); q_rows = q_rows.where(t.encounter_id == P()); params.append(args.encounter_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    if getattr(args, "cpt_code", None):
        q_count = q_count.where(t.cpt_code == P()); q_rows = q_rows.where(t.cpt_code == P()); params.append(args.cpt_code)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.procedure_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 15. add-clinical-note
# ---------------------------------------------------------------------------
def add_clinical_note(conn, args):
    enc_id = getattr(args, "encounter_id", None)
    _validate_encounter(conn, enc_id)
    _validate_patient(conn, args.patient_id)

    author_id = getattr(args, "author_id", None) or getattr(args, "provider_id", None)
    if not author_id:
        err("--author-id or --provider-id is required")

    note_type = getattr(args, "note_type", None) or "progress"
    _validate_enum(note_type, VALID_NOTE_TYPES, "health-note-type")

    note_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_clinical_note", {"id": P(), "encounter_id": P(), "patient_id": P(), "author_id": P(), "note_type": P(), "subjective": P(), "objective": P(), "assessment": P(), "plan": P(), "body": P(), "addendum": P(), "signed_at": P(), "cosigner_id": P(), "cosigned_at": P(), "status": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        note_id, enc_id, args.patient_id, author_id, note_type,
        getattr(args, "subjective", None),
        getattr(args, "objective", None),
        getattr(args, "assessment", None),
        getattr(args, "plan_text", None),
        getattr(args, "body", None),
        None, None, None, None,
        "draft", now, now,
    ))
    audit(conn, "healthclaw_clinical_note", note_id, "health-add-clinical-note", None)
    conn.commit()
    ok({"id": note_id, "note_type": note_type, "status": "draft"})


# ---------------------------------------------------------------------------
# 16. update-clinical-note
# ---------------------------------------------------------------------------
def update_clinical_note(conn, args):
    note_id = getattr(args, "note_id", None)
    if not note_id:
        err("--note-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_clinical_note")).select(Field("id")).where(Field("id") == P()).get_sql(), (note_id,)).fetchone():
        err(f"Clinical note {note_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "note_type": "note_type", "subjective": "subjective",
        "objective": "objective", "assessment": "assessment",
        "plan_text": "plan", "body": "body", "addendum": "addendum",
        "note_status": "status", "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            if col_name == "note_type":
                _validate_enum(val, VALID_NOTE_TYPES, "health-note-type")
            elif col_name == "status":
                _validate_enum(val, VALID_NOTE_STATUSES, "status")
            data[col_name] = val; changed.append(col_name)

    # Sign the note
    if getattr(args, "sign", None) == "1":
        data["status"] = "signed"; changed.append("status")
        data["signed_at"] = _now_iso(); changed.append("signed_at")

    if not data:
        err("No fields to update")
    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("healthclaw_clinical_note", data, {"id": note_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_clinical_note", note_id, "health-update-clinical-note", getattr(args, "company_id", None))
    conn.commit()
    ok({"id": note_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 17. list-clinical-notes
# ---------------------------------------------------------------------------
def list_clinical_notes(conn, args):
    t = Table("healthclaw_clinical_note")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "encounter_id", None):
        q_count = q_count.where(t.encounter_id == P()); q_rows = q_rows.where(t.encounter_id == P()); params.append(args.encounter_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    if getattr(args, "note_type", None):
        q_count = q_count.where(t.note_type == P()); q_rows = q_rows.where(t.note_type == P()); params.append(args.note_type)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 18. add-order
# ---------------------------------------------------------------------------
def add_order(conn, args):
    enc_id = getattr(args, "encounter_id", None)
    _validate_encounter(conn, enc_id)
    _validate_patient(conn, args.patient_id)

    ordering_prov = getattr(args, "ordering_provider_id", None) or getattr(args, "provider_id", None)
    if not ordering_prov:
        err("--ordering-provider-id or --provider-id is required")

    order_type = getattr(args, "order_type", None)
    if not order_type:
        err("--order-type is required")
    _validate_enum(order_type, VALID_ORDER_TYPES, "health-order-type")

    order_date = getattr(args, "order_date", None)
    if not order_date:
        err("--order-date is required")

    priority = getattr(args, "priority", None) or "routine"
    _validate_enum(priority, VALID_ORDER_PRIORITIES, "priority")

    order_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_order", company_id=args.company_id)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_order", {"id": P(), "naming_series": P(), "encounter_id": P(), "patient_id": P(), "ordering_provider_id": P(), "order_type": P(), "order_date": P(), "priority": P(), "clinical_indication": P(), "diagnosis_id": P(), "status": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        order_id, naming, enc_id, args.patient_id, ordering_prov,
        order_type, order_date, priority,
        getattr(args, "clinical_indication", None),
        getattr(args, "diagnosis_id", None),
        "pending", getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_order", order_id, "health-add-order", args.company_id)
    conn.commit()
    ok({"id": order_id, "naming_series": naming, "order_type": order_type, "status": "pending"})


# ===========================================================================
# H14: Problem List (alias to medical_history)
# ===========================================================================

def add_problem(conn, args):
    """Alias for health-add-medical-history (problem list entry)."""
    # Import at call time to avoid circular imports
    from patients import add_medical_history
    add_medical_history(conn, args)


def list_active_problems(conn, args):
    """List active/chronic problems from medical_history table."""
    t = Table("healthclaw_medical_history")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    patient_id = getattr(args, "patient_id", None)
    if not patient_id:
        err("--patient-id is required")
    _validate_patient(conn, patient_id)

    q_count = q_count.where(t.patient_id == P())
    q_rows = q_rows.where(t.patient_id == P())
    params.append(patient_id)

    # Filter to active or chronic problems only
    q_count = q_count.where(t.status.isin([P(), P()]))
    q_rows = q_rows.where(t.status.isin([P(), P()]))
    params.extend(["active", "chronic"])

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ===========================================================================
# H15: Medication Reconciliation
# ===========================================================================

VALID_RECON_TYPES = ("admission", "discharge", "transfer", "annual_review")
VALID_RECON_STATUSES = ("pending", "completed", "reviewed")


def add_med_reconciliation(conn, args):
    """Create a medication reconciliation record."""
    if not args.company_id:
        err("--company-id is required")
    _validate_patient(conn, args.patient_id)

    recon_type = getattr(args, "reconciliation_type", None)
    if not recon_type:
        err("--reconciliation-type is required")
    _validate_enum(recon_type, VALID_RECON_TYPES, "reconciliation-type")

    enc_id = getattr(args, "encounter_id", None)
    if enc_id:
        _validate_encounter(conn, enc_id)

    rec_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_med_reconciliation", {
        "id": P(), "patient_id": P(), "encounter_id": P(),
        "reconciliation_type": P(), "medications_reviewed": P(),
        "medications_added": P(), "medications_removed": P(),
        "medications_changed": P(), "reconciled_by": P(),
        "reconciled_at": P(), "notes": P(), "status": P(),
        "company_id": P(), "created_at": P(),
    })
    conn.execute(sql, (
        rec_id, args.patient_id, enc_id, recon_type,
        getattr(args, "medications_reviewed", None),
        getattr(args, "medications_added", None),
        getattr(args, "medications_removed", None),
        getattr(args, "medications_changed", None),
        getattr(args, "reconciled_by", None),
        now if getattr(args, "reconciled_by", None) else None,
        getattr(args, "notes", None),
        "pending", args.company_id, now,
    ))
    audit(conn, "healthclaw_med_reconciliation", rec_id, "health-add-med-reconciliation", args.company_id)
    conn.commit()
    ok({"id": rec_id, "reconciliation_type": recon_type, "recon_status": "pending"})


def list_med_reconciliations(conn, args):
    """List medication reconciliation records."""
    t = Table("healthclaw_med_reconciliation")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P()); q_rows = q_rows.where(t.company_id == P()); params.append(args.company_id)
    if getattr(args, "status", None):
        q_count = q_count.where(t.status == P()); q_rows = q_rows.where(t.status == P()); params.append(args.status)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


def get_med_reconciliation(conn, args):
    """Get a single medication reconciliation record."""
    rec_id = getattr(args, "reconciliation_id", None)
    if not rec_id:
        err("--reconciliation-id is required")
    t = Table("healthclaw_med_reconciliation")
    row = conn.execute(Q.from_(t).select(t.star).where(t.id == P()).get_sql(), (rec_id,)).fetchone()
    if not row:
        err(f"Medication reconciliation {rec_id} not found")
    ok(row_to_dict(row))


# ===========================================================================
# H16: Immunization Registry
# ===========================================================================

def add_immunization(conn, args):
    """Record a vaccination."""
    if not args.company_id:
        err("--company-id is required")
    _validate_patient(conn, args.patient_id)

    vaccine_name = getattr(args, "vaccine_name", None)
    if not vaccine_name:
        err("--vaccine-name is required")
    admin_date = getattr(args, "administration_date", None)
    if not admin_date:
        err("--administration-date is required")

    imm_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_immunization", {
        "id": P(), "patient_id": P(), "vaccine_name": P(),
        "vaccine_code": P(), "lot_number": P(), "manufacturer": P(),
        "administration_date": P(), "administration_site": P(),
        "administered_by": P(), "dose_number": P(),
        "series_complete": P(), "vis_date": P(),
        "next_due_date": P(), "reaction_notes": P(),
        "company_id": P(), "created_at": P(),
    })
    conn.execute(sql, (
        imm_id, args.patient_id, vaccine_name,
        getattr(args, "vaccine_code", None),
        getattr(args, "lot_number", None),
        getattr(args, "manufacturer", None),
        admin_date,
        getattr(args, "administration_site", None),
        getattr(args, "administered_by", None),
        int(getattr(args, "dose_number", None) or 1),
        1 if getattr(args, "series_complete", None) == "1" else 0,
        getattr(args, "vis_date", None),
        getattr(args, "next_due_date", None),
        getattr(args, "reaction_notes", None),
        args.company_id, now,
    ))
    audit(conn, "healthclaw_immunization", imm_id, "health-add-immunization", args.company_id)
    conn.commit()
    ok({"id": imm_id, "vaccine_name": vaccine_name, "administration_date": admin_date})


def update_immunization(conn, args):
    """Update an immunization record."""
    imm_id = getattr(args, "immunization_id", None)
    if not imm_id:
        err("--immunization-id is required")
    t = Table("healthclaw_immunization")
    if not conn.execute(Q.from_(t).select(Field("id")).where(Field("id") == P()).get_sql(), (imm_id,)).fetchone():
        err(f"Immunization {imm_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "vaccine_name": "vaccine_name", "vaccine_code": "vaccine_code",
        "lot_number": "lot_number", "manufacturer": "manufacturer",
        "administration_date": "administration_date", "administration_site": "administration_site",
        "administered_by": "administered_by", "vis_date": "vis_date",
        "next_due_date": "next_due_date", "reaction_notes": "reaction_notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val; changed.append(col_name)

    dose = getattr(args, "dose_number", None)
    if dose is not None:
        data["dose_number"] = int(dose); changed.append("dose_number")
    series = getattr(args, "series_complete", None)
    if series is not None:
        data["series_complete"] = 1 if series == "1" else 0; changed.append("series_complete")

    if not data:
        err("No fields to update")
    sql, params = dynamic_update("healthclaw_immunization", data, {"id": imm_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_immunization", imm_id, "health-update-immunization", None)
    conn.commit()
    ok({"id": imm_id, "updated_fields": changed})


def list_immunizations(conn, args):
    """List immunization records for a patient."""
    t = Table("healthclaw_immunization")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P()); q_rows = q_rows.where(t.company_id == P()); params.append(args.company_id)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.administration_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total, "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


def get_immunization_record(conn, args):
    """Get a single immunization record."""
    imm_id = getattr(args, "immunization_id", None)
    if not imm_id:
        err("--immunization-id is required")
    t = Table("healthclaw_immunization")
    row = conn.execute(Q.from_(t).select(t.star).where(t.id == P()).get_sql(), (imm_id,)).fetchone()
    if not row:
        err(f"Immunization {imm_id} not found")
    ok(row_to_dict(row))


def immunizations_due_report(conn, args):
    """Report immunizations due for all patients or a specific patient."""
    if not args.company_id:
        err("--company-id is required")

    t = Table("healthclaw_immunization")
    q = Q.from_(t).select(t.star).where(t.company_id == P()).where(t.next_due_date.isnotnull())
    params = [args.company_id]

    if getattr(args, "patient_id", None):
        q = q.where(t.patient_id == P())
        params.append(args.patient_id)

    # Only show where next_due_date is in the future or past (overdue)
    q = q.orderby(t.next_due_date, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q.get_sql(), params + [args.limit, args.offset]).fetchall()

    results = []
    for r in rows:
        data = row_to_dict(r)
        results.append({
            "patient_id": data["patient_id"],
            "vaccine_name": data["vaccine_name"],
            "last_dose_date": data["administration_date"],
            "next_due_date": data["next_due_date"],
            "dose_number": data.get("dose_number"),
            "series_complete": data.get("series_complete", 0),
        })

    ok({"company_id": args.company_id, "immunizations_due": results, "count": len(results)})


# ===========================================================================
# H17: Care Team (Phase 11)
# ===========================================================================

VALID_CARE_TEAM_ROLES = ("pcp", "specialist", "care_coordinator", "nurse",
                         "therapist", "social_worker", "pharmacist", "other")


def add_care_team_member(conn, args):
    _validate_patient(conn, args.patient_id)
    _validate_provider(conn, args.provider_id)
    if not args.company_id:
        err("--company-id is required")
    role = getattr(args, "role", None)
    if not role:
        err("--role is required")
    _validate_enum(role, VALID_CARE_TEAM_ROLES, "role")

    ct_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_care_team", {
        "id": P(), "patient_id": P(), "provider_id": P(),
        "role": P(), "start_date": P(), "end_date": P(),
        "status": P(), "company_id": P(), "created_at": P(),
    })
    conn.execute(sql, (
        ct_id, args.patient_id, args.provider_id, role,
        getattr(args, "start_date", None) or now[:10],
        None, "active", args.company_id, now,
    ))
    audit(conn, "healthclaw_care_team", ct_id, "health-add-care-team-member", args.company_id)
    conn.commit()
    ok({"id": ct_id, "patient_id": args.patient_id,
        "provider_id": args.provider_id, "role": role, "care_team_status": "active"})


def list_care_team(conn, args):
    _validate_patient(conn, args.patient_id)
    t = Table("healthclaw_care_team")
    q_count = Q.from_(t).select(fn.Count("*")).where(t.patient_id == P())
    q_rows = Q.from_(t).select(t.star).where(t.patient_id == P())
    params = [args.patient_id]
    status = getattr(args, "status", None)
    if status:
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(status)
    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.role, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    enriched = []
    for r in rows:
        d = row_to_dict(r)
        prov = conn.execute(Q.from_(Table("employee")).select(Field("full_name")).where(Field("id") == P()).get_sql(), (d["provider_id"],)).fetchone()
        if prov:
            d["provider_name"] = prov[0]
        enriched.append(d)
    ok({"rows": enriched, "total_count": total, "limit": args.limit,
        "offset": args.offset, "has_more": (args.offset + args.limit) < total})


def remove_care_team_member(conn, args):
    ct_id = getattr(args, "care_team_id", None)
    if not ct_id:
        err("--care-team-id is required")
    t = Table("healthclaw_care_team")
    row = conn.execute(Q.from_(t).select(t.status).where(t.id == P()).get_sql(), (ct_id,)).fetchone()
    if not row:
        err(f"Care team member {ct_id} not found")
    if row[0] == "inactive":
        err("Care team member is already inactive")
    now = _now_iso()
    data = {"status": "inactive", "end_date": now[:10]}
    sql, params = dynamic_update("healthclaw_care_team", data, {"id": ct_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_care_team", ct_id, "health-remove-care-team-member", None)
    conn.commit()
    ok({"id": ct_id, "care_team_status": "inactive", "end_date": now[:10]})


# ===========================================================================
# H18: Patient Education (Phase 11)
# ===========================================================================

VALID_EDUCATION_TYPES = ("discharge_instructions", "disease_management", "medication_guide",
                         "preventive_care", "surgical_prep", "post_operative", "lifestyle", "other")


def add_patient_education(conn, args):
    """Record patient education as a clinical note with education_type metadata."""
    enc_id = getattr(args, "encounter_id", None)
    _validate_encounter(conn, enc_id)
    _validate_patient(conn, args.patient_id)
    author_id = getattr(args, "author_id", None) or getattr(args, "provider_id", None)
    if not author_id:
        err("--author-id or --provider-id is required")
    education_type = getattr(args, "education_type", None) or "other"
    _validate_enum(education_type, VALID_EDUCATION_TYPES, "education-type")
    body = getattr(args, "body", None)
    if not body:
        err("--body is required (education content)")

    note_id = str(uuid.uuid4())
    now = _now_iso()
    import json as _json
    education_meta = _json.dumps({"education_type": education_type, "is_education": True})
    sql, _ = insert_row("healthclaw_clinical_note", {
        "id": P(), "encounter_id": P(), "patient_id": P(),
        "author_id": P(), "note_type": P(), "subjective": P(),
        "objective": P(), "assessment": P(), "plan": P(),
        "body": P(), "addendum": P(), "signed_at": P(),
        "cosigner_id": P(), "cosigned_at": P(),
        "status": P(), "created_at": P(), "updated_at": P(),
    })
    conn.execute(sql, (
        note_id, enc_id, args.patient_id, author_id, "other",
        None, None, education_meta, None, body, None, None, None, None,
        "signed", now, now,
    ))
    audit(conn, "healthclaw_clinical_note", note_id, "health-add-patient-education", None)
    conn.commit()
    ok({"id": note_id, "education_type": education_type,
        "encounter_id": enc_id, "patient_id": args.patient_id, "note_status": "signed"})


def list_patient_education(conn, args):
    """List patient education records (clinical notes with education metadata)."""
    _validate_patient(conn, args.patient_id)
    t = Table("healthclaw_clinical_note")
    q_rows = Q.from_(t).select(t.star).where((t.patient_id == P()) & (t.note_type == P()))
    params = [args.patient_id, "other"]
    rows = conn.execute(
        q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P()).get_sql(),
        params + [args.limit, args.offset]
    ).fetchall()
    import json as _json
    education_notes = []
    for r in rows:
        d = row_to_dict(r)
        try:
            meta = _json.loads(d.get("assessment", "{}"))
            if meta.get("is_education"):
                d["education_type"] = meta.get("education_type", "other")
                education_notes.append(d)
        except (_json.JSONDecodeError, TypeError):
            pass
    ok({"rows": education_notes, "total_count": len(education_notes),
        "limit": args.limit, "offset": args.offset, "has_more": False})


# ===========================================================================
# H23: Recurring Appointments (Phase 11)
# ===========================================================================

def create_recurring_appointment(conn, args):
    """Create N appointments at specified interval."""
    if not args.company_id:
        err("--company-id is required")
    _validate_patient(conn, args.patient_id)
    _validate_provider(conn, args.provider_id)
    appt_date = getattr(args, "appointment_date", None)
    if not appt_date:
        err("--appointment-date is required (first appointment date)")
    start_time = getattr(args, "start_time", None)
    end_time = getattr(args, "end_time", None)
    if not start_time or not end_time:
        err("--start-time and --end-time are required")

    count = int(getattr(args, "recurrence_count", None) or 4)
    if count < 1 or count > 52:
        err("--recurrence-count must be 1-52")
    interval_days = int(getattr(args, "interval_days", None) or 7)
    if interval_days < 1:
        err("--interval-days must be >= 1")
    appt_type = getattr(args, "appointment_type", None) or "follow_up"
    series_id = str(uuid.uuid4())
    created_ids = []

    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    ENTITY_PREFIXES.setdefault("healthclaw_appointment", "APPT-")
    from datetime import timedelta
    import json as _json
    current_date = datetime.strptime(appt_date[:10], "%Y-%m-%d")
    now = _now_iso()

    for i in range(count):
        appt_date_str = current_date.strftime("%Y-%m-%d")
        appt_id = str(uuid.uuid4())
        naming = get_next_name(conn, "healthclaw_appointment", company_id=args.company_id)
        sql, _ = insert_row("healthclaw_appointment", {
            "id": P(), "naming_series": P(), "patient_id": P(),
            "provider_id": P(), "appointment_date": P(), "start_time": P(),
            "end_time": P(), "duration_minutes": P(), "appointment_type": P(),
            "chief_complaint": P(), "location": P(), "status": P(),
            "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P(),
        })
        conn.execute(sql, (
            appt_id, naming, args.patient_id, args.provider_id,
            appt_date_str, start_time, end_time,
            int(getattr(args, "duration_minutes", None) or 30), appt_type,
            getattr(args, "chief_complaint", None), getattr(args, "location", None),
            "scheduled",
            _json.dumps({"series_id": series_id, "occurrence": i + 1, "total": count}),
            args.company_id, now, now,
        ))
        created_ids.append(appt_id)
        current_date += timedelta(days=interval_days)

    audit(conn, "healthclaw_appointment", series_id, "health-create-recurring-appointment",
          args.company_id, {"count": count, "interval_days": interval_days})
    conn.commit()
    last_date = (datetime.strptime(appt_date[:10], "%Y-%m-%d") + timedelta(days=interval_days * (count - 1))).strftime("%Y-%m-%d")
    ok({"series_id": series_id, "appointment_count": len(created_ids),
        "appointment_ids": created_ids, "interval_days": interval_days,
        "first_date": appt_date[:10], "last_date": last_date})


def list_recurring_series(conn, args):
    """List appointments belonging to a recurring series."""
    _validate_patient(conn, args.patient_id)
    t = Table("healthclaw_appointment")
    rows = conn.execute(
        Q.from_(t).select(t.star).where(t.patient_id == P())
        .orderby(t.appointment_date, order=Order.asc)
        .limit(P()).offset(P()).get_sql(),
        (args.patient_id, args.limit, args.offset)
    ).fetchall()
    import json as _json
    series_map = {}
    for r in rows:
        d = row_to_dict(r)
        try:
            meta = _json.loads(d.get("notes", "{}"))
            sid = meta.get("series_id")
            if sid:
                if sid not in series_map:
                    series_map[sid] = {"series_id": sid, "total_in_series": meta.get("total", 0), "appointments": []}
                series_map[sid]["appointments"].append({
                    "id": d["id"], "appointment_date": d["appointment_date"],
                    "status": d["status"], "occurrence": meta.get("occurrence", 0),
                })
        except (_json.JSONDecodeError, TypeError):
            pass
    ok({"patient_id": args.patient_id, "series_count": len(series_map),
        "series": list(series_map.values())})


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-add-encounter": add_encounter,
    "health-update-encounter": update_encounter,
    "health-get-encounter": get_encounter,
    "health-list-encounters": list_encounters,
    "health-add-vitals": add_vitals,
    "health-list-vitals": list_vitals,
    "health-add-diagnosis": add_diagnosis,
    "health-update-diagnosis": update_diagnosis,
    "health-list-diagnoses": list_diagnoses,
    "health-add-prescription": add_prescription,
    "health-update-prescription": update_prescription,
    "health-list-prescriptions": list_prescriptions,
    "health-add-procedure": add_procedure,
    "health-list-procedures": list_procedures,
    "health-add-clinical-note": add_clinical_note,
    "health-update-clinical-note": update_clinical_note,
    "health-list-clinical-notes": list_clinical_notes,
    "health-add-order": add_order,
    # H14: Problem List (aliases)
    "health-add-problem": add_problem,
    "health-list-active-problems": list_active_problems,
    # H15: Medication Reconciliation
    "health-add-med-reconciliation": add_med_reconciliation,
    "health-list-med-reconciliations": list_med_reconciliations,
    "health-get-med-reconciliation": get_med_reconciliation,
    # H16: Immunization Registry
    "health-add-immunization": add_immunization,
    "health-update-immunization": update_immunization,
    "health-list-immunizations": list_immunizations,
    "health-get-immunization-record": get_immunization_record,
    "health-immunizations-due-report": immunizations_due_report,
    # H17: Care Team (Phase 11)
    "health-add-care-team-member": add_care_team_member,
    "health-list-care-team": list_care_team,
    "health-remove-care-team-member": remove_care_team_member,
    # H18: Patient Education (Phase 11)
    "health-add-patient-education": add_patient_education,
    "health-list-patient-education": list_patient_education,
    # H23: Recurring Appointments (Phase 11)
    "health-create-recurring-appointment": create_recurring_appointment,
    "health-list-recurring-series": list_recurring_series,
}
