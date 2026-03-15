"""HealthClaw — inventory domain module

Actions for the inventory/pharmacy domain (3 tables, 10 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row

    # Register HealthClaw naming prefixes (inventory domain)
    ENTITY_PREFIXES.setdefault("healthclaw_dispensing", "DISP-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_FORMULARY_STATUSES = ("active", "inactive", "expired")
VALID_FORMULARY_ITEM_STATUSES = ("active", "inactive", "recalled")
VALID_CONTROLLED_SCHEDULES = ("II", "III", "IV", "V")
VALID_FORMULARY_TIERS = ("1", "2", "3", "4", "specialty")
VALID_DISPENSING_STATUSES = ("dispensed", "returned", "recalled", "voided")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
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


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


# ---------------------------------------------------------------------------
# 1. add-formulary
# ---------------------------------------------------------------------------
def add_formulary(conn, args):
    _validate_company(conn, args.company_id)

    name = getattr(args, "formulary_name", None)
    if not name:
        err("--formulary-name is required")
    effective_date = getattr(args, "effective_date", None)
    if not effective_date:
        err("--effective-date is required")

    formulary_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_formulary", {"id": P(), "name": P(), "description": P(), "effective_date": P(), "expiration_date": P(), "status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        formulary_id, name,
        getattr(args, "description", None),
        effective_date,
        getattr(args, "expiration_date", None),
        "active", args.company_id, now, now,
    ))
    audit(conn, "healthclaw_formulary", formulary_id, "health-add-formulary", args.company_id)
    conn.commit()
    ok({"id": formulary_id, "name": name, "status": "active"})


# ---------------------------------------------------------------------------
# 2. update-formulary
# ---------------------------------------------------------------------------
def update_formulary(conn, args):
    formulary_id = getattr(args, "formulary_id", None)
    if not formulary_id:
        err("--formulary-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_formulary")).select(Field("id")).where(Field("id") == P()).get_sql(), (formulary_id,)).fetchone():
        err(f"Formulary {formulary_id} not found")

    updates, params, changed = [], [], []
    for arg_name, col_name in {
        "formulary_name": "name", "description": "description",
        "effective_date": "effective_date", "expiration_date": "expiration_date",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            updates.append(f"{col_name} = ?")
            params.append(val)
            changed.append(col_name)

    formulary_status = getattr(args, "formulary_status", None)
    if formulary_status is not None:
        _validate_enum(formulary_status, VALID_FORMULARY_STATUSES, "status")
        updates.append("status = ?")
        params.append(formulary_status)
        changed.append("status")

    if not updates:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(formulary_id)
    conn.execute(f"UPDATE healthclaw_formulary SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "healthclaw_formulary", formulary_id, "health-update-formulary", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": formulary_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 3. list-formularies
# ---------------------------------------------------------------------------
def list_formularies(conn, args):
    t = Table("healthclaw_formulary")

    q_count = Q.from_(t).select(fn.Count("*"))

    q_rows = Q.from_(t).select(t.star)

    params = []


    if getattr(args, "company_id", None):

        q_count = q_count.where(t.company_id == P())

        q_rows = q_rows.where(t.company_id == P())

        params.append(args.company_id)

    if getattr(args, "status", None):

        q_count = q_count.where(t.status == P())

        q_rows = q_rows.where(t.status == P())

        params.append(args.status)


    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 4. add-formulary-item
# ---------------------------------------------------------------------------
def add_formulary_item(conn, args):
    formulary_id = getattr(args, "formulary_id", None)
    if not formulary_id:
        err("--formulary-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_formulary")).select(Field("id")).where(Field("id") == P()).get_sql(), (formulary_id,)).fetchone():
        err(f"Formulary {formulary_id} not found")

    item_id = getattr(args, "item_id", None)
    if not item_id:
        err("--item-id is required")
    if not conn.execute(Q.from_(Table("item")).select(Field("id")).where(Field("id") == P()).get_sql(), (item_id,)).fetchone():
        err(f"Item {item_id} not found")

    # Validate optional enums
    controlled_schedule = getattr(args, "controlled_schedule", None)
    _validate_enum(controlled_schedule, VALID_CONTROLLED_SCHEDULES, "health-controlled-schedule")
    formulary_tier = getattr(args, "formulary_tier", None)
    _validate_enum(formulary_tier, VALID_FORMULARY_TIERS, "health-formulary-tier")

    fi_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_formulary_item", {"id": P(), "formulary_id": P(), "item_id": P(), "ndc_code": P(), "drug_class": P(), "generic_name": P(), "brand_name": P(), "strength": P(), "dosage_form": P(), "route": P(), "controlled_schedule": P(), "therapeutic_class": P(), "formulary_tier": P(), "requires_prior_auth": P(), "max_daily_dose": P(), "status": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        fi_id, formulary_id, item_id,
        getattr(args, "ndc_code", None),
        getattr(args, "drug_class", None),
        getattr(args, "generic_name", None),
        getattr(args, "brand_name", None),
        getattr(args, "strength", None),
        getattr(args, "dosage_form", None),
        getattr(args, "route", None),
        controlled_schedule,
        getattr(args, "therapeutic_class", None),
        formulary_tier,
        1 if getattr(args, "requires_prior_auth", None) == "1" else 0,
        getattr(args, "max_daily_dose", None),
        "active", now, now,
    ))
    audit(conn, "healthclaw_formulary_item", fi_id, "health-add-formulary-item", None)
    conn.commit()
    ok({"id": fi_id, "formulary_id": formulary_id, "item_id": item_id})


# ---------------------------------------------------------------------------
# 5. update-formulary-item
# ---------------------------------------------------------------------------
def update_formulary_item(conn, args):
    fi_id = getattr(args, "formulary_item_id", None)
    if not fi_id:
        err("--formulary-item-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_formulary_item")).select(Field("id")).where(Field("id") == P()).get_sql(), (fi_id,)).fetchone():
        err(f"Formulary item {fi_id} not found")

    updates, params, changed = [], [], []
    for arg_name, col_name in {
        "ndc_code": "ndc_code", "drug_class": "drug_class",
        "generic_name": "generic_name", "brand_name": "brand_name",
        "strength": "strength", "dosage_form": "dosage_form",
        "route": "route", "therapeutic_class": "therapeutic_class",
        "max_daily_dose": "max_daily_dose",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            updates.append(f"{col_name} = ?")
            params.append(val)
            changed.append(col_name)

    controlled_schedule = getattr(args, "controlled_schedule", None)
    if controlled_schedule is not None:
        _validate_enum(controlled_schedule, VALID_CONTROLLED_SCHEDULES, "health-controlled-schedule")
        updates.append("controlled_schedule = ?")
        params.append(controlled_schedule)
        changed.append("controlled_schedule")

    formulary_tier = getattr(args, "formulary_tier", None)
    if formulary_tier is not None:
        _validate_enum(formulary_tier, VALID_FORMULARY_TIERS, "health-formulary-tier")
        updates.append("formulary_tier = ?")
        params.append(formulary_tier)
        changed.append("formulary_tier")

    fi_status = getattr(args, "formulary_item_status", None)
    if fi_status is not None:
        _validate_enum(fi_status, VALID_FORMULARY_ITEM_STATUSES, "status")
        updates.append("status = ?")
        params.append(fi_status)
        changed.append("status")

    if getattr(args, "requires_prior_auth", None) is not None:
        updates.append("requires_prior_auth = ?")
        params.append(1 if args.requires_prior_auth == "1" else 0)
        changed.append("requires_prior_auth")

    if not updates:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(fi_id)
    conn.execute(f"UPDATE healthclaw_formulary_item SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "healthclaw_formulary_item", fi_id, "health-update-formulary-item", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": fi_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 6. list-formulary-items
# ---------------------------------------------------------------------------
def list_formulary_items(conn, args):
    t = Table("healthclaw_formulary_item")

    q_count = Q.from_(t).select(fn.Count("*"))

    q_rows = Q.from_(t).select(t.star)

    params = []


    if getattr(args, "formulary_id", None):

        q_count = q_count.where(t.formulary_id == P())

        q_rows = q_rows.where(t.formulary_id == P())

        params.append(args.formulary_id)

    if getattr(args, "status", None):

        q_count = q_count.where(t.status == P())

        q_rows = q_rows.where(t.status == P())

        params.append(args.status)


    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 7. add-dispensing
# ---------------------------------------------------------------------------
def add_dispensing(conn, args):
    _validate_company(conn, args.company_id)

    prescription_id = getattr(args, "prescription_id", None)
    if not prescription_id:
        err("--prescription-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_prescription")).select(Field("id")).where(Field("id") == P()).get_sql(), (prescription_id,)).fetchone():
        err(f"Prescription {prescription_id} not found")

    _validate_patient(conn, args.patient_id)

    dispensed_by = getattr(args, "dispensed_by_id", None)
    if not dispensed_by:
        err("--dispensed-by-id is required")
    if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (dispensed_by,)).fetchone():
        err(f"Employee {dispensed_by} not found")

    dispensed_date = getattr(args, "dispensed_date", None)
    if not dispensed_date:
        err("--dispensed-date is required")

    # Optional FK checks
    formulary_item_id = getattr(args, "formulary_item_id", None)
    if formulary_item_id:
        if not conn.execute(Q.from_(Table("healthclaw_formulary_item")).select(Field("id")).where(Field("id") == P()).get_sql(), (formulary_item_id,)).fetchone():
            err(f"Formulary item {formulary_item_id} not found")
    item_id = getattr(args, "item_id", None)
    if item_id:
        if not conn.execute(Q.from_(Table("item")).select(Field("id")).where(Field("id") == P()).get_sql(), (item_id,)).fetchone():
            err(f"Item {item_id} not found")

    disp_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_dispensing", company_id=args.company_id)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_dispensing", {"id": P(), "naming_series": P(), "prescription_id": P(), "patient_id": P(), "formulary_item_id": P(), "item_id": P(), "dispensed_by_id": P(), "dispensed_date": P(), "quantity": P(), "lot_number": P(), "expiration_date": P(), "ndc_code": P(), "directions": P(), "refill_number": P(), "status": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        disp_id, naming, prescription_id, args.patient_id,
        formulary_item_id, item_id, dispensed_by, dispensed_date,
        str(round_currency(to_decimal(getattr(args, "quantity", None) or "0"))),
        getattr(args, "lot_number", None),
        getattr(args, "expiration_date", None),
        getattr(args, "ndc_code", None),
        getattr(args, "directions", None),
        int(getattr(args, "refill_number", None) or 0),
        "dispensed",
        getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_dispensing", disp_id, "health-add-dispensing", args.company_id)
    conn.commit()
    ok({"id": disp_id, "naming_series": naming, "prescription_id": prescription_id, "status": "dispensed"})


# ---------------------------------------------------------------------------
# 8. get-dispensing
# ---------------------------------------------------------------------------
def get_dispensing(conn, args):
    disp_id = getattr(args, "dispensing_id", None)
    if not disp_id:
        err("--dispensing-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_dispensing")).select(Table("healthclaw_dispensing").star).where(Field("id") == P()).get_sql(), (disp_id,)).fetchone()
    if not row:
        err(f"Dispensing {disp_id} not found")
    data = row_to_dict(row)

    # Enrich: patient name
    pat = conn.execute("SELECT full_name FROM healthclaw_patient WHERE id = ?", (data["patient_id"],)).fetchone()
    if pat:
        data["patient_name"] = pat[0]
    # Enrich: dispensed by name
    emp = conn.execute("SELECT full_name FROM employee WHERE id = ?", (data["dispensed_by_id"],)).fetchone()
    if emp:
        data["dispensed_by_name"] = emp[0]
    ok(data)


# ---------------------------------------------------------------------------
# 9. list-dispensings
# ---------------------------------------------------------------------------
def list_dispensings(conn, args):
    t = Table("healthclaw_dispensing")

    q_count = Q.from_(t).select(fn.Count("*"))

    q_rows = Q.from_(t).select(t.star)

    params = []


    if getattr(args, "patient_id", None):

        q_count = q_count.where(t.patient_id == P())

        q_rows = q_rows.where(t.patient_id == P())

        params.append(args.patient_id)

    if getattr(args, "prescription_id", None):

        q_count = q_count.where(t.prescription_id == P())

        q_rows = q_rows.where(t.prescription_id == P())

        params.append(args.prescription_id)

    if getattr(args, "status", None):

        q_count = q_count.where(t.status == P())

        q_rows = q_rows.where(t.status == P())

        params.append(args.status)


    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.dispensed_date, order=Order.desc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 10. cancel-dispensing
# ---------------------------------------------------------------------------
def cancel_dispensing(conn, args):
    disp_id = getattr(args, "dispensing_id", None)
    if not disp_id:
        err("--dispensing-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_dispensing")).select(Field("status")).where(Field("id") == P()).get_sql(), (disp_id,)).fetchone()
    if not row:
        err(f"Dispensing {disp_id} not found")
    if row[0] != "dispensed":
        err(f"Cannot void dispensing with status '{row[0]}'. Must be 'dispensed'.")

    conn.execute(
        "UPDATE healthclaw_dispensing SET status = 'voided', updated_at = datetime('now') WHERE id = ?",
        (disp_id,)
    )
    audit(conn, "healthclaw_dispensing", disp_id, "health-cancel-dispensing", None)
    conn.commit()
    ok({"id": disp_id, "status": "voided"})


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-add-formulary": add_formulary,
    "health-update-formulary": update_formulary,
    "health-list-formularies": list_formularies,
    "health-add-formulary-item": add_formulary_item,
    "health-update-formulary-item": update_formulary_item,
    "health-list-formulary-items": list_formulary_items,
    "health-add-dispensing": add_dispensing,
    "health-get-dispensing": get_dispensing,
    "health-list-dispensings": list_dispensings,
    "health-cancel-dispensing": cancel_dispensing,
}
