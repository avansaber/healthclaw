"""HealthClaw Advanced — billing domain module.

Actions for procedure codes, charges, claims, and payment postings.
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
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update, update_row
except ImportError:
    pass

ENTITY_PREFIXES.setdefault("healthclaw_charge", "CHG-")
ENTITY_PREFIXES.setdefault("healthclaw_claim", "CLM-")

# ---- Constants ---------------------------------------------------------------

VALID_CODE_TYPES = ("CPT", "ICD-10", "HCPCS")
VALID_CHARGE_STATUSES = ("unbilled", "billed", "paid", "adjusted", "void")
VALID_CLAIM_STATUSES = ("draft", "submitted", "accepted", "denied", "paid", "appealed")


# ---- Helpers -----------------------------------------------------------------

def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_enum(val, choices, label):
    if val not in choices:
        err(f"Invalid {label}: {val}. Must be one of: {', '.join(choices)}")


# ---------------------------------------------------------------------------
# 1. add-procedure-code
# ---------------------------------------------------------------------------
def add_procedure_code(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    if not getattr(args, "code", None):
        err("--code is required")
    if not getattr(args, "description", None):
        err("--description is required")

    code_type = getattr(args, "code_type", None) or "CPT"
    _validate_enum(code_type, VALID_CODE_TYPES, "health-code-type")

    default_fee = str(round_currency(to_decimal(getattr(args, "default_fee", None) or "0.00")))

    pc_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_procedure_code", {"id": P(), "company_id": P(), "code": P(), "code_type": P(), "description": P(), "category": P(), "default_fee": P(), "is_active": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql,
        (pc_id, args.company_id, args.code, code_type, args.description,
         getattr(args, "category", None), default_fee, 1,
         getattr(args, "notes", None), now, now)
    )
    audit(conn, "healthclaw_procedure_code", pc_id, "health-add-procedure-code", args.company_id)
    conn.commit()
    ok({"id": pc_id, "code": args.code, "code_type": code_type, "default_fee": default_fee})


# ---------------------------------------------------------------------------
# 2. list-procedure-codes
# ---------------------------------------------------------------------------
def list_procedure_codes(conn, args):
    t = Table("healthclaw_procedure_code")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P()); q_rows = q_rows.where(t.company_id == P()); params.append(args.company_id)
    if getattr(args, "code_type", None):
        q_count = q_count.where(t.code_type == P()); q_rows = q_rows.where(t.code_type == P()); params.append(args.code_type)
    if getattr(args, "category", None):
        q_count = q_count.where(t.category == P()); q_rows = q_rows.where(t.category == P()); params.append(args.category)
    if getattr(args, "search", None):
        s = f"%{args.search}%"
        crit = LiteralValue("(\"code\" LIKE ? OR \"description\" LIKE ?)")
        q_count = q_count.where(crit); q_rows = q_rows.where(crit)
        params.extend([s, s])

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    limit = getattr(args, "limit", None) or 50
    offset = getattr(args, "offset", None) or 0
    q_rows = q_rows.orderby(t.code, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset, "has_more": (offset + limit) < total})


# ---------------------------------------------------------------------------
# 3. add-charge
# ---------------------------------------------------------------------------
def add_charge(conn, args):
    for req in ("company_id", "patient_id", "provider_id", "service_date"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    # Validate procedure_code_id if provided
    procedure_code_id = getattr(args, "procedure_code_id", None)
    if procedure_code_id:
        if not conn.execute(Q.from_(Table("healthclaw_procedure_code")).select(Field("id")).where(Field("id") == P()).get_sql(), (procedure_code_id,)).fetchone():
            err(f"Procedure code {procedure_code_id} not found")

    unit_fee = str(round_currency(to_decimal(getattr(args, "unit_fee", None) or "0.00")))
    quantity = int(getattr(args, "quantity", None) or 1)
    total_fee = str(round_currency(to_decimal(unit_fee) * quantity))

    icd10_codes = getattr(args, "icd10_codes", None) or "[]"
    try:
        json.loads(icd10_codes)
    except (json.JSONDecodeError, TypeError):
        err("--icd10-codes must be valid JSON array")

    charge_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_charge", {"id": P(), "company_id": P(), "patient_id": P(), "provider_id": P(), "procedure_code_id": P(), "service_date": P(), "cpt_code": P(), "icd10_codes": P(), "description": P(), "quantity": P(), "unit_fee": P(), "total_fee": P(), "charge_status": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql,
        (charge_id, args.company_id, args.patient_id, args.provider_id,
         procedure_code_id, args.service_date,
         getattr(args, "cpt_code", None), icd10_codes,
         getattr(args, "description", None), quantity, unit_fee, total_fee,
         "unbilled",
         getattr(args, "notes", None), now, now)
    )
    audit(conn, "healthclaw_charge", charge_id, "health-add-charge", args.company_id)
    conn.commit()
    ok({"id": charge_id, "total_fee": total_fee, "charge_status": "unbilled"})


# ---------------------------------------------------------------------------
# 4. list-charges
# ---------------------------------------------------------------------------
def list_charges(conn, args):
    t = Table("healthclaw_charge")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P()); q_rows = q_rows.where(t.company_id == P()); params.append(args.company_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    charge_status = getattr(args, "charge_status", None)
    if charge_status:
        q_count = q_count.where(t.charge_status == P()); q_rows = q_rows.where(t.charge_status == P()); params.append(charge_status)
    if getattr(args, "search", None):
        s = f"%{args.search}%"
        crit = LiteralValue("(\"cpt_code\" LIKE ? OR \"description\" LIKE ? OR \"notes\" LIKE ?)")
        q_count = q_count.where(crit); q_rows = q_rows.where(crit)
        params.extend([s, s, s])

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    limit = getattr(args, "limit", None) or 50
    offset = getattr(args, "offset", None) or 0
    q_rows = q_rows.orderby(t.service_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset, "has_more": (offset + limit) < total})


# ---------------------------------------------------------------------------
# 5. get-charge
# ---------------------------------------------------------------------------
def get_charge(conn, args):
    charge_id = getattr(args, "charge_id", None)
    if not charge_id:
        err("--charge-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_charge")).select(Table("healthclaw_charge").star).where(Field("id") == P()).get_sql(), (charge_id,)).fetchone()
    if not row:
        err(f"Charge {charge_id} not found")
    data = row_to_dict(row)
    # Parse JSON fields
    if data.get("icd10_codes"):
        try:
            data["icd10_codes"] = json.loads(data["icd10_codes"])
        except (json.JSONDecodeError, TypeError):
            pass
    ok(data)


# ---------------------------------------------------------------------------
# 6. add-claim
# ---------------------------------------------------------------------------
def add_claim(conn, args):
    for req in ("company_id", "patient_id", "payer_name"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    charge_ids = getattr(args, "charge_ids", None) or "[]"
    try:
        parsed_ids = json.loads(charge_ids)
    except (json.JSONDecodeError, TypeError):
        err("--charge-ids must be valid JSON array")
        parsed_ids = []

    # Calculate total_charged from charges
    total_charged = Decimal("0.00")
    for cid in parsed_ids:
        row = conn.execute(Q.from_(Table("healthclaw_charge")).select(Field("total_fee")).where(Field("id") == P()).get_sql(), (cid,)).fetchone()
        if row:
            total_charged += to_decimal(row[0])

    claim_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_claim", {"id": P(), "company_id": P(), "patient_id": P(), "payer_name": P(), "payer_id_number": P(), "policy_number": P(), "group_number": P(), "claim_number": P(), "charge_ids": P(), "total_charged": P(), "total_allowed": P(), "total_paid": P(), "total_adjustment": P(), "patient_responsibility": P(), "claim_status": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql,
        (claim_id, args.company_id, args.patient_id, args.payer_name,
         getattr(args, "payer_id_number", None),
         getattr(args, "policy_number", None),
         getattr(args, "group_number", None),
         getattr(args, "claim_number", None),
         charge_ids,
         str(round_currency(total_charged)),
         "0.00", "0.00", "0.00", "0.00",
         "draft",
         getattr(args, "notes", None), now, now)
    )
    audit(conn, "healthclaw_claim", claim_id, "health-add-claim", args.company_id)
    conn.commit()
    ok({"id": claim_id, "total_charged": str(round_currency(total_charged)),
        "claim_status": "draft"})


# ---------------------------------------------------------------------------
# 7. list-claims
# ---------------------------------------------------------------------------
def list_claims(conn, args):
    t = Table("healthclaw_claim")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P()); q_rows = q_rows.where(t.company_id == P()); params.append(args.company_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    claim_status = getattr(args, "claim_status", None)
    if claim_status:
        q_count = q_count.where(t.claim_status == P()); q_rows = q_rows.where(t.claim_status == P()); params.append(claim_status)
    if getattr(args, "payer_name", None):
        q_count = q_count.where(t.payer_name == P()); q_rows = q_rows.where(t.payer_name == P()); params.append(args.payer_name)
    if getattr(args, "search", None):
        s = f"%{args.search}%"
        crit = LiteralValue("(\"payer_name\" LIKE ? OR \"claim_number\" LIKE ? OR \"notes\" LIKE ?)")
        q_count = q_count.where(crit); q_rows = q_rows.where(crit)
        params.extend([s, s, s])

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    limit = getattr(args, "limit", None) or 50
    offset = getattr(args, "offset", None) or 0
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset, "has_more": (offset + limit) < total})


# ---------------------------------------------------------------------------
# 8. get-claim
# ---------------------------------------------------------------------------
def get_claim(conn, args):
    claim_id = getattr(args, "claim_id", None)
    if not claim_id:
        err("--claim-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_claim")).select(Table("healthclaw_claim").star).where(Field("id") == P()).get_sql(), (claim_id,)).fetchone()
    if not row:
        err(f"Claim {claim_id} not found")
    data = row_to_dict(row)
    # Parse JSON fields
    if data.get("charge_ids"):
        try:
            data["charge_ids"] = json.loads(data["charge_ids"])
        except (json.JSONDecodeError, TypeError):
            pass
    ok(data)


# ---------------------------------------------------------------------------
# 9. submit-claim
# ---------------------------------------------------------------------------
def submit_claim(conn, args):
    claim_id = getattr(args, "claim_id", None)
    if not claim_id:
        err("--claim-id is required")

    row = conn.execute(Q.from_(Table("healthclaw_claim")).select(Table("healthclaw_claim").star).where(Field("id") == P()).get_sql(), (claim_id,)).fetchone()
    if not row:
        err(f"Claim {claim_id} not found")
    claim = row_to_dict(row)

    if claim["claim_status"] not in ("draft", "appealed"):
        err(f"Cannot submit claim with status: {claim['claim_status']}. Must be draft or appealed")

    now = _now_iso()
    sql = update_row("healthclaw_claim",
        data={"claim_status": "submitted", "submitted_date": P(), "updated_at": LiteralValue("datetime('now')")},
        where={"id": P()})
    conn.execute(sql, (now, claim_id))

    # Update associated charges to billed
    charge_ids_raw = claim.get("charge_ids", "[]")
    try:
        charge_ids = json.loads(charge_ids_raw) if isinstance(charge_ids_raw, str) else charge_ids_raw
    except (json.JSONDecodeError, TypeError):
        charge_ids = []
    _chg_sql = update_row("healthclaw_charge",
        data={"charge_status": "billed", "updated_at": LiteralValue("datetime('now')")},
        where={"id": P()})
    for cid in charge_ids:
        conn.execute(_chg_sql, (cid,))

    audit(conn, "healthclaw_claim", claim_id, "health-submit-claim", claim["company_id"])
    conn.commit()
    ok({"id": claim_id, "claim_status": "submitted", "submitted_date": now,
        "charges_billed": len(charge_ids)})


# ---------------------------------------------------------------------------
# 10. add-payment-posting
# ---------------------------------------------------------------------------
def add_payment_posting(conn, args):
    for req in ("company_id", "claim_id", "patient_id", "payer_name", "posting_date"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    # Validate claim
    if not conn.execute(Q.from_(Table("healthclaw_claim")).select(Field("id")).where(Field("id") == P()).get_sql(), (args.claim_id,)).fetchone():
        err(f"Claim {args.claim_id} not found")

    # Validate charge_id if provided
    charge_id = getattr(args, "charge_id", None)
    if charge_id:
        if not conn.execute(Q.from_(Table("healthclaw_charge")).select(Field("id")).where(Field("id") == P()).get_sql(), (charge_id,)).fetchone():
            err(f"Charge {charge_id} not found")

    allowed_amount = str(round_currency(to_decimal(getattr(args, "allowed_amount", None) or "0.00")))
    paid_amount = str(round_currency(to_decimal(getattr(args, "paid_amount", None) or "0.00")))
    adjustment = str(round_currency(to_decimal(getattr(args, "adjustment", None) or "0.00")))
    patient_responsibility = str(round_currency(to_decimal(
        getattr(args, "patient_responsibility", None) or "0.00")))

    pp_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_payment_posting", {"id": P(), "company_id": P(), "claim_id": P(), "charge_id": P(), "patient_id": P(), "payer_name": P(), "posting_date": P(), "allowed_amount": P(), "paid_amount": P(), "adjustment": P(), "patient_responsibility": P(), "payment_method": P(), "check_number": P(), "notes": P(), "created_at": P()})

    conn.execute(sql,
        (pp_id, args.company_id, args.claim_id, charge_id, args.patient_id,
         args.payer_name, args.posting_date, allowed_amount, paid_amount,
         adjustment, patient_responsibility,
         getattr(args, "payment_method", None),
         getattr(args, "check_number", None),
         getattr(args, "notes", None), now)
    )

    # PyPika: skipped — complex CAST arithmetic expression for claim totals
    conn.execute(
        """UPDATE healthclaw_claim SET
           total_allowed = CAST((CAST(total_allowed AS REAL) + CAST(? AS REAL)) AS TEXT),
           total_paid = CAST((CAST(total_paid AS REAL) + CAST(? AS REAL)) AS TEXT),
           total_adjustment = CAST((CAST(total_adjustment AS REAL) + CAST(? AS REAL)) AS TEXT),
           patient_responsibility = CAST((CAST(patient_responsibility AS REAL) + CAST(? AS REAL)) AS TEXT),
           updated_at = datetime('now')
           WHERE id = ?""",
        (allowed_amount, paid_amount, adjustment, patient_responsibility, args.claim_id)
    )

    audit(conn, "healthclaw_payment_posting", pp_id, "health-add-payment-posting", args.company_id)
    conn.commit()
    ok({"id": pp_id, "paid_amount": paid_amount, "adjustment": adjustment})


# ---------------------------------------------------------------------------
# 11. list-payment-postings
# ---------------------------------------------------------------------------
def list_payment_postings(conn, args):
    t = Table("healthclaw_payment_posting")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P()); q_rows = q_rows.where(t.company_id == P()); params.append(args.company_id)
    if getattr(args, "claim_id", None):
        q_count = q_count.where(t.claim_id == P()); q_rows = q_rows.where(t.claim_id == P()); params.append(args.claim_id)
    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P()); q_rows = q_rows.where(t.patient_id == P()); params.append(args.patient_id)
    if getattr(args, "payer_name", None):
        q_count = q_count.where(t.payer_name == P()); q_rows = q_rows.where(t.payer_name == P()); params.append(args.payer_name)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    limit = getattr(args, "limit", None) or 50
    offset = getattr(args, "offset", None) or 0
    q_rows = q_rows.orderby(t.posting_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"rows": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset, "has_more": (offset + limit) < total})


# ---------------------------------------------------------------------------
# 12. aging-report
# ---------------------------------------------------------------------------
def aging_report(conn, args):
    company_id = getattr(args, "company_id", None)
    where, params = ["charge_status IN ('unbilled', 'billed')"], []
    if company_id:
        where.append("company_id = ?"); params.append(company_id)
    where_sql = " AND ".join(where)

    # PyPika: skipped — complex julianday() calculation
    rows = conn.execute(
        f"""SELECT *,
            CAST(julianday('now') - julianday(service_date) AS INTEGER) as days_outstanding
            FROM healthclaw_charge
            WHERE {where_sql}
            ORDER BY service_date ASC""",
        params
    ).fetchall()

    buckets = {"0-30": [], "31-60": [], "61-90": [], "91-120": [], "120+": []}
    bucket_totals = {"0-30": Decimal("0.00"), "31-60": Decimal("0.00"),
                     "61-90": Decimal("0.00"), "91-120": Decimal("0.00"),
                     "120+": Decimal("0.00")}

    for r in rows:
        d = row_to_dict(r)
        days = int(d.get("days_outstanding", 0))
        fee = to_decimal(d.get("total_fee", "0.00"))
        entry = {"id": d["id"], "patient_id": d["patient_id"],
                 "service_date": d["service_date"], "total_fee": str(fee),
                 "days_outstanding": days, "charge_status": d["charge_status"]}

        if days <= 30:
            bucket = "0-30"
        elif days <= 60:
            bucket = "31-60"
        elif days <= 90:
            bucket = "61-90"
        elif days <= 120:
            bucket = "91-120"
        else:
            bucket = "120+"
        buckets[bucket].append(entry)
        bucket_totals[bucket] += fee

    total_outstanding = sum(bucket_totals.values())
    ok({
        "total_outstanding": str(round_currency(total_outstanding)),
        "total_charges": len(rows),
        "buckets": {k: {"count": len(v), "total": str(round_currency(bucket_totals[k]))}
                    for k, v in buckets.items()},
        "details": {k: v for k, v in buckets.items() if v},
    })


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-add-procedure-code": add_procedure_code,
    "health-list-procedure-codes": list_procedure_codes,
    "health-adv-add-charge": add_charge,
    "health-adv-list-charges": list_charges,
    "health-adv-get-charge": get_charge,
    "health-adv-add-claim": add_claim,
    "health-adv-list-claims": list_claims,
    "health-adv-get-claim": get_claim,
    "health-adv-submit-claim": submit_claim,
    "health-adv-add-payment-posting": add_payment_posting,
    "health-adv-list-payment-postings": list_payment_postings,
    "health-aging-report": aging_report,
}
