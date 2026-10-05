"""HealthClaw Advanced — billing domain module.

Actions for procedure codes, charges, claims, payment postings, and charity-care adjustments.
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from decimal import Decimal

try:
    import importlib.util
    if importlib.util.find_spec("erpclaw_lib") is None:
        sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update, update_row, now, days_between
except ImportError:
    pass

SKILL = "healthclaw"

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
    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_procedure_code", {"id": P(), "company_id": P(), "code": P(), "code_type": P(), "description": P(), "category": P(), "default_fee": P(), "is_active": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql,
        (pc_id, args.company_id, args.code, code_type, args.description,
         getattr(args, "category", None), default_fee, 1,
         getattr(args, "notes", None), _ts, _ts)
    )
    audit(conn, SKILL, "health-add-procedure-code", "healthclaw_procedure_code", pc_id)
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
        crit = LiteralValue("(LOWER(\"code\") LIKE LOWER(?) OR LOWER(\"description\") LIKE LOWER(?))")
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
    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_charge", {"id": P(), "company_id": P(), "patient_id": P(), "provider_id": P(), "procedure_code_id": P(), "service_date": P(), "cpt_code": P(), "icd10_codes": P(), "description": P(), "quantity": P(), "unit_fee": P(), "total_fee": P(), "charge_status": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql,
        (charge_id, args.company_id, args.patient_id, args.provider_id,
         procedure_code_id, args.service_date,
         getattr(args, "cpt_code", None), icd10_codes,
         getattr(args, "description", None), quantity, unit_fee, total_fee,
         "unbilled",
         getattr(args, "notes", None), _ts, _ts)
    )
    audit(conn, SKILL, "health-add-charge", "healthclaw_charge", charge_id)
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
        crit = LiteralValue("(LOWER(\"cpt_code\") LIKE LOWER(?) OR LOWER(\"description\") LIKE LOWER(?) OR LOWER(\"notes\") LIKE LOWER(?))")
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
    for req in ("company_id", "patient_id", "payer_name", "claim_date"):
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
    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_claim", {"id": P(), "company_id": P(), "patient_id": P(), "payer_name": P(), "payer_id_number": P(), "policy_number": P(), "group_number": P(), "claim_number": P(), "claim_date": P(), "charge_ids": P(), "total_charged": P(), "total_allowed": P(), "total_paid": P(), "total_adjustment": P(), "patient_responsibility": P(), "claim_status": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql,
        (claim_id, args.company_id, args.patient_id, args.payer_name,
         getattr(args, "payer_id_number", None),
         getattr(args, "policy_number", None),
         getattr(args, "group_number", None),
         getattr(args, "claim_number", None),
         args.claim_date,
         charge_ids,
         str(round_currency(total_charged)),
         "0.00", "0.00", "0.00", "0.00",
         "draft",
         getattr(args, "notes", None), _ts, _ts)
    )
    audit(conn, SKILL, "health-add-claim", "healthclaw_claim", claim_id)
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
        crit = LiteralValue("(LOWER(\"payer_name\") LIKE LOWER(?) OR LOWER(\"claim_number\") LIKE LOWER(?) OR LOWER(\"notes\") LIKE LOWER(?))")
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

    _ts = _now_iso()
    sql = update_row("healthclaw_claim",
        data={"claim_status": "submitted", "submitted_date": P(), "updated_at": now()},
        where={"id": P()})
    conn.execute(sql, (_ts, claim_id))

    # Update associated charges to billed
    charge_ids_raw = claim.get("charge_ids", "[]")
    try:
        charge_ids = json.loads(charge_ids_raw) if isinstance(charge_ids_raw, str) else charge_ids_raw
    except (json.JSONDecodeError, TypeError):
        charge_ids = []
    _chg_sql = update_row("healthclaw_charge",
        data={"charge_status": "billed", "updated_at": now()},
        where={"id": P()})
    for cid in charge_ids:
        conn.execute(_chg_sql, (cid,))

    audit(conn, SKILL, "health-submit-claim", "healthclaw_claim", claim_id)
    conn.commit()
    ok({"id": claim_id, "claim_status": "submitted", "submitted_date": _ts,
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
    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_payment_posting", {"id": P(), "company_id": P(), "claim_id": P(), "charge_id": P(), "patient_id": P(), "payer_name": P(), "posting_date": P(), "allowed_amount": P(), "paid_amount": P(), "adjustment": P(), "patient_responsibility": P(), "payment_method": P(), "check_number": P(), "notes": P(), "created_at": P()})

    conn.execute(sql,
        (pp_id, args.company_id, args.claim_id, charge_id, args.patient_id,
         args.payer_name, args.posting_date, allowed_amount, paid_amount,
         adjustment, patient_responsibility,
         getattr(args, "payment_method", None),
         getattr(args, "check_number", None),
         getattr(args, "notes", None), _ts)
    )

    # Claim totals accumulate in Decimal. SQL NUMERIC arithmetic computes in
    # floating point on SQLite and drops the scale ("200" for 200.00).
    from datetime import datetime as _dt, timezone as _tz
    _now_str = _dt.now(_tz.utc).strftime('%Y-%m-%d %H:%M:%S')
    _cur = conn.execute(
        Q.from_(Table("healthclaw_claim")).select(
            Field("total_allowed"), Field("total_paid"),
            Field("total_adjustment"), Field("patient_responsibility"),
        ).where(Field("id") == P()).get_sql(),
        (args.claim_id,)
    ).fetchone()
    _new_totals = [
        str(round_currency(to_decimal(_cur[i] or "0") + to_decimal(delta)))
        for i, delta in enumerate(
            (allowed_amount, paid_amount, adjustment, patient_responsibility))
    ]
    sql = update_row("healthclaw_claim",
        data={"total_allowed": P(), "total_paid": P(), "total_adjustment": P(),
              "patient_responsibility": P(), "updated_at": P()},
        where={"id": P()})
    conn.execute(sql, (*_new_totals, _now_str, args.claim_id))

    audit(conn, SKILL, "health-add-payment-posting", "healthclaw_payment_posting", pp_id)
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

    # Dialect-aware days_between helper replaces julianday calculation
    days_expr = days_between("'now'", "service_date").get_sql(quote_char=None)
    rows = conn.execute(
        f"""SELECT *,
            CAST({days_expr} AS INTEGER) as days_outstanding
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
# 13. post-patient-revenue
# ---------------------------------------------------------------------------
def post_patient_revenue(conn, args):
    """Post one submitted claim's recognized patient revenue to the GL.

    Debit the receivable account and credit the revenue account for the
    claim's exact total charged, through the shared GL posting seam in one
    transaction. Retries are idempotent through the GL voucher linkage on
    the claim: an identical retry returns the original receipt, while a
    retry naming different accounts is refused. Records audit linkage on
    the claim and returns the claim ID, exact amount, posting date, and
    GL entry IDs.
    """
    for req in ("company_id", "claim_id", "posting_date",
                "receivable_account_id", "revenue_account_id"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    company_id = args.company_id
    claim_id = args.claim_id
    posting_date = args.posting_date
    receivable_account_id = args.receivable_account_id
    revenue_account_id = args.revenue_account_id

    claim_row = conn.execute(
        Q.from_(Table("healthclaw_claim")).select(Table("healthclaw_claim").star).where(Field("id") == P()).get_sql(),
        (claim_id,)).fetchone()
    if not claim_row:
        err(f"Claim {claim_id} not found")
    claim = row_to_dict(claim_row)

    if claim.get("company_id") != company_id:
        err(f"Claim {claim_id} belongs to company {claim.get('company_id')}, not {company_id}")

    if claim.get("claim_status") != "submitted":
        err(f"Claim {claim_id} must be submitted to post patient revenue (status: {claim.get('claim_status')})")

    raw_total = claim.get("total_charged") or "0"
    if to_decimal(raw_total) == Decimal("0"):
        raw_total = claim.get("total_charge") or "0"
    amount = to_decimal(raw_total or "0")
    if amount <= Decimal("0"):
        err(f"Claim {claim_id} has no positive total charged to post")
    amount_str = str(round_currency(amount))

    prior = conn.execute(
        Q.from_(Table("gl_entry")).select(Field("id"), Field("account_id"), Field("debit"), Field("credit"), Field("posting_date")).where(Field("voucher_type") == P()).where(Field("voucher_id") == P()).where(Field("entry_set") == P()).where(Field("is_cancelled") == P()).get_sql(),
        ("journal_entry", claim_id, "primary", 0)).fetchall()
    if prior:
        debit_legs = [row_to_dict(r) for r in prior if to_decimal(dict(r).get("debit") or "0") > Decimal("0")]
        credit_legs = [row_to_dict(r) for r in prior if to_decimal(dict(r).get("credit") or "0") > Decimal("0")]
        posted_receivable = debit_legs[0]["account_id"] if len(debit_legs) == 1 else None
        posted_revenue = credit_legs[0]["account_id"] if len(credit_legs) == 1 else None
        posted_amount = to_decimal(debit_legs[0]["debit"]) if len(debit_legs) == 1 else None
        posted_date = row_to_dict(prior[0]).get("posting_date")
        posted_ids = [row_to_dict(r)["id"] for r in prior]
        if (posted_receivable == receivable_account_id
                and posted_revenue == revenue_account_id
                and posted_amount is not None and posted_amount == amount):
            ok({"id": claim_id, "claim_id": claim_id, "amount": amount_str,
                "total_charged": amount_str, "posting_date": posted_date,
                "gl_entry_ids": posted_ids, "gl_entry_count": len(posted_ids)})
        conn.rollback()
        err(f"Claim {claim_id} already posted with different accounts; refusing changed-account retry")

    def _load_account(account_id, label, root_type):
        account_row = conn.execute(
            Q.from_(Table("account")).select(Table("account").star).where(Field("id") == P()).get_sql(),
            (account_id,)).fetchone()
        if not account_row:
            err(f"{label} account {account_id} not found")
        account = row_to_dict(account_row)
        if account.get("company_id") != company_id:
            err(f"{label} account {account_id} belongs to company {account.get('company_id')}, not {company_id}")
        if account.get("is_group"):
            err(f"{label} account {account.get('name')} is a group account; post to a ledger account")
        if account.get("disabled"):
            err(f"{label} account {account.get('name')} is disabled")
        if (account.get("root_type") or "") != root_type:
            err(f"{label} account {account.get('name')} must be a {root_type} account")
        return account

    _load_account(receivable_account_id, "Receivable", "asset")
    _load_account(revenue_account_id, "Revenue", "income")

    cost_center_id = getattr(args, "cost_center_id", None)
    if cost_center_id:
        cc_row = conn.execute(
            Q.from_(Table("cost_center")).select(Table("cost_center").star).where(Field("id") == P()).get_sql(),
            (cost_center_id,)).fetchone()
        if not cc_row:
            err(f"Cost center {cost_center_id} not found")
        cc = row_to_dict(cc_row)
        if cc.get("company_id") != company_id:
            err(f"Cost center {cost_center_id} belongs to company {cc.get('company_id')}, not {company_id}")
        if cc.get("is_group"):
            err(f"Cost center {cc.get('name')} is a group cost center")
    else:
        co_row = conn.execute(
            Q.from_(Table("company")).select(Field("default_cost_center_id")).where(Field("id") == P()).get_sql(),
            (company_id,)).fetchone()
        if co_row and dict(co_row).get("default_cost_center_id"):
            cost_center_id = dict(co_row)["default_cost_center_id"]
    if not cost_center_id:
        cc_row = conn.execute(
            Q.from_(Table("cost_center")).select(Field("id")).where(Field("company_id") == P()).where(Field("is_group") == P()).limit(1).get_sql(),
            (company_id, 0)).fetchone()
        if cc_row:
            cost_center_id = dict(cc_row)["id"]

    try:
        from erpclaw_lib.gl_posting import insert_gl_entries
    except ImportError:
        conn.rollback()
        err("GL posting is unavailable for patient revenue")

    entries = [
        {"account_id": receivable_account_id, "debit": amount_str, "credit": "0",
         "party_type": "customer", "party_id": claim.get("patient_id")},
        {"account_id": revenue_account_id, "debit": "0", "credit": amount_str,
         "cost_center_id": cost_center_id},
    ]
    try:
        gl_ids = insert_gl_entries(
            conn, entries,
            voucher_type="journal_entry",
            voucher_id=claim_id,
            posting_date=posting_date,
            company_id=company_id,
            remarks=f"Patient revenue for claim {claim_id}",
            entry_set="primary",
        )
    except Exception as e:
        conn.rollback()
        err(f"GL posting failed for patient revenue {claim_id}: {e}")

    audit(conn, SKILL, "health-post-patient-revenue", "healthclaw_claim", claim_id,
          new_values={"company_id": company_id, "total_charged": amount_str,
                      "posting_date": posting_date,
                      "receivable_account_id": receivable_account_id,
                      "revenue_account_id": revenue_account_id,
                      "gl_entry_ids": gl_ids})
    conn.commit()
    ok({"id": claim_id, "claim_id": claim_id, "amount": amount_str,
        "total_charged": amount_str, "posting_date": posting_date,
        "gl_entry_ids": gl_ids, "gl_entry_count": len(gl_ids)})

# ---------------------------------------------------------------------------
# 14. apply-charity-care
# ---------------------------------------------------------------------------
def apply_charity_care(conn, args):
    """Apply one approved charity-care adjustment against a submitted claim.

    Debit the charity-care expense account and credit the receivable account
    for the exact approved amount, through the shared GL posting seam in one
    transaction. The claim must be submitted and belong to the posting
    company, and the call must carry an explicit approval date and approval
    reference. Both accounts must be active ledger accounts of that company:
    the receivable an asset and the charity-care account an expense. The
    amount must be an exact positive Decimal within the claim balance (total
    charged less paid, adjusted, and previously approved charity care).
    Retries naming the same claim plus approval reference are idempotent by
    the stored adjustment row: an identical retry returns the original
    receipt, while a changed-amount or changed-account retry is refused.
    Records audit linkage on the adjustment and returns the claim ID, exact
    amount, remaining balance, and GL entry IDs.
    """
    for req in ("company_id", "claim_id", "approval_date", "charity_amount",
                "approval_reference", "receivable_account_id",
                "charity_expense_account_id"):
        if not getattr(args, req, None):
            err(f"--{req.replace('_', '-')} is required")

    company_id = args.company_id
    claim_id = args.claim_id
    approval_date = args.approval_date
    approval_reference = args.approval_reference
    receivable_account_id = args.receivable_account_id
    charity_expense_account_id = args.charity_expense_account_id

    try:
        amount = round_currency(to_decimal(args.charity_amount))
    except (TypeError, ValueError):
        err(f"Invalid charity-care amount: {args.charity_amount!r}")
    if amount <= Decimal("0"):
        err(f"Charity-care amount must be positive, got {args.charity_amount!r}")
    amount_str = str(round_currency(amount))

    claim_row = conn.execute(
        Q.from_(Table("healthclaw_claim")).select(Table("healthclaw_claim").star).where(Field("id") == P()).get_sql(),
        (claim_id,)).fetchone()
    if not claim_row:
        err(f"Claim {claim_id} not found")
    claim = row_to_dict(claim_row)

    if claim.get("company_id") != company_id:
        err(f"Claim {claim_id} belongs to company {claim.get('company_id')}, not {company_id}")

    if claim.get("claim_status") != "submitted":
        err(f"Claim {claim_id} must be submitted to apply charity care (status: {claim.get('claim_status')})")

    history_rows = conn.execute(
        Q.from_(Table("healthclaw_charity_care_adjustment")).select(
            Field("id"), Field("approval_reference"), Field("amount"),
            Field("approval_date"), Field("receivable_account_id"),
            Field("charity_expense_account_id"), Field("gl_entry_ids")).where(Field("claim_id") == P()).get_sql(),
        (claim_id,)).fetchall()
    history = [row_to_dict(r) for r in history_rows]
    prior_total = sum((to_decimal(h.get("amount") or "0") for h in history), Decimal("0"))

    raw_total = claim.get("total_charged") or "0"
    if to_decimal(raw_total) == Decimal("0"):
        raw_total = claim.get("total_charge") or "0"
    claim_total = to_decimal(raw_total or "0")
    claim_consumed = to_decimal(claim.get("total_paid") or "0") + to_decimal(claim.get("total_adjustment") or "0")

    existing = next((h for h in history if h.get("approval_reference") == approval_reference), None)
    if existing is not None:
        if to_decimal(existing.get("amount") or "0") != amount:
            conn.rollback()
            err(f"Claim {claim_id} already has charity-care adjustment {approval_reference} for a different amount ({existing.get('amount')}); refusing changed-amount retry")
        if (existing.get("receivable_account_id") != receivable_account_id
                or existing.get("charity_expense_account_id") != charity_expense_account_id):
            conn.rollback()
            err(f"Claim {claim_id} already has charity-care adjustment {approval_reference} with different accounts; refusing changed-account retry")
        stored_ids = json.loads(existing.get("gl_entry_ids") or "[]")
        remaining_str = str(round_currency(claim_total - claim_consumed - prior_total))
        ok({"id": existing.get("id"), "claim_id": claim_id, "amount": existing.get("amount"),
            "remaining_balance": remaining_str, "approval_reference": approval_reference,
            "approval_date": existing.get("approval_date"),
            "gl_entry_ids": stored_ids, "gl_entry_count": len(stored_ids)})

    def _load_account(account_id, label, root_type):
        account_row = conn.execute(
            Q.from_(Table("account")).select(Table("account").star).where(Field("id") == P()).get_sql(),
            (account_id,)).fetchone()
        if not account_row:
            err(f"{label} account {account_id} not found")
        account = row_to_dict(account_row)
        if account.get("company_id") != company_id:
            err(f"{label} account {account_id} belongs to company {account.get('company_id')}, not {company_id}")
        if account.get("is_group"):
            err(f"{label} account {account.get('name')} is a group account; post to a ledger account")
        if account.get("disabled"):
            err(f"{label} account {account.get('name')} is disabled")
        if (account.get("root_type") or "") != root_type:
            err(f"{label} account {account.get('name')} must be a {root_type} account")
        return account

    _load_account(receivable_account_id, "Receivable", "asset")
    _load_account(charity_expense_account_id, "Charity-care", "expense")

    balance = claim_total - claim_consumed - prior_total
    if amount > balance:
        err(f"Charity-care amount {amount_str} exceeds claim {claim_id} balance {str(round_currency(balance))}")
    remaining_str = str(round_currency(balance - amount))

    cost_center_id = getattr(args, "cost_center_id", None)
    if cost_center_id:
        cc_row = conn.execute(
            Q.from_(Table("cost_center")).select(Table("cost_center").star).where(Field("id") == P()).get_sql(),
            (cost_center_id,)).fetchone()
        if not cc_row:
            err(f"Cost center {cost_center_id} not found")
        cc = row_to_dict(cc_row)
        if cc.get("company_id") != company_id:
            err(f"Cost center {cost_center_id} belongs to company {cc.get('company_id')}, not {company_id}")
        if cc.get("is_group"):
            err(f"Cost center {cc.get('name')} is a group cost center")
    else:
        co_row = conn.execute(
            Q.from_(Table("company")).select(Field("default_cost_center_id")).where(Field("id") == P()).get_sql(),
            (company_id,)).fetchone()
        if co_row and dict(co_row).get("default_cost_center_id"):
            cost_center_id = dict(co_row)["default_cost_center_id"]
    if not cost_center_id:
        cc_row = conn.execute(
            Q.from_(Table("cost_center")).select(Field("id")).where(Field("company_id") == P()).where(Field("is_group") == P()).limit(1).get_sql(),
            (company_id, 0)).fetchone()
        if cc_row:
            cost_center_id = dict(cc_row)["id"]

    try:
        from erpclaw_lib.gl_posting import insert_gl_entries
    except ImportError:
        conn.rollback()
        err("GL posting is unavailable for charity care")

    adj_id = str(uuid.uuid4())
    entries = [
        {"account_id": charity_expense_account_id, "debit": amount_str, "credit": "0",
         "cost_center_id": cost_center_id},
        {"account_id": receivable_account_id, "debit": "0", "credit": amount_str,
         "party_type": "customer", "party_id": claim.get("patient_id")},
    ]
    try:
        gl_ids = insert_gl_entries(
            conn, entries,
            voucher_type="journal_entry",
            voucher_id=adj_id,
            posting_date=approval_date,
            company_id=company_id,
            remarks=f"Charity care for claim {claim_id} ref {approval_reference}",
            entry_set="primary",
        )
    except Exception as e:
        conn.rollback()
        err(f"GL posting failed for charity care {claim_id} ref {approval_reference}: {e}")

    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_charity_care_adjustment",
        {"id": P(), "company_id": P(), "claim_id": P(), "approval_date": P(),
         "approval_reference": P(), "amount": P(), "receivable_account_id": P(),
         "charity_expense_account_id": P(), "gl_entry_ids": P(), "created_at": P()})
    conn.execute(sql,
        (adj_id, company_id, claim_id, approval_date, approval_reference,
         amount_str, receivable_account_id, charity_expense_account_id,
         json.dumps(gl_ids), _ts))

    audit(conn, SKILL, "health-apply-charity-care", "healthclaw_charity_care_adjustment", adj_id,
          new_values={"company_id": company_id, "claim_id": claim_id,
                      "approval_date": approval_date,
                      "approval_reference": approval_reference,
                      "amount": amount_str, "remaining_balance": remaining_str,
                      "receivable_account_id": receivable_account_id,
                      "charity_expense_account_id": charity_expense_account_id,
                      "gl_entry_ids": gl_ids})
    conn.commit()
    ok({"id": adj_id, "claim_id": claim_id, "amount": amount_str,
        "remaining_balance": remaining_str, "approval_reference": approval_reference,
        "approval_date": approval_date,
        "gl_entry_ids": gl_ids, "gl_entry_count": len(gl_ids)})

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
    "health-post-patient-revenue": post_patient_revenue,
    "health-apply-charity-care": apply_charity_care,
}
