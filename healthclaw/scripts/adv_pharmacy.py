"""HealthClaw Advanced — pharmacy domain module.

Actions for medications, prescriptions, dispensing, and controlled substances.
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from decimal import Decimal

try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, Case
except ImportError:
    pass

ENTITY_PREFIXES.setdefault("healthclaw_prescription", "RX-")
ENTITY_PREFIXES.setdefault("healthclaw_dispense_log", "DISP-")

# ---- Constants ---------------------------------------------------------------

VALID_DEA_SCHEDULES = ("I", "II", "III", "IV", "V", "non-scheduled")
VALID_RX_STATUSES = ("active", "filled", "partially_filled", "expired", "cancelled")
VALID_CS_LOG_TYPES = ("received", "dispensed", "destroyed", "returned", "adjusted")


# ---- Helpers -----------------------------------------------------------------

def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_enum(val, choices, label):
    if val not in choices:
        err(f"Invalid {label}: {val}. Must be one of: {', '.join(choices)}")


def _validate_dea_number(dea):
    """Basic DEA number format check: 2 letters + 7 digits."""
    if not dea:
        return
    if len(dea) != 9:
        err(f"Invalid DEA number format: {dea}. Expected 2 letters + 7 digits (9 chars)")
    if not dea[:2].isalpha() or not dea[2:].isdigit():
        err(f"Invalid DEA number format: {dea}. Expected 2 letters + 7 digits")


# ---------------------------------------------------------------------------
# 1. add-medication
# ---------------------------------------------------------------------------
def add_medication(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    if not getattr(args, "name", None):
        err("--name is required")

    dea_schedule = getattr(args, "dea_schedule", None) or "non-scheduled"
    _validate_enum(dea_schedule, VALID_DEA_SCHEDULES, "health-dea-schedule")

    unit_price = str(round_currency(to_decimal(getattr(args, "unit_price", None) or "0.00")))
    quantity_on_hand = int(getattr(args, "quantity_on_hand", None) or 0)
    reorder_level = int(getattr(args, "reorder_level", None) or 0)

    med_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute(
        """INSERT INTO healthclaw_medication
           (id, company_id, name, generic_name, ndc_code, dea_schedule, dosage_form,
            strength, manufacturer, unit_price, quantity_on_hand, reorder_level,
            is_active, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
        (med_id, args.company_id, args.name,
         getattr(args, "generic_name", None),
         getattr(args, "ndc_code", None),
         dea_schedule,
         getattr(args, "dosage_form", None),
         getattr(args, "strength", None),
         getattr(args, "manufacturer", None),
         unit_price, quantity_on_hand, reorder_level,
         getattr(args, "notes", None), now, now)
    )
    audit(conn, "healthclaw_medication", med_id, "health-add-medication", args.company_id)
    conn.commit()
    ok({"id": med_id, "name": args.name, "dea_schedule": dea_schedule, "unit_price": unit_price})


# ---------------------------------------------------------------------------
# 2. list-medications
# ---------------------------------------------------------------------------
def list_medications(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?"); params.append(args.company_id)
    if getattr(args, "dea_schedule", None):
        where.append("dea_schedule = ?"); params.append(args.dea_schedule)
    if getattr(args, "search", None):
        where.append("(name LIKE ? OR generic_name LIKE ? OR ndc_code LIKE ?)")
        s = f"%{args.search}%"
        params.extend([s, s, s])
    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM healthclaw_medication WHERE {where_sql}", params).fetchone()[0]
    limit = getattr(args, "limit", None) or 50
    offset = getattr(args, "offset", None) or 0
    params.extend([limit, offset])
    rows = conn.execute(
        f"SELECT * FROM healthclaw_medication WHERE {where_sql} ORDER BY name ASC LIMIT ? OFFSET ?", params
    ).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset, "has_more": (offset + limit) < total})


