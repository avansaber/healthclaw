"""HealthClaw Advanced — lab domain module.

Actions for lab tests, orders, results, and reporting.
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from decimal import Decimal

try:
    sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, update_row, now, hours_between
except ImportError:
    pass

ENTITY_PREFIXES.setdefault("healthclaw_lab_order", "LO-")
ENTITY_PREFIXES.setdefault("healthclaw_lab_result", "LR-")

# ---- Constants ---------------------------------------------------------------

VALID_PRIORITIES = ("routine", "stat", "urgent")
VALID_ORDER_STATUSES = ("ordered", "collected", "in_progress", "completed", "cancelled")


# ---- Helpers -----------------------------------------------------------------

def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_enum(val, choices, label):
    if val not in choices:
        err(f"Invalid {label}: {val}. Must be one of: {', '.join(choices)}")


# ---------------------------------------------------------------------------
# 1. add-lab-test
# ---------------------------------------------------------------------------
def add_lab_test(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    if not getattr(args, "test_name", None):
        err("--test-name is required")

    base_price = str(round_currency(to_decimal(getattr(args, "base_price", None) or "0.00")))
    turnaround_hours = getattr(args, "turnaround_hours", None)
    if turnaround_hours is not None:
        turnaround_hours = int(turnaround_hours)

    test_id = str(uuid.uuid4())
    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_lab_test", {"id": P(), "company_id": P(), "test_name": P(), "test_code": P(), "loinc_code": P(), "category": P(), "specimen_type": P(), "reference_range": P(), "unit": P(), "turnaround_hours": P(), "base_price": P(), "is_active": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql,
        (test_id, args.company_id, args.test_name,
         getattr(args, "test_code", None),
         getattr(args, "loinc_code", None),
         getattr(args, "category", None),
         getattr(args, "specimen_type", None),
         getattr(args, "reference_range", None),
         getattr(args, "unit", None),
         turnaround_hours, base_price, 1,
         getattr(args, "notes", None), _ts, _ts)
    )
    audit(conn, "healthclaw_lab_test", test_id, "health-add-lab-test", args.company_id)
    conn.commit()
    ok({"id": test_id, "test_name": args.test_name, "base_price": base_price})


# ---------------------------------------------------------------------------
# 2. list-lab-tests
# ---------------------------------------------------------------------------
def list_lab_tests(conn, args):
    t = Table("healthclaw_lab_test")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P()); q_rows = q_rows.where(t.company_id == P()); params.append(args.company_id)
    if getattr(args, "category", None):
        q_count = q_count.where(t.category == P()); q_rows = q_rows.where(t.category == P()); params.append(args.category)
    if getattr(args, "search", None):
        s = f"%{args.search}%"
        crit = LiteralValue("(LOWER(\"test_name\") LIKE LOWER(?) OR LOWER(\"test_code\") LIKE LOWER(?) OR LOWER(\"loinc_code\") LIKE LOWER(?))")
        q_count = q_count.where(crit); q_rows = q_rows.where(crit)
        params.extend([s, s, s])

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    limit = getattr(args, "limit", None) or 50
    offset = getattr(args, "offset", None) or 0
    q_rows = q_rows.orderby(t.test_name, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset, "has_more": (offset + limit) < total})


# ---------------------------------------------------------------------------
# 3. get-lab-test
# ---------------------------------------------------------------------------
def get_lab_test(conn, args):
    test_id = getattr(args, "lab_test_id", None)
    if not test_id:
        err("--lab-test-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_lab_test")).select(Table("healthclaw_lab_test").star).where(Field("id") == P()).get_sql(), (test_id,)).fetchone()
    if not row:
        err(f"Lab test {test_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# 4. add-lab-order
# ---------------------------------------------------------------------------
def add_lab_order(conn, args):
    for req in ("company_id", "patient_id", "ordering_provider", "lab_test_id", "order_date"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    # Validate lab test exists
    if not conn.execute(Q.from_(Table("healthclaw_lab_test")).select(Field("id")).where(Field("id") == P()).get_sql(), (args.lab_test_id,)).fetchone():
        err(f"Lab test {args.lab_test_id} not found")

    priority = getattr(args, "priority", None) or "routine"
    _validate_enum(priority, VALID_PRIORITIES, "priority")

    fasting_required = int(getattr(args, "fasting_required", None) or 0)

    order_id = str(uuid.uuid4())
    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_lab_order", {"id": P(), "company_id": P(), "patient_id": P(), "ordering_provider": P(), "lab_test_id": P(), "order_date": P(), "priority": P(), "order_status": P(), "clinical_notes": P(), "fasting_required": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql,
        (order_id, args.company_id, args.patient_id, args.ordering_provider,
         args.lab_test_id, args.order_date, priority, "ordered",
         getattr(args, "clinical_notes", None),
         fasting_required,
         getattr(args, "notes", None), _ts, _ts)
    )
    audit(conn, "healthclaw_lab_order", order_id, "health-add-lab-order", args.company_id)
    conn.commit()
    ok({"id": order_id, "lab_test_id": args.lab_test_id, "priority": priority,
        "order_status": "ordered"})


# ---------------------------------------------------------------------------
# 5. list-lab-orders
# ---------------------------------------------------------------------------
def list_lab_orders(conn, args):
    t = Table("healthclaw_lab_order")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P()); q_rows = q_rows.where(t.company_id == P()); params.append(args.company_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    if getattr(args, "lab_test_id", None):
        q_count = q_count.where(t.lab_test_id == P()); q_rows = q_rows.where(t.lab_test_id == P()); params.append(args.lab_test_id)
    order_status = getattr(args, "order_status", None)
    if order_status:
        q_count = q_count.where(t.order_status == P()); q_rows = q_rows.where(t.order_status == P()); params.append(order_status)
    if getattr(args, "priority", None):
        q_count = q_count.where(t.priority == P()); q_rows = q_rows.where(t.priority == P()); params.append(args.priority)
    if getattr(args, "search", None):
        s = f"%{args.search}%"
        crit = LiteralValue("(LOWER(\"clinical_notes\") LIKE LOWER(?) OR LOWER(\"notes\") LIKE LOWER(?))")
        q_count = q_count.where(crit); q_rows = q_rows.where(crit)
        params.extend([s, s])

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    limit = getattr(args, "limit", None) or 50
    offset = getattr(args, "offset", None) or 0
    q_rows = q_rows.orderby(t.order_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset, "has_more": (offset + limit) < total})


# ---------------------------------------------------------------------------
# 6. get-lab-order
# ---------------------------------------------------------------------------
def get_lab_order(conn, args):
    order_id = getattr(args, "lab_order_id", None)
    if not order_id:
        err("--lab-order-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_lab_order")).select(Table("healthclaw_lab_order").star).where(Field("id") == P()).get_sql(), (order_id,)).fetchone()
    if not row:
        err(f"Lab order {order_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# 7. add-lab-result
# ---------------------------------------------------------------------------
def add_lab_result(conn, args):
    for req in ("company_id", "lab_order_id", "result_date"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    # Validate lab order exists and get test info
    order_row = conn.execute(Q.from_(Table("healthclaw_lab_order")).select(Table("healthclaw_lab_order").star).where(Field("id") == P()).get_sql(), (args.lab_order_id,)).fetchone()
    if not order_row:
        err(f"Lab order {args.lab_order_id} not found")
    order = row_to_dict(order_row)

    is_abnormal = int(getattr(args, "is_abnormal", None) or 0)
    is_critical = int(getattr(args, "is_critical", None) or 0)

    result_id = str(uuid.uuid4())
    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_lab_result", {"id": P(), "company_id": P(), "lab_order_id": P(), "lab_test_id": P(), "patient_id": P(), "result_value": P(), "result_unit": P(), "reference_range": P(), "is_abnormal": P(), "is_critical": P(), "performed_by": P(), "verified_by": P(), "result_date": P(), "result_notes": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql,
        (result_id, args.company_id, args.lab_order_id, order["lab_test_id"],
         order["patient_id"],
         getattr(args, "result_value", None),
         getattr(args, "result_unit", None),
         getattr(args, "reference_range", None),
         is_abnormal, is_critical,
         getattr(args, "performed_by", None),
         getattr(args, "verified_by", None),
         args.result_date,
         getattr(args, "result_notes", None), _ts, _ts)
    )

    # Update order status to completed
    _upd_sql = update_row("healthclaw_lab_order",
        data={"order_status": "completed", "completed_at": P(), "updated_at": now()},
        where={"id": P()})
    conn.execute(_upd_sql, (_ts, args.lab_order_id))

    audit(conn, "healthclaw_lab_result", result_id, "health-add-lab-result", args.company_id)
    conn.commit()
    ok({"id": result_id, "lab_order_id": args.lab_order_id,
        "is_abnormal": is_abnormal, "is_critical": is_critical})


# ---------------------------------------------------------------------------
# 8. list-lab-results
# ---------------------------------------------------------------------------
def list_lab_results(conn, args):
    t = Table("healthclaw_lab_result")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P()); q_rows = q_rows.where(t.company_id == P()); params.append(args.company_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    if getattr(args, "lab_order_id", None):
        q_count = q_count.where(t.lab_order_id == P()); q_rows = q_rows.where(t.lab_order_id == P()); params.append(args.lab_order_id)
    if getattr(args, "lab_test_id", None):
        q_count = q_count.where(t.lab_test_id == P()); q_rows = q_rows.where(t.lab_test_id == P()); params.append(args.lab_test_id)
    if getattr(args, "is_abnormal", None):
        q_count = q_count.where(t.is_abnormal == 1); q_rows = q_rows.where(t.is_abnormal == 1)
    if getattr(args, "is_critical", None):
        q_count = q_count.where(t.is_critical == 1); q_rows = q_rows.where(t.is_critical == 1)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    limit = getattr(args, "limit", None) or 50
    offset = getattr(args, "offset", None) or 0
    q_rows = q_rows.orderby(t.result_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset, "has_more": (offset + limit) < total})


# ---------------------------------------------------------------------------
# 9. get-lab-result
# ---------------------------------------------------------------------------
def get_lab_result(conn, args):
    result_id = getattr(args, "lab_result_id", None)
    if not result_id:
        err("--lab-result-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_lab_result")).select(Table("healthclaw_lab_result").star).where(Field("id") == P()).get_sql(), (result_id,)).fetchone()
    if not row:
        err(f"Lab result {result_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# 10. mark-lab-critical
# ---------------------------------------------------------------------------
def mark_lab_critical(conn, args):
    result_id = getattr(args, "lab_result_id", None)
    if not result_id:
        err("--lab-result-id is required")

    row = conn.execute(Q.from_(Table("healthclaw_lab_result")).select(Table("healthclaw_lab_result").star).where(Field("id") == P()).get_sql(), (result_id,)).fetchone()
    if not row:
        err(f"Lab result {result_id} not found")

    _upd_sql = update_row("healthclaw_lab_result",
        data={"is_critical": 1, "is_abnormal": 1, "updated_at": now()},
        where={"id": P()})
    conn.execute(_upd_sql, (result_id,))
    audit(conn, "healthclaw_lab_result", result_id, "health-mark-lab-critical",
          getattr(args, "company_id", None) or row_to_dict(row).get("company_id"))
    conn.commit()
    ok({"id": result_id, "is_critical": 1, "is_abnormal": 1})


# ---------------------------------------------------------------------------
# 11. lab-turnaround-report
# ---------------------------------------------------------------------------
def lab_turnaround_report(conn, args):
    company_id = getattr(args, "company_id", None)
    where, params = ["lo.order_status = 'completed'", "lo.completed_at IS NOT NULL"], []
    if company_id:
        where.append("lo.company_id = ?"); params.append(company_id)
    date_from = getattr(args, "date_from", None)
    if date_from:
        where.append("lo.order_date >= ?"); params.append(date_from)
    date_to = getattr(args, "date_to", None)
    if date_to:
        where.append("lo.order_date <= ?"); params.append(date_to)
    where_sql = " AND ".join(where)

    # Dialect-aware hours_between helper replaces julianday calculation
    hours_expr = hours_between("lo.completed_at", "lo.order_date").get_sql(quote_char=None)
    rows = conn.execute(
        f"""SELECT lo.*, lt.test_name, lt.turnaround_hours as expected_hours,
            ROUND({hours_expr}, 1) as actual_hours
            FROM healthclaw_lab_order lo
            JOIN healthclaw_lab_test lt ON lo.lab_test_id = lt.id
            WHERE {where_sql}
            ORDER BY lo.order_date DESC""",
        params
    ).fetchall()

    entries = []
    total_hours = 0.0
    exceeded_count = 0
    for r in rows:
        d = row_to_dict(r)
        actual = float(d.get("actual_hours", 0) or 0)
        expected = int(d.get("expected_hours", 0) or 0)
        total_hours += actual
        met_target = actual <= expected if expected > 0 else True
        if not met_target:
            exceeded_count += 1
        entries.append({
            "order_id": d["id"],
            "test_name": d.get("test_name"),
            "order_date": d.get("order_date"),
            "completed_at": d.get("completed_at"),
            "actual_hours": actual,
            "expected_hours": expected,
            "met_target": met_target,
        })

    avg_hours = round(total_hours / len(entries), 1) if entries else 0.0

    ok({
        "total_completed": len(entries),
        "average_turnaround_hours": avg_hours,
        "exceeded_target_count": exceeded_count,
        "on_target_rate": round((len(entries) - exceeded_count) / len(entries) * 100, 1) if entries else 0.0,
        "entries": entries,
    })


# ---------------------------------------------------------------------------
# 12. abnormal-results-report
# ---------------------------------------------------------------------------
def abnormal_results_report(conn, args):
    company_id = getattr(args, "company_id", None)
    where, params = ["lr.is_abnormal = 1"], []
    if company_id:
        where.append("lr.company_id = ?"); params.append(company_id)
    if getattr(args, "patient_id", None):
        where.append("lr.patient_id = ?"); params.append(args.patient_id)
    date_from = getattr(args, "date_from", None)
    if date_from:
        where.append("lr.result_date >= ?"); params.append(date_from)
    date_to = getattr(args, "date_to", None)
    if date_to:
        where.append("lr.result_date <= ?"); params.append(date_to)
    where_sql = " AND ".join(where)

    # PyPika: skipped — complex JOIN report query
    rows = conn.execute(
        f"""SELECT lr.*, lt.test_name, lt.category
            FROM healthclaw_lab_result lr
            JOIN healthclaw_lab_test lt ON lr.lab_test_id = lt.id
            WHERE {where_sql}
            ORDER BY lr.is_critical DESC, lr.result_date DESC""",
        params
    ).fetchall()

    entries = [row_to_dict(r) for r in rows]
    critical_count = sum(1 for e in entries if e.get("is_critical"))

    ok({
        "total_abnormal": len(entries),
        "critical_count": critical_count,
        "entries": entries,
    })


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-adv-add-lab-test": add_lab_test,
    "health-adv-list-lab-tests": list_lab_tests,
    "health-get-lab-test": get_lab_test,
    "health-adv-add-lab-order": add_lab_order,
    "health-adv-list-lab-orders": list_lab_orders,
    "health-adv-get-lab-order": get_lab_order,
    "health-adv-add-lab-result": add_lab_result,
    "health-adv-list-lab-results": list_lab_results,
    "health-get-lab-result": get_lab_result,
    "health-mark-lab-critical": mark_lab_critical,
    "health-lab-turnaround-report": lab_turnaround_report,
    "health-abnormal-results-report": abnormal_results_report,
}
