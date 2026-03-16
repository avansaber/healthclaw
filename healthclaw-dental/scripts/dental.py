"""HealthClaw Dental — dental domain module

Actions for the dental expansion (4 tables, 12 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from decimal import Decimal

try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, update_row
    from erpclaw_lib.vendor.pypika.terms import LiteralValue
except ImportError:
    pass


# ---- Helpers ----------------------------------------------------------------

def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


VALID_TOOTH_SYSTEMS = ("universal", "palmer", "fdi")
VALID_CHART_STATUSES = ("active", "resolved", "monitoring")
VALID_PROC_STATUSES = ("planned", "in_progress", "completed", "cancelled")
VALID_PLAN_STATUSES = ("proposed", "accepted", "in_progress", "completed", "cancelled")
VALID_PERIO_STATUSES = ("in_progress", "complete")
VALID_QUADRANTS = ("UR", "UL", "LR", "LL")
VALID_SURFACES = ("M", "O", "D", "B", "L", "I", "F")


def _validate_enum(val, choices, label):
    if val not in choices:
        err(f"Invalid {label}: {val}. Must be one of: {', '.join(choices)}")


def _validate_tooth_number(num):
    """Validate universal tooth numbering (1-32 permanent, A-T primary)."""
    if num.isdigit():
        n = int(num)
        if 1 <= n <= 32:
            return
    if len(num) == 1 and "A" <= num.upper() <= "T":
        return
    err(f"Invalid tooth number: {num}. Use 1-32 (permanent) or A-T (primary)")


def _validate_surface(surface):
    """Validate surface codes (M, O, D, B, L, I, F or combinations like MOD)."""
    if not surface:
        return
    for ch in surface.upper():
        if ch not in VALID_SURFACES:
            err(f"Invalid surface code '{ch}' in '{surface}'. Valid: {', '.join(VALID_SURFACES)}")


# ---------------------------------------------------------------------------
# 1. add-tooth-chart-entry
# ---------------------------------------------------------------------------
def add_tooth_chart_entry(conn, args):
    if not getattr(args, "patient_id", None):
        err("--patient-id is required")
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    if not getattr(args, "tooth_number", None):
        err("--tooth-number is required")
    if not getattr(args, "condition", None):
        err("--condition is required")
    if not getattr(args, "noted_date", None):
        err("--noted-date is required")

    # Validate patient exists
    t_pat = Table("healthclaw_patient")
    q = Q.from_(t_pat).select(t_pat.id).where(t_pat.id == P())
    if not conn.execute(q.get_sql(), (args.patient_id,)).fetchone():
        err(f"Patient {args.patient_id} not found")

    noted_by_id = getattr(args, "noted_by_id", None)
    if noted_by_id:
        t_emp = Table("employee")
        q = Q.from_(t_emp).select(t_emp.id).where(t_emp.id == P())
        if not conn.execute(q.get_sql(), (noted_by_id,)).fetchone():
            err(f"Employee {noted_by_id} not found")

    _validate_tooth_number(args.tooth_number)
    surface = getattr(args, "surface", None)
    if surface:
        _validate_surface(surface)

    tooth_system = getattr(args, "tooth_system", None) or "universal"
    _validate_enum(tooth_system, VALID_TOOTH_SYSTEMS, "tooth-system")

    entry_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_tooth_chart", {
        "id": P(), "patient_id": P(), "company_id": P(), "tooth_number": P(),
        "tooth_system": P(), "surface": P(), "condition": P(),
        "condition_detail": P(), "noted_date": P(), "noted_by_id": P(),
        "status": P(), "notes": P(), "created_at": P(), "updated_at": P(),
    })
    conn.execute(sql, (
        entry_id, args.patient_id, args.company_id, args.tooth_number, tooth_system,
        surface, args.condition, getattr(args, "condition_detail", None),
        args.noted_date, getattr(args, "noted_by_id", None),
        "active", getattr(args, "notes", None), now, now,
    ))
    audit(conn, "healthclaw_tooth_chart", entry_id, "dental-add-tooth-chart-entry", args.company_id)
    conn.commit()
    ok({"id": entry_id, "tooth_number": args.tooth_number, "condition": args.condition})


# ---------------------------------------------------------------------------
# 2. update-tooth-chart-entry
# ---------------------------------------------------------------------------
def update_tooth_chart_entry(conn, args):
    entry_id = getattr(args, "tooth_chart_id", None)
    if not entry_id:
        err("--tooth-chart-id is required")
    t = Table("healthclaw_tooth_chart")
    q = Q.from_(t).select(t.id).where(t.id == P())
    if not conn.execute(q.get_sql(), (entry_id,)).fetchone():
        err(f"Tooth chart entry {entry_id} not found")

    updates, params, changed = [], [], []
    for arg_name, col_name in {
        "condition": "condition", "condition_detail": "condition_detail",
        "surface": "surface", "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            if col_name == "surface":
                _validate_surface(val)
            updates.append(f"{col_name} = ?"); params.append(val); changed.append(col_name)
    status = getattr(args, "status", None)
    if status:
        _validate_enum(status, VALID_CHART_STATUSES, "status")
        updates.append("status = ?"); params.append(status); changed.append("status")

    if not updates:
        err("No fields to update")
    updates.append("updated_at = datetime('now')")
    params.append(entry_id)
    conn.execute(f"UPDATE healthclaw_tooth_chart SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "healthclaw_tooth_chart", entry_id, "dental-update-tooth-chart-entry", getattr(args, "company_id", None))
    conn.commit()
    ok({"id": entry_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 3. get-tooth-chart
# ---------------------------------------------------------------------------
def get_tooth_chart(conn, args):
    patient_id = getattr(args, "patient_id", None)
    if not patient_id:
        err("--patient-id is required")
    t = Table("healthclaw_tooth_chart")
    q = (Q.from_(t).select(t.star)
         .where(t.patient_id == P())
         .where(t.status == P())
         .orderby(LiteralValue("CAST(\"tooth_number\" AS INTEGER)")))
    rows = conn.execute(q.get_sql(), (patient_id, "active")).fetchall()
    chart = {}
    for r in rows:
        d = row_to_dict(r)
        tooth = d["tooth_number"]
        if tooth not in chart:
            chart[tooth] = []
        chart[tooth].append(d)
    ok({"patient_id": patient_id, "tooth_count": len(chart), "chart": chart, "total_entries": len(rows)})


# ---------------------------------------------------------------------------
# 4. add-dental-procedure
# ---------------------------------------------------------------------------
def add_dental_procedure(conn, args):
    for req in ("encounter_id", "patient_id", "company_id", "provider_id", "cdt_code", "procedure_date"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    # Validate encounter exists
    t_enc = Table("healthclaw_encounter")
    q = Q.from_(t_enc).select(t_enc.id).where(t_enc.id == P())
    if not conn.execute(q.get_sql(), (args.encounter_id,)).fetchone():
        err(f"Encounter {args.encounter_id} not found")
    # Validate patient exists
    t_pat = Table("healthclaw_patient")
    q = Q.from_(t_pat).select(t_pat.id).where(t_pat.id == P())
    if not conn.execute(q.get_sql(), (args.patient_id,)).fetchone():
        err(f"Patient {args.patient_id} not found")
    # Validate provider exists
    t_emp = Table("employee")
    q = Q.from_(t_emp).select(t_emp.id).where(t_emp.id == P())
    if not conn.execute(q.get_sql(), (args.provider_id,)).fetchone():
        err(f"Provider {args.provider_id} not found")

    tooth_number = getattr(args, "tooth_number", None)
    if tooth_number:
        _validate_tooth_number(tooth_number)
    surface = getattr(args, "surface", None)
    if surface:
        _validate_surface(surface)
    quadrant = getattr(args, "quadrant", None)
    if quadrant:
        _validate_enum(quadrant, VALID_QUADRANTS, "quadrant")

    fee = str(round_currency(to_decimal(getattr(args, "fee", None) or "0.00")))

    proc_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_dental_procedure", {
        "id": P(), "encounter_id": P(), "patient_id": P(), "company_id": P(),
        "provider_id": P(), "cdt_code": P(), "cdt_description": P(),
        "tooth_number": P(), "surface": P(), "quadrant": P(),
        "procedure_date": P(), "fee": P(), "status": P(),
        "notes": P(), "created_at": P(), "updated_at": P(),
    })
    conn.execute(sql, (
        proc_id, args.encounter_id, args.patient_id, args.company_id, args.provider_id,
        args.cdt_code, getattr(args, "cdt_description", None),
        tooth_number, surface, quadrant, args.procedure_date, fee, "planned",
        getattr(args, "notes", None), now, now,
    ))
    audit(conn, "healthclaw_dental_procedure", proc_id, "dental-add-dental-procedure", args.company_id)
    conn.commit()
    ok({"id": proc_id, "cdt_code": args.cdt_code, "fee": fee})


# ---------------------------------------------------------------------------
# 5. list-dental-procedures
# ---------------------------------------------------------------------------
def list_dental_procedures(conn, args):
    t = Table("healthclaw_dental_procedure")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "encounter_id", None):
        q_count = q_count.where(t.encounter_id == P())
        q_rows = q_rows.where(t.encounter_id == P())
        params.append(args.encounter_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P())
        q_rows = q_rows.where(t.patient_id == P())
        params.append(args.patient_id)
    if getattr(args, "cdt_code", None):
        q_count = q_count.where(t.cdt_code == P())
        q_rows = q_rows.where(t.cdt_code == P())
        params.append(args.cdt_code)
    if getattr(args, "status", None):
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(args.status)
    if getattr(args, "search", None):
        s = f"%{args.search}%"
        search_crit = (t.cdt_code.like(P())) | (t.cdt_description.like(P())) | (t.notes.like(P()))
        q_count = q_count.where(search_crit)
        q_rows = q_rows.where(search_crit)
        params.extend([s, s, s])

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.procedure_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 6. add-treatment-plan
# ---------------------------------------------------------------------------
def add_treatment_plan(conn, args):
    for req in ("patient_id", "company_id", "provider_id", "plan_name", "plan_date"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    t_pat = Table("healthclaw_patient")
    q = Q.from_(t_pat).select(t_pat.id).where(t_pat.id == P())
    if not conn.execute(q.get_sql(), (args.patient_id,)).fetchone():
        err(f"Patient {args.patient_id} not found")
    t_emp = Table("employee")
    q = Q.from_(t_emp).select(t_emp.id).where(t_emp.id == P())
    if not conn.execute(q.get_sql(), (args.provider_id,)).fetchone():
        err(f"Provider {args.provider_id} not found")

    phases = getattr(args, "phases", None) or "[]"
    # Validate JSON
    try:
        json.loads(phases)
    except (json.JSONDecodeError, TypeError):
        err("--phases must be valid JSON array")

    estimated_total = str(round_currency(to_decimal(getattr(args, "estimated_total", None) or "0.00")))
    insurance_estimate = str(round_currency(to_decimal(getattr(args, "insurance_estimate", None) or "0.00")))
    patient_estimate = str(round_currency(to_decimal(getattr(args, "patient_estimate", None) or "0.00")))

    plan_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_treatment_plan", {
        "id": P(), "patient_id": P(), "company_id": P(), "provider_id": P(),
        "plan_name": P(), "plan_date": P(), "phases": P(),
        "estimated_total": P(), "insurance_estimate": P(), "patient_estimate": P(),
        "status": P(), "notes": P(), "created_at": P(), "updated_at": P(),
    })
    conn.execute(sql, (
        plan_id, args.patient_id, args.company_id, args.provider_id, args.plan_name,
        args.plan_date, phases, estimated_total, insurance_estimate, patient_estimate,
        "proposed", getattr(args, "notes", None), now, now,
    ))
    audit(conn, "healthclaw_treatment_plan", plan_id, "dental-add-treatment-plan", args.company_id)
    conn.commit()
    ok({"id": plan_id, "plan_name": args.plan_name, "estimated_total": estimated_total})


# ---------------------------------------------------------------------------
# 7. update-treatment-plan
# ---------------------------------------------------------------------------
def update_treatment_plan(conn, args):
    plan_id = getattr(args, "treatment_plan_id", None)
    if not plan_id:
        err("--treatment-plan-id is required")
    t = Table("healthclaw_treatment_plan")
    q = Q.from_(t).select(t.id).where(t.id == P())
    if not conn.execute(q.get_sql(), (plan_id,)).fetchone():
        err(f"Treatment plan {plan_id} not found")

    updates, params, changed = [], [], []
    for arg_name, col_name in {
        "plan_name": "plan_name", "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            updates.append(f"{col_name} = ?"); params.append(val); changed.append(col_name)

    status = getattr(args, "status", None)
    if status:
        _validate_enum(status, VALID_PLAN_STATUSES, "status")
        updates.append("status = ?"); params.append(status); changed.append("status")

    phases = getattr(args, "phases", None)
    if phases:
        try:
            json.loads(phases)
        except (json.JSONDecodeError, TypeError):
            err("--phases must be valid JSON array")
        updates.append("phases = ?"); params.append(phases); changed.append("phases")

    for money_field in ("estimated_total", "insurance_estimate", "patient_estimate"):
        val = getattr(args, money_field, None)
        if val is not None:
            updates.append(f"{money_field} = ?")
            params.append(str(round_currency(to_decimal(val))))
            changed.append(money_field)

    if not updates:
        err("No fields to update")
    updates.append("updated_at = datetime('now')")
    params.append(plan_id)
    conn.execute(f"UPDATE healthclaw_treatment_plan SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "healthclaw_treatment_plan", plan_id, "dental-update-treatment-plan", getattr(args, "company_id", None))
    conn.commit()
    ok({"id": plan_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 8. list-treatment-plans
# ---------------------------------------------------------------------------
def list_treatment_plans(conn, args):
    t = Table("healthclaw_treatment_plan")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P())
        q_rows = q_rows.where(t.patient_id == P())
        params.append(args.patient_id)
    if getattr(args, "status", None):
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(args.status)
    if getattr(args, "search", None):
        s = f"%{args.search}%"
        search_crit = (t.plan_name.like(P())) | (t.notes.like(P()))
        q_count = q_count.where(search_crit)
        q_rows = q_rows.where(search_crit)
        params.extend([s, s])

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.plan_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 9. add-perio-exam
# ---------------------------------------------------------------------------
def add_perio_exam(conn, args):
    for req in ("patient_id", "company_id", "provider_id", "exam_date"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    t_pat = Table("healthclaw_patient")
    q = Q.from_(t_pat).select(t_pat.id).where(t_pat.id == P())
    if not conn.execute(q.get_sql(), (args.patient_id,)).fetchone():
        err(f"Patient {args.patient_id} not found")
    t_emp = Table("employee")
    q = Q.from_(t_emp).select(t_emp.id).where(t_emp.id == P())
    if not conn.execute(q.get_sql(), (args.provider_id,)).fetchone():
        err(f"Provider {args.provider_id} not found")

    measurements = getattr(args, "measurements", None) or "{}"
    try:
        json.loads(measurements)
    except (json.JSONDecodeError, TypeError):
        err("--measurements must be valid JSON object")

    bleeding_sites = getattr(args, "bleeding_sites", None) or "[]"
    try:
        json.loads(bleeding_sites)
    except (json.JSONDecodeError, TypeError):
        err("--bleeding-sites must be valid JSON array")

    exam_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_perio_exam", {
        "id": P(), "patient_id": P(), "company_id": P(), "provider_id": P(),
        "exam_date": P(), "measurements": P(), "bleeding_sites": P(),
        "furcation_data": P(), "mobility_data": P(), "recession_data": P(),
        "plaque_score": P(), "notes": P(), "status": P(),
        "created_at": P(), "updated_at": P(),
    })
    conn.execute(sql, (
        exam_id, args.patient_id, args.company_id, args.provider_id, args.exam_date,
        measurements, bleeding_sites,
        getattr(args, "furcation_data", None) or "{}", getattr(args, "mobility_data", None) or "{}",
        getattr(args, "recession_data", None) or "{}", getattr(args, "plaque_score", None),
        getattr(args, "notes", None), "complete", now, now,
    ))
    audit(conn, "healthclaw_perio_exam", exam_id, "dental-add-perio-exam", args.company_id)
    conn.commit()
    ok({"id": exam_id, "exam_date": args.exam_date})


# ---------------------------------------------------------------------------
# 10. get-perio-exam
# ---------------------------------------------------------------------------
def get_perio_exam(conn, args):
    exam_id = getattr(args, "perio_exam_id", None)
    if not exam_id:
        err("--perio-exam-id is required")
    t = Table("healthclaw_perio_exam")
    q = Q.from_(t).select(t.star).where(t.id == P())
    row = conn.execute(q.get_sql(), (exam_id,)).fetchone()
    if not row:
        err(f"Perio exam {exam_id} not found")
    data = row_to_dict(row)
    # Parse JSON fields
    for field in ("measurements", "bleeding_sites", "furcation_data", "mobility_data", "recession_data"):
        if data.get(field):
            try:
                data[field] = json.loads(data[field])
            except (json.JSONDecodeError, TypeError):
                pass
    ok(data)


# ---------------------------------------------------------------------------
# 11. list-perio-exams
# ---------------------------------------------------------------------------
def list_perio_exams(conn, args):
    t = Table("healthclaw_perio_exam")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P())
        q_rows = q_rows.where(t.patient_id == P())
        params.append(args.patient_id)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.exam_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": args.limit, "offset": args.offset, "has_more": (args.offset + args.limit) < total})


# ---------------------------------------------------------------------------
# 12. compare-perio-exams
# ---------------------------------------------------------------------------
def compare_perio_exams(conn, args):
    exam_id_1 = getattr(args, "exam_id_1", None)
    exam_id_2 = getattr(args, "exam_id_2", None)
    if not exam_id_1 or not exam_id_2:
        err("--exam-id-1 and --exam-id-2 are required")

    t = Table("healthclaw_perio_exam")
    q = Q.from_(t).select(t.star).where(t.id == P())
    row1 = conn.execute(q.get_sql(), (exam_id_1,)).fetchone()
    row2 = conn.execute(q.get_sql(), (exam_id_2,)).fetchone()
    if not row1:
        err(f"Perio exam {exam_id_1} not found")
    if not row2:
        err(f"Perio exam {exam_id_2} not found")

    d1, d2 = row_to_dict(row1), row_to_dict(row2)

    # Parse measurements
    try:
        m1 = json.loads(d1.get("measurements", "{}"))
        m2 = json.loads(d2.get("measurements", "{}"))
    except (json.JSONDecodeError, TypeError):
        m1, m2 = {}, {}

    # Compare: find improvements and regressions
    all_teeth = set(list(m1.keys()) + list(m2.keys()))
    improvements, regressions, stable = [], [], []

    for tooth in sorted(all_teeth):
        depths1 = m1.get(tooth, [])
        depths2 = m2.get(tooth, [])
        if not depths1 or not depths2:
            continue
        avg1 = sum(depths1) / len(depths1) if depths1 else 0
        avg2 = sum(depths2) / len(depths2) if depths2 else 0
        diff = avg2 - avg1
        entry = {"tooth": tooth, "avg_before": round(avg1, 1), "avg_after": round(avg2, 1), "change": round(diff, 1)}
        if diff < -0.5:
            improvements.append(entry)
        elif diff > 0.5:
            regressions.append(entry)
        else:
            stable.append(entry)

    # Bleeding sites comparison
    try:
        b1 = set(json.loads(d1.get("bleeding_sites", "[]")))
        b2 = set(json.loads(d2.get("bleeding_sites", "[]")))
    except (json.JSONDecodeError, TypeError):
        b1, b2 = set(), set()

    ok({
        "exam_1": {"id": exam_id_1, "date": d1.get("exam_date")},
        "exam_2": {"id": exam_id_2, "date": d2.get("exam_date")},
        "improvements": improvements,
        "regressions": regressions,
        "stable_count": len(stable),
        "bleeding_sites_before": len(b1),
        "bleeding_sites_after": len(b2),
        "bleeding_change": len(b2) - len(b1),
    })


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "dental-add-tooth-chart-entry": add_tooth_chart_entry,
    "dental-update-tooth-chart-entry": update_tooth_chart_entry,
    "dental-get-tooth-chart": get_tooth_chart,
    "dental-add-dental-procedure": add_dental_procedure,
    "dental-list-dental-procedures": list_dental_procedures,
    "dental-add-treatment-plan": add_treatment_plan,
    "dental-update-treatment-plan": update_treatment_plan,
    "dental-list-treatment-plans": list_treatment_plans,
    "dental-add-perio-exam": add_perio_exam,
    "dental-get-perio-exam": get_perio_exam,
    "dental-list-perio-exams": list_perio_exams,
    "dental-compare-perio-exams": compare_perio_exams,
}