# ---------------------------------------------------------------------------
# 3. get-medication
# ---------------------------------------------------------------------------
def get_medication(conn, args):
    med_id = getattr(args, "medication_id", None)
    if not med_id:
        err("--medication-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_medication")).select(Table("healthclaw_medication").star).where(Field("id") == P()).get_sql(), (med_id,)).fetchone()
    if not row:
        err(f"Medication {med_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# 4. update-medication
# ---------------------------------------------------------------------------
def update_medication(conn, args):
    med_id = getattr(args, "medication_id", None)
    if not med_id:
        err("--medication-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_medication")).select(Field("id")).where(Field("id") == P()).get_sql(), (med_id,)).fetchone():
        err(f"Medication {med_id} not found")

    updates, params, changed = [], [], []
    for arg_name, col_name in {
        "name": "name", "generic_name": "generic_name", "ndc_code": "ndc_code",
        "dosage_form": "dosage_form", "strength": "strength",
        "manufacturer": "manufacturer", "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            updates.append(f"{col_name} = ?"); params.append(val); changed.append(col_name)

    dea_schedule = getattr(args, "dea_schedule", None)
    if dea_schedule:
        _validate_enum(dea_schedule, VALID_DEA_SCHEDULES, "health-dea-schedule")
        updates.append("dea_schedule = ?"); params.append(dea_schedule); changed.append("dea_schedule")

    unit_price = getattr(args, "unit_price", None)
    if unit_price is not None:
        updates.append("unit_price = ?")
        params.append(str(round_currency(to_decimal(unit_price))))
        changed.append("unit_price")

    quantity_on_hand = getattr(args, "quantity_on_hand", None)
    if quantity_on_hand is not None:
        updates.append("quantity_on_hand = ?"); params.append(int(quantity_on_hand)); changed.append("quantity_on_hand")

    reorder_level = getattr(args, "reorder_level", None)
    if reorder_level is not None:
        updates.append("reorder_level = ?"); params.append(int(reorder_level)); changed.append("reorder_level")

    if not updates:
        err("No fields to update")
    updates.append("updated_at = datetime('now')")
    params.append(med_id)
    conn.execute(f"UPDATE healthclaw_medication SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "healthclaw_medication", med_id, "health-update-medication", getattr(args, "company_id", None))
    conn.commit()
    ok({"id": med_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 5. add-prescription
# ---------------------------------------------------------------------------
def add_prescription(conn, args):
    for req in ("company_id", "patient_id", "prescriber_id", "medication_id", "dosage", "frequency", "prescribed_date"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    # Validate medication exists
    med_row = conn.execute(Q.from_(Table("healthclaw_medication")).select(Field("id"), Field("dea_schedule")).where(Field("id") == P()).get_sql(), (args.medication_id,)).fetchone()
    if not med_row:
        err(f"Medication {args.medication_id} not found")

    # If controlled substance, require DEA number
    dea_schedule = med_row[1] if med_row else "non-scheduled"
    dea_number = getattr(args, "dea_number", None)
    if dea_schedule != "non-scheduled" and not dea_number:
        err(f"DEA number required for schedule {dea_schedule} medication")
    if dea_number:
        _validate_dea_number(dea_number)

    route = getattr(args, "route", None) or "oral"
    quantity_prescribed = int(getattr(args, "quantity_prescribed", None) or 0)
    refills_authorized = int(getattr(args, "refills_authorized", None) or 0)

    # Schedule II cannot have refills
    if dea_schedule == "II" and refills_authorized > 0:
        err("Schedule II medications cannot have refills")

    rx_id = str(uuid.uuid4())
    rx_number = getattr(args, "rx_number", None)
    now = _now_iso()
    conn.execute(
        """INSERT INTO healthclaw_prescription
           (id, company_id, patient_id, prescriber_id, medication_id, rx_number,
            dosage, frequency, route, quantity_prescribed, refills_authorized,
            refills_used, dea_number, rx_status, prescribed_date, expiry_date,
            notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'active', ?, ?, ?, ?, ?)""",
        (rx_id, args.company_id, args.patient_id, args.prescriber_id,
         args.medication_id, rx_number, args.dosage, args.frequency, route,
         quantity_prescribed, refills_authorized, dea_number,
         args.prescribed_date, getattr(args, "expiry_date", None),
         getattr(args, "notes", None), now, now)
    )
    audit(conn, "healthclaw_prescription", rx_id, "health-add-prescription", args.company_id)
    conn.commit()
    ok({"id": rx_id, "rx_number": rx_number, "medication_id": args.medication_id,
        "rx_status": "active"})


# ---------------------------------------------------------------------------
# 6. list-prescriptions
# ---------------------------------------------------------------------------
def list_prescriptions(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?"); params.append(args.company_id)
    if getattr(args, "patient_id", None):
        where.append("patient_id = ?"); params.append(args.patient_id)
    if getattr(args, "medication_id", None):
        where.append("medication_id = ?"); params.append(args.medication_id)
    rx_status = getattr(args, "rx_status", None)
    if rx_status:
        where.append("rx_status = ?"); params.append(rx_status)
    if getattr(args, "search", None):
        where.append("(dosage LIKE ? OR notes LIKE ? OR rx_number LIKE ?)")
        s = f"%{args.search}%"
        params.extend([s, s, s])
    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM healthclaw_prescription WHERE {where_sql}", params).fetchone()[0]
    limit = getattr(args, "limit", None) or 50
    offset = getattr(args, "offset", None) or 0
    params.extend([limit, offset])
    rows = conn.execute(
        f"SELECT * FROM healthclaw_prescription WHERE {where_sql} ORDER BY prescribed_date DESC LIMIT ? OFFSET ?", params
    ).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset, "has_more": (offset + limit) < total})


# ---------------------------------------------------------------------------
# 7. get-prescription
# ---------------------------------------------------------------------------
def get_prescription(conn, args):
    rx_id = getattr(args, "prescription_id", None)
    if not rx_id:
        err("--prescription-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_prescription")).select(Table("healthclaw_prescription").star).where(Field("id") == P()).get_sql(), (rx_id,)).fetchone()
    if not row:
        err(f"Prescription {rx_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# 8. fill-prescription
# ---------------------------------------------------------------------------
def fill_prescription(conn, args):
    rx_id = getattr(args, "prescription_id", None)
    if not rx_id:
        err("--prescription-id is required")
    if not getattr(args, "dispensed_by", None):
        err("--dispensed-by is required")

    row = conn.execute(Q.from_(Table("healthclaw_prescription")).select(Table("healthclaw_prescription").star).where(Field("id") == P()).get_sql(), (rx_id,)).fetchone()
    if not row:
        err(f"Prescription {rx_id} not found")
    rx = row_to_dict(row)

    if rx["rx_status"] in ("filled", "expired", "cancelled"):
        err(f"Cannot fill prescription with status: {rx['rx_status']}")

    quantity = int(getattr(args, "quantity_dispensed", None) or rx["quantity_prescribed"])

    # Create dispense log
    disp_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute(
        """INSERT INTO healthclaw_dispense_log
           (id, company_id, prescription_id, medication_id, dispensed_by,
            quantity_dispensed, dispense_date, is_refill, lot_number,
            expiration_date, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
        (disp_id, rx["company_id"], rx_id, rx["medication_id"],
         args.dispensed_by, quantity, now,
         getattr(args, "lot_number", None),
         getattr(args, "expiration_date", None),
         getattr(args, "notes", None), now)
    )

    # Update medication inventory
    conn.execute(
        "UPDATE healthclaw_medication SET quantity_on_hand = quantity_on_hand - ? WHERE id = ?",
        (quantity, rx["medication_id"])
    )

    # Update prescription status
    conn.execute(
        "UPDATE healthclaw_prescription SET rx_status = 'filled', updated_at = datetime('now') WHERE id = ?",
        (rx_id,)
    )

    # If controlled substance, log it
    med_row = conn.execute("SELECT dea_schedule FROM healthclaw_medication WHERE id = ?",
                           (rx["medication_id"],)).fetchone()
    if med_row and med_row[0] != "non-scheduled":
        cs_log_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO healthclaw_controlled_substance_log
               (id, company_id, medication_id, prescription_id, action_type,
                quantity, dea_number, performed_by, witness, log_date, notes, created_at)
               VALUES (?, ?, ?, ?, 'dispensed', ?, ?, ?, ?, ?, ?, ?)""",
            (cs_log_id, rx["company_id"], rx["medication_id"], rx_id,
             quantity, rx.get("dea_number"), args.dispensed_by,
             getattr(args, "witness", None), now,
             getattr(args, "notes", None), now)
        )

    audit(conn, "healthclaw_prescription", rx_id, "health-fill-prescription", rx["company_id"])
    conn.commit()
    ok({"id": rx_id, "dispense_log_id": disp_id, "quantity_dispensed": quantity,
        "rx_status": "filled"})


# ---------------------------------------------------------------------------
# 9. refill-prescription
# ---------------------------------------------------------------------------
def refill_prescription(conn, args):
    rx_id = getattr(args, "prescription_id", None)
    if not rx_id:
        err("--prescription-id is required")
    if not getattr(args, "dispensed_by", None):
        err("--dispensed-by is required")

    row = conn.execute(Q.from_(Table("healthclaw_prescription")).select(Table("healthclaw_prescription").star).where(Field("id") == P()).get_sql(), (rx_id,)).fetchone()
    if not row:
        err(f"Prescription {rx_id} not found")
    rx = row_to_dict(row)

    if rx["rx_status"] in ("expired", "cancelled"):
        err(f"Cannot refill prescription with status: {rx['rx_status']}")
    if rx["refills_used"] >= rx["refills_authorized"]:
        err(f"No refills remaining (used {rx['refills_used']} of {rx['refills_authorized']})")

    quantity = int(getattr(args, "quantity_dispensed", None) or rx["quantity_prescribed"])

    # Create dispense log as refill
    disp_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute(
        """INSERT INTO healthclaw_dispense_log
           (id, company_id, prescription_id, medication_id, dispensed_by,
            quantity_dispensed, dispense_date, is_refill, lot_number,
            expiration_date, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
        (disp_id, rx["company_id"], rx_id, rx["medication_id"],
         args.dispensed_by, quantity, now,
         getattr(args, "lot_number", None),
         getattr(args, "expiration_date", None),
         getattr(args, "notes", None), now)
    )

    # Update medication inventory
    conn.execute(
        "UPDATE healthclaw_medication SET quantity_on_hand = quantity_on_hand - ? WHERE id = ?",
        (quantity, rx["medication_id"])
    )

    # Update refills_used
    new_refills = rx["refills_used"] + 1
    new_status = "filled" if new_refills >= rx["refills_authorized"] else "active"
    conn.execute(
        "UPDATE healthclaw_prescription SET refills_used = ?, rx_status = ?, updated_at = datetime('now') WHERE id = ?",
        (new_refills, new_status, rx_id)
    )

    # Controlled substance log
    med_row = conn.execute("SELECT dea_schedule FROM healthclaw_medication WHERE id = ?",
                           (rx["medication_id"],)).fetchone()
    if med_row and med_row[0] != "non-scheduled":
        cs_log_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO healthclaw_controlled_substance_log
               (id, company_id, medication_id, prescription_id, action_type,
                quantity, dea_number, performed_by, witness, log_date, notes, created_at)
               VALUES (?, ?, ?, ?, 'dispensed', ?, ?, ?, ?, ?, ?, ?)""",
            (cs_log_id, rx["company_id"], rx["medication_id"], rx_id,
             quantity, rx.get("dea_number"), args.dispensed_by,
             getattr(args, "witness", None), now,
             getattr(args, "notes", None), now)
        )

    audit(conn, "healthclaw_prescription", rx_id, "health-refill-prescription", rx["company_id"])
    conn.commit()
    ok({"id": rx_id, "dispense_log_id": disp_id, "refill_number": new_refills,
        "refills_remaining": rx["refills_authorized"] - new_refills,
        "rx_status": new_status})


# ---------------------------------------------------------------------------
# 10. add-dispense-log
# ---------------------------------------------------------------------------
def add_dispense_log(conn, args):
    for req in ("company_id", "prescription_id", "dispensed_by"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    rx_row = conn.execute(Q.from_(Table("healthclaw_prescription")).select(Table("healthclaw_prescription").star).where(Field("id") == P()).get_sql(), (args.prescription_id,)).fetchone()
    if not rx_row:
        err(f"Prescription {args.prescription_id} not found")
    rx = row_to_dict(rx_row)

    quantity = int(getattr(args, "quantity_dispensed", None) or 0)
    if quantity <= 0:
        err("--quantity-dispensed must be > 0")

    disp_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_dispense_log", {"id": P(), "company_id": P(), "prescription_id": P(), "medication_id": P(), "dispensed_by": P(), "quantity_dispensed": P(), "dispense_date": P(), "is_refill": P(), "lot_number": P(), "expiration_date": P(), "notes": P(), "created_at": P()})

    conn.execute(sql,
        (disp_id, args.company_id, args.prescription_id, rx["medication_id"],
         args.dispensed_by, quantity, now,
         int(getattr(args, "is_refill", None) or 0),
         getattr(args, "lot_number", None),
         getattr(args, "expiration_date", None),
         getattr(args, "notes", None), now)
    )
    audit(conn, "healthclaw_dispense_log", disp_id, "health-add-dispense-log", args.company_id)
    conn.commit()
    ok({"id": disp_id, "prescription_id": args.prescription_id, "quantity_dispensed": quantity})


# ---------------------------------------------------------------------------
# 11. list-dispense-logs
# ---------------------------------------------------------------------------
def list_dispense_logs(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?"); params.append(args.company_id)
    if getattr(args, "prescription_id", None):
        where.append("prescription_id = ?"); params.append(args.prescription_id)
    if getattr(args, "medication_id", None):
        where.append("medication_id = ?"); params.append(args.medication_id)
    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM healthclaw_dispense_log WHERE {where_sql}", params).fetchone()[0]
    limit = getattr(args, "limit", None) or 50
    offset = getattr(args, "offset", None) or 0
    params.extend([limit, offset])
    rows = conn.execute(
        f"SELECT * FROM healthclaw_dispense_log WHERE {where_sql} ORDER BY dispense_date DESC LIMIT ? OFFSET ?", params
    ).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset, "has_more": (offset + limit) < total})


# ---------------------------------------------------------------------------
# 12. check-drug-interaction
# ---------------------------------------------------------------------------
def check_drug_interaction(conn, args):
    med_id = getattr(args, "medication_id", None)
    if not med_id:
        err("--medication-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_medication")).select(Field("id")).where(Field("id") == P()).get_sql(), (med_id,)).fetchone():
        err(f"Medication {med_id} not found")

    # Check interactions where this medication is either A or B
    rows = conn.execute(
        """SELECT di.*, ma.name as med_a_name, mb.name as med_b_name
           FROM healthclaw_drug_interaction di
           JOIN healthclaw_medication ma ON di.medication_a_id = ma.id
           JOIN healthclaw_medication mb ON di.medication_b_id = mb.id
           WHERE di.medication_a_id = ? OR di.medication_b_id = ?
           ORDER BY CASE di.severity
               WHEN 'contraindicated' THEN 1 WHEN 'major' THEN 2
               WHEN 'moderate' THEN 3 WHEN 'minor' THEN 4 END""",
        (med_id, med_id)
    ).fetchall()
    interactions = []
    for r in rows:
        d = row_to_dict(r)
        # Identify the other medication
        if d["medication_a_id"] == med_id:
            d["interacting_medication"] = d["med_b_name"]
            d["interacting_medication_id"] = d["medication_b_id"]
        else:
            d["interacting_medication"] = d["med_a_name"]
            d["interacting_medication_id"] = d["medication_a_id"]
        interactions.append(d)

    ok({"medication_id": med_id, "interaction_count": len(interactions),
        "interactions": interactions})


# ---------------------------------------------------------------------------
# 13. medication-inventory-report
# ---------------------------------------------------------------------------
def medication_inventory_report(conn, args):
    company_id = getattr(args, "company_id", None)
    where, params = ["is_active = 1"], []
    if company_id:
        where.append("company_id = ?"); params.append(company_id)
    where_sql = " AND ".join(where)

    rows = conn.execute(
        f"SELECT * FROM healthclaw_medication WHERE {where_sql} ORDER BY name ASC", params
    ).fetchall()

    total_value = Decimal("0.00")
    below_reorder = []
    out_of_stock = []
    controlled = []

    for r in rows:
        d = row_to_dict(r)
        qty = int(d.get("quantity_on_hand", 0))
        price = Decimal(d.get("unit_price", "0.00"))
        total_value += price * qty
        if qty <= 0:
            out_of_stock.append({"id": d["id"], "name": d["name"]})
        elif qty <= int(d.get("reorder_level", 0)):
            below_reorder.append({"id": d["id"], "name": d["name"],
                                  "quantity_on_hand": qty, "reorder_level": d["reorder_level"]})
        if d.get("dea_schedule") != "non-scheduled":
            controlled.append({"id": d["id"], "name": d["name"],
                               "dea_schedule": d["dea_schedule"], "quantity_on_hand": qty})

    ok({
        "total_medications": len(rows),
        "total_inventory_value": str(round_currency(total_value)),
        "out_of_stock_count": len(out_of_stock),
        "out_of_stock": out_of_stock,
        "below_reorder_count": len(below_reorder),
        "below_reorder": below_reorder,
        "controlled_substances": controlled,
        "controlled_count": len(controlled),
    })


# ---------------------------------------------------------------------------
# 14. controlled-substance-report
# ---------------------------------------------------------------------------
def controlled_substance_report(conn, args):
    company_id = getattr(args, "company_id", None)
    where, params = ["1=1"], []
    if company_id:
        where.append("csl.company_id = ?"); params.append(company_id)
    date_from = getattr(args, "date_from", None)
    if date_from:
        where.append("csl.log_date >= ?"); params.append(date_from)
    date_to = getattr(args, "date_to", None)
    if date_to:
        where.append("csl.log_date <= ?"); params.append(date_to)
    where_sql = " AND ".join(where)

    rows = conn.execute(
        f"""SELECT csl.*, m.name as medication_name, m.dea_schedule
            FROM healthclaw_controlled_substance_log csl
            JOIN healthclaw_medication m ON csl.medication_id = m.id
            WHERE {where_sql}
            ORDER BY csl.log_date DESC""",
        params
    ).fetchall()

    entries = [row_to_dict(r) for r in rows]
    # Summarize by action type
    summary = {}
    for e in entries:
        at = e.get("action_type", "unknown")
        if at not in summary:
            summary[at] = {"count": 0, "total_quantity": 0}
        summary[at]["count"] += 1
        summary[at]["total_quantity"] += int(e.get("quantity", 0))

    ok({
        "total_entries": len(entries),
        "entries": entries,
        "summary_by_action": summary,
    })


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-add-medication": add_medication,
    "health-list-medications": list_medications,
    "health-get-medication": get_medication,
    "health-update-medication": update_medication,
    "health-adv-add-prescription": add_prescription,
    "health-adv-list-prescriptions": list_prescriptions,
    "health-get-prescription": get_prescription,
    "health-fill-prescription": fill_prescription,
    "health-refill-prescription": refill_prescription,
    "health-add-dispense-log": add_dispense_log,
    "health-list-dispense-logs": list_dispense_logs,
    "health-check-drug-interaction": check_drug_interaction,
    "health-medication-inventory-report": medication_inventory_report,
    "health-controlled-substance-report": controlled_substance_report,
}
