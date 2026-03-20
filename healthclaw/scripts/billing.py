"""HealthClaw — billing domain module

Actions for the billing domain (6 tables, 16 actions).
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
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update, update_row

    # Register HealthClaw naming prefixes (billing domain)
    ENTITY_PREFIXES.setdefault("healthclaw_charge", "CHG-")
    ENTITY_PREFIXES.setdefault("healthclaw_claim", "CLM-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_FEE_SCHEDULE_STATUSES = ("active", "inactive", "expired")
VALID_PAYER_TYPES = ("commercial", "medicare", "medicaid", "self_pay", "workers_comp", "other")
VALID_CHARGE_STATUSES = ("unbilled", "billed", "paid", "adjusted", "void")
VALID_CLAIM_STATUSES = ("draft", "submitted", "accepted", "denied", "partially_paid", "paid", "appealed", "void")
VALID_CLAIM_TYPES = ("professional", "institutional", "dental")
VALID_POSTING_TYPES = ("insurance_payment", "patient_payment", "adjustment", "refund", "write_off")
VALID_PAYMENT_METHODS = ("check", "eft", "cash", "credit_card", "ach", "other")


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


def _validate_encounter(conn, encounter_id):
    if not encounter_id:
        err("--encounter-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_encounter")).select(Field("id")).where(Field("id") == P()).get_sql(), (encounter_id,)).fetchone():
        err(f"Encounter {encounter_id} not found")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


# ---------------------------------------------------------------------------
# 1. add-fee-schedule
# ---------------------------------------------------------------------------
def add_fee_schedule(conn, args):
    _validate_company(conn, args.company_id)

    name = getattr(args, "fee_schedule_name", None)
    if not name:
        err("--fee-schedule-name is required")
    effective_date = getattr(args, "effective_date", None)
    if not effective_date:
        err("--effective-date is required")

    payer_type = getattr(args, "payer_type", None)
    _validate_enum(payer_type, VALID_PAYER_TYPES, "health-payer-type")

    fs_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_fee_schedule", {"id": P(), "name": P(), "description": P(), "payer_type": P(), "effective_date": P(), "expiration_date": P(), "status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        fs_id, name,
        getattr(args, "description", None),
        payer_type, effective_date,
        getattr(args, "expiration_date", None),
        "active", args.company_id, now, now,
    ))
    audit(conn, "healthclaw_fee_schedule", fs_id, "health-add-fee-schedule", args.company_id)
    conn.commit()
    ok({"id": fs_id, "name": name, "status": "active"})


# ---------------------------------------------------------------------------
# 2. update-fee-schedule
# ---------------------------------------------------------------------------
def update_fee_schedule(conn, args):
    fs_id = getattr(args, "fee_schedule_id", None)
    if not fs_id:
        err("--fee-schedule-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_fee_schedule")).select(Field("id")).where(Field("id") == P()).get_sql(), (fs_id,)).fetchone():
        err(f"Fee schedule {fs_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "fee_schedule_name": "name", "description": "description",
        "effective_date": "effective_date", "expiration_date": "expiration_date",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    payer_type = getattr(args, "payer_type", None)
    if payer_type is not None:
        _validate_enum(payer_type, VALID_PAYER_TYPES, "health-payer-type")
        data["payer_type"] = payer_type
        changed.append("payer_type")

    fee_schedule_status = getattr(args, "fee_schedule_status", None)
    if fee_schedule_status is not None:
        _validate_enum(fee_schedule_status, VALID_FEE_SCHEDULE_STATUSES, "status")
        data["status"] = fee_schedule_status
        changed.append("status")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("healthclaw_fee_schedule", data, {"id": fs_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_fee_schedule", fs_id, "health-update-fee-schedule", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": fs_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 3. list-fee-schedules
# ---------------------------------------------------------------------------
def list_fee_schedules(conn, args):
    t = Table("healthclaw_fee_schedule")

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
# 4. add-fee-schedule-item
# ---------------------------------------------------------------------------
def add_fee_schedule_item(conn, args):
    fs_id = getattr(args, "fee_schedule_id", None)
    if not fs_id:
        err("--fee-schedule-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_fee_schedule")).select(Field("id")).where(Field("id") == P()).get_sql(), (fs_id,)).fetchone():
        err(f"Fee schedule {fs_id} not found")

    cpt_code = getattr(args, "cpt_code", None)
    if not cpt_code:
        err("--cpt-code is required")
    standard_charge = getattr(args, "standard_charge", None)
    if not standard_charge:
        err("--standard-charge is required")

    fsi_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_fee_schedule_item", {"id": P(), "fee_schedule_id": P(), "cpt_code": P(), "description": P(), "standard_charge": P(), "allowed_amount": P(), "unit_count": P(), "modifier": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        fsi_id, fs_id, cpt_code,
        getattr(args, "description", None),
        str(round_currency(to_decimal(standard_charge))),
        str(round_currency(to_decimal(getattr(args, "allowed_amount", None) or "0"))),
        int(getattr(args, "unit_count", None) or 1),
        getattr(args, "modifier", None),
        now, now,
    ))
    audit(conn, "healthclaw_fee_schedule_item", fsi_id, "health-add-fee-schedule-item", None)
    conn.commit()
    ok({"id": fsi_id, "fee_schedule_id": fs_id, "cpt_code": cpt_code})


# ---------------------------------------------------------------------------
# 5. list-fee-schedule-items
# ---------------------------------------------------------------------------
def list_fee_schedule_items(conn, args):
    t = Table("healthclaw_fee_schedule_item")

    q_count = Q.from_(t).select(fn.Count("*"))

    q_rows = Q.from_(t).select(t.star)

    params = []


    if getattr(args, "fee_schedule_id", None):

        q_count = q_count.where(t.fee_schedule_id == P())

        q_rows = q_rows.where(t.fee_schedule_id == P())

        params.append(args.fee_schedule_id)

    if getattr(args, "cpt_code", None):

        q_count = q_count.where(t.cpt_code == P())

        q_rows = q_rows.where(t.cpt_code == P())

        params.append(args.cpt_code)


    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.cpt_code, order=Order.asc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 6. add-charge
# ---------------------------------------------------------------------------
def add_charge(conn, args):
    _validate_company(conn, args.company_id)
    _validate_encounter(conn, args.encounter_id)
    _validate_patient(conn, args.patient_id)

    cpt_code = getattr(args, "cpt_code", None)
    if not cpt_code:
        err("--cpt-code is required")
    service_date = getattr(args, "service_date", None)
    if not service_date:
        err("--service-date is required")

    provider_id = getattr(args, "provider_id", None)
    if not provider_id:
        err("--provider-id is required")
    if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (provider_id,)).fetchone():
        err(f"Provider (employee) {provider_id} not found")

    # Optional FK checks
    procedure_id = getattr(args, "procedure_id", None)
    if procedure_id:
        if not conn.execute(Q.from_(Table("healthclaw_procedure")).select(Field("id")).where(Field("id") == P()).get_sql(), (procedure_id,)).fetchone():
            err(f"Procedure {procedure_id} not found")
    fee_schedule_id = getattr(args, "fee_schedule_id", None)
    if fee_schedule_id:
        if not conn.execute(Q.from_(Table("healthclaw_fee_schedule")).select(Field("id")).where(Field("id") == P()).get_sql(), (fee_schedule_id,)).fetchone():
            err(f"Fee schedule {fee_schedule_id} not found")

    charge_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_charge", company_id=args.company_id)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_charge", {"id": P(), "naming_series": P(), "encounter_id": P(), "patient_id": P(), "procedure_id": P(), "cpt_code": P(), "modifiers": P(), "diagnosis_ids": P(), "units": P(), "charge_amount": P(), "allowed_amount": P(), "fee_schedule_id": P(), "service_date": P(), "provider_id": P(), "place_of_service": P(), "charge_status": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        charge_id, naming, args.encounter_id, args.patient_id,
        procedure_id, cpt_code,
        getattr(args, "modifiers", None),
        getattr(args, "diagnosis_ids", None),
        int(getattr(args, "units", None) or 1),
        str(round_currency(to_decimal(getattr(args, "charge_amount", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "allowed_amount", None) or "0"))),
        fee_schedule_id, service_date, provider_id,
        getattr(args, "place_of_service", None) or "11",
        "unbilled",
        getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_charge", charge_id, "health-add-charge", args.company_id)
    conn.commit()
    ok({"id": charge_id, "naming_series": naming, "cpt_code": cpt_code, "status": "unbilled"})


# ---------------------------------------------------------------------------
# 7. list-charges
# ---------------------------------------------------------------------------
def list_charges(conn, args):
    t = Table("healthclaw_charge")

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

    if getattr(args, "status", None):

        q_count = q_count.where(t.charge_status == P())

        q_rows = q_rows.where(t.charge_status == P())

        params.append(args.status)

    if getattr(args, "company_id", None):

        q_count = q_count.where(t.company_id == P())

        q_rows = q_rows.where(t.company_id == P())

        params.append(args.company_id)


    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.service_date, order=Order.desc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 8. add-claim
# ---------------------------------------------------------------------------
def add_claim(conn, args):
    _validate_company(conn, args.company_id)
    _validate_patient(conn, args.patient_id)
    _validate_encounter(conn, args.encounter_id)

    insurance_id = getattr(args, "insurance_id", None)
    if not insurance_id:
        err("--insurance-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_patient_insurance")).select(Field("id")).where(Field("id") == P()).get_sql(), (insurance_id,)).fetchone():
        err(f"Insurance {insurance_id} not found")

    claim_date = getattr(args, "claim_date", None)
    if not claim_date:
        err("--claim-date is required")

    claim_type = getattr(args, "claim_type", None) or "professional"
    _validate_enum(claim_type, VALID_CLAIM_TYPES, "health-claim-type")

    # Optional FK checks
    billing_provider_id = getattr(args, "billing_provider_id", None)
    if billing_provider_id:
        if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (billing_provider_id,)).fetchone():
            err(f"Billing provider {billing_provider_id} not found")
    rendering_provider_id = getattr(args, "rendering_provider_id", None)
    if rendering_provider_id:
        if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (rendering_provider_id,)).fetchone():
            err(f"Rendering provider {rendering_provider_id} not found")
    prior_auth_id = getattr(args, "prior_auth_id", None)
    if prior_auth_id:
        if not conn.execute(Q.from_(Table("healthclaw_prior_auth")).select(Field("id")).where(Field("id") == P()).get_sql(), (prior_auth_id,)).fetchone():
            err(f"Prior auth {prior_auth_id} not found")

    claim_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_claim", company_id=args.company_id)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_claim", {"id": P(), "naming_series": P(), "patient_id": P(), "insurance_id": P(), "encounter_id": P(), "claim_date": P(), "total_charge": P(), "total_allowed": P(), "total_paid": P(), "patient_responsibility": P(), "adjustment_amount": P(), "billing_provider_id": P(), "rendering_provider_id": P(), "place_of_service": P(), "claim_type": P(), "filing_indicator": P(), "prior_auth_id": P(), "sales_invoice_id": P(), "claim_status": P(), "denial_reason": P(), "denial_category": P(), "denial_code": P(), "denial_date": P(), "appeal_deadline": P(), "appeal_submitted_date": P(), "appeal_method": P(), "appeal_reference": P(), "appeal_outcome": P(), "appeal_resolved_date": P(), "appeal_amount_recovered": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        claim_id, naming, args.patient_id, insurance_id, args.encounter_id,
        claim_date,
        str(round_currency(to_decimal(getattr(args, "total_charge", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "total_allowed", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "total_paid", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "patient_responsibility", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "adjustment_amount", None) or "0"))),
        billing_provider_id, rendering_provider_id,
        getattr(args, "place_of_service", None) or "11",
        claim_type,
        getattr(args, "filing_indicator", None),
        prior_auth_id,
        getattr(args, "sales_invoice_id", None),
        "draft",
        None, None, None, None, None, None, None, None, None, None, None,
        getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_claim", claim_id, "health-add-claim", args.company_id)
    conn.commit()
    ok({"id": claim_id, "naming_series": naming, "claim_date": claim_date, "claim_status": "draft"})


# ---------------------------------------------------------------------------
# 9. update-claim
# ---------------------------------------------------------------------------
def update_claim(conn, args):
    claim_id = getattr(args, "claim_id", None)
    if not claim_id:
        err("--claim-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_claim")).select(Field("id")).where(Field("id") == P()).get_sql(), (claim_id,)).fetchone():
        err(f"Claim {claim_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "claim_date": "claim_date",
        "place_of_service": "place_of_service",
        "filing_indicator": "filing_indicator",
        "denial_reason": "denial_reason",
        "appeal_deadline": "appeal_deadline",
        "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    claim_type = getattr(args, "claim_type", None)
    if claim_type is not None:
        _validate_enum(claim_type, VALID_CLAIM_TYPES, "health-claim-type")
        data["claim_type"] = claim_type
        changed.append("claim_type")

    claim_status = getattr(args, "claim_status", None)
    if claim_status is not None:
        _validate_enum(claim_status, VALID_CLAIM_STATUSES, "status")
        data["claim_status"] = claim_status
        changed.append("claim_status")

    # Money fields
    for mf in ("total_charge", "total_allowed", "total_paid", "patient_responsibility", "adjustment_amount"):
        val = getattr(args, mf, None)
        if val is not None:
            data[mf] = str(round_currency(to_decimal(val)))
            changed.append(mf)

    # Optional FK updates
    billing_provider_id = getattr(args, "billing_provider_id", None)
    if billing_provider_id is not None:
        if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (billing_provider_id,)).fetchone():
            err(f"Billing provider {billing_provider_id} not found")
        data["billing_provider_id"] = billing_provider_id
        changed.append("billing_provider_id")

    rendering_provider_id = getattr(args, "rendering_provider_id", None)
    if rendering_provider_id is not None:
        if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (rendering_provider_id,)).fetchone():
            err(f"Rendering provider {rendering_provider_id} not found")
        data["rendering_provider_id"] = rendering_provider_id
        changed.append("rendering_provider_id")

    prior_auth_id = getattr(args, "prior_auth_id", None)
    if prior_auth_id is not None:
        if not conn.execute(Q.from_(Table("healthclaw_prior_auth")).select(Field("id")).where(Field("id") == P()).get_sql(), (prior_auth_id,)).fetchone():
            err(f"Prior auth {prior_auth_id} not found")
        data["prior_auth_id"] = prior_auth_id
        changed.append("prior_auth_id")

    sales_invoice_id = getattr(args, "sales_invoice_id", None)
    if sales_invoice_id is not None:
        data["sales_invoice_id"] = sales_invoice_id
        changed.append("sales_invoice_id")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("healthclaw_claim", data, {"id": claim_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_claim", claim_id, "health-update-claim", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": claim_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 10. get-claim
# ---------------------------------------------------------------------------
def get_claim(conn, args):
    claim_id = getattr(args, "claim_id", None)
    if not claim_id:
        err("--claim-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_claim")).select(Table("healthclaw_claim").star).where(Field("id") == P()).get_sql(), (claim_id,)).fetchone()
    if not row:
        err(f"Claim {claim_id} not found")
    data = row_to_dict(row)

    # Enrich: patient name
    _pat_t = Table("healthclaw_patient")
    pat = conn.execute(Q.from_(_pat_t).select(_pat_t.full_name).where(_pat_t.id == P()).get_sql(), (data["patient_id"],)).fetchone()
    if pat:
        data["patient_name"] = pat[0]
    # Enrich: insurance payer name
    _ins_t = Table("healthclaw_patient_insurance")
    ins = conn.execute(Q.from_(_ins_t).select(_ins_t.payer_name).where(_ins_t.id == P()).get_sql(), (data["insurance_id"],)).fetchone()
    if ins:
        data["payer_name"] = ins[0]
    # Enrich: line count
    data["line_count"] = conn.execute(Q.from_(Table("healthclaw_claim_line")).select(fn.Count("*")).where(Field("claim_id") == P()).get_sql(), (claim_id,)).fetchone()[0]
    # Enrich: payment posting total (Python Decimal summation — never CAST AS REAL)
    _pp_t = Table("healthclaw_payment_posting")
    posting_rows = conn.execute(
        Q.from_(_pp_t).select(_pp_t.amount).where(_pp_t.claim_id == P()).get_sql(),
        (claim_id,)
    ).fetchall()
    posting_total = sum((to_decimal(r[0]) for r in posting_rows), Decimal("0"))
    data["total_payments_posted"] = str(round_currency(posting_total))
    ok(data)


# ---------------------------------------------------------------------------
# 11. list-claims
# ---------------------------------------------------------------------------
def list_claims(conn, args):
    t = Table("healthclaw_claim")

    q_count = Q.from_(t).select(fn.Count("*"))

    q_rows = Q.from_(t).select(t.star)

    params = []


    if getattr(args, "patient_id", None):

        q_count = q_count.where(t.patient_id == P())

        q_rows = q_rows.where(t.patient_id == P())

        params.append(args.patient_id)

    if getattr(args, "status", None):

        q_count = q_count.where(t.claim_status == P())

        q_rows = q_rows.where(t.claim_status == P())

        params.append(args.status)

    if getattr(args, "company_id", None):

        q_count = q_count.where(t.company_id == P())

        q_rows = q_rows.where(t.company_id == P())

        params.append(args.company_id)

    if getattr(args, "insurance_id", None):

        q_count = q_count.where(t.insurance_id == P())

        q_rows = q_rows.where(t.insurance_id == P())

        params.append(args.insurance_id)


    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.claim_date, order=Order.desc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# H3: NPI Luhn validation helper
# ---------------------------------------------------------------------------
def _validate_npi(npi):
    """Validate NPI using Luhn algorithm (10-digit)."""
    if not npi or len(npi) != 10 or not npi.isdigit():
        return False
    # NPI uses prefix 80840 for Luhn check
    prefixed = "80840" + npi
    total = 0
    for i, ch in enumerate(reversed(prefixed)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ---------------------------------------------------------------------------
# H3: scrub-claim (pre-submission validation)
# ---------------------------------------------------------------------------
def scrub_claim(conn, args):
    claim_id = getattr(args, "claim_id", None)
    if not claim_id:
        err("--claim-id is required")

    errors = []
    warnings = []

    # 1. Claim exists and is in 'draft' status
    row = conn.execute(
        Q.from_(Table("healthclaw_claim")).select(
            Table("healthclaw_claim").star
        ).where(Field("id") == P()).get_sql(),
        (claim_id,)
    ).fetchone()
    if not row:
        err(f"Claim {claim_id} not found")
    claim = row_to_dict(row)
    if claim["claim_status"] != "draft":
        errors.append(f"Claim status is '{claim['claim_status']}', must be 'draft'")

    # 2. Patient exists and has at least one active insurance
    patient_id = claim.get("patient_id")
    if patient_id:
        pat = conn.execute(
            Q.from_(Table("healthclaw_patient")).select(Field("id")).where(Field("id") == P()).get_sql(),
            (patient_id,)
        ).fetchone()
        if not pat:
            errors.append(f"Patient {patient_id} not found")
        else:
            ins_count = conn.execute(
                Q.from_(Table("healthclaw_patient_insurance")).select(fn.Count("*")).where(
                    (Field("patient_id") == P()) & (Field("status") == P())
                ).get_sql(),
                (patient_id, "active")
            ).fetchone()[0]
            if ins_count == 0:
                errors.append("Patient has no active insurance")
    else:
        errors.append("Claim has no patient_id")

    # 3. At least one claim line exists
    lines = conn.execute(
        Q.from_(Table("healthclaw_claim_line")).select(
            Table("healthclaw_claim_line").star
        ).where(Field("claim_id") == P()).get_sql(),
        (claim_id,)
    ).fetchall()
    if len(lines) == 0:
        errors.append("No claim lines found")

    # 4. Each claim line has a CPT code (procedure_code = cpt_code)
    for line in lines:
        ld = row_to_dict(line)
        if not ld.get("cpt_code"):
            errors.append(f"Claim line {ld['id']} missing CPT code")

    # 5. Each claim line has at least one diagnosis pointer (diagnosis_pointers)
    for line in lines:
        ld = row_to_dict(line)
        dp = ld.get("diagnosis_pointers")
        if not dp or dp.strip() == "":
            errors.append(f"Claim line {ld['id']} missing diagnosis pointer")

    # 6. NPI format check on rendering_provider
    rendering_provider_id = claim.get("rendering_provider_id")
    if rendering_provider_id:
        npi = None
        # Check if employee table has an npi column (SQLite treats missing columns as string literals)
        try:
            emp_cols = [r[1] for r in conn.execute("PRAGMA table_info(employee)").fetchall()]
            if "npi" in emp_cols:
                emp_row = conn.execute(
                    Q.from_(Table("employee")).select(Field("npi")).where(Field("id") == P()).get_sql(),
                    (rendering_provider_id,)
                ).fetchone()
                if emp_row and emp_row[0]:
                    npi = emp_row[0]
        except Exception:
            pass
        if npi:
            if not _validate_npi(npi):
                errors.append(f"Rendering provider NPI '{npi}' is invalid (Luhn check failed)")
        else:
            warnings.append("Rendering provider has no NPI on file")
    else:
        warnings.append("No rendering provider assigned to claim")

    # 7. No duplicate claim (same patient + payer + service_date + procedure_code)
    if lines:
        insurance_id = claim.get("insurance_id")
        for line in lines:
            ld = row_to_dict(line)
            cpt = ld.get("cpt_code")
            if cpt and insurance_id:
                # Get the charge's service_date
                charge_row = conn.execute(
                    Q.from_(Table("healthclaw_charge")).select(Field("service_date")).where(Field("id") == P()).get_sql(),
                    (ld["charge_id"],)
                ).fetchone()
                if charge_row:
                    svc_date = charge_row[0]
                    # Look for another claim (not this one) with same patient + insurance + a line with same cpt + same service_date charge
                    dup_claims = conn.execute(
                        Q.from_(Table("healthclaw_claim")).select(Field("id")).where(
                            (Field("patient_id") == P()) &
                            (Field("insurance_id") == P()) &
                            (Field("id") != P()) &
                            (Field("claim_status") != P())
                        ).get_sql(),
                        (patient_id, insurance_id, claim_id, "void")
                    ).fetchall()
                    for dc in dup_claims:
                        dup_line = conn.execute(
                            Q.from_(Table("healthclaw_claim_line")).select(Field("id")).where(
                                (Field("claim_id") == P()) & (Field("cpt_code") == P())
                            ).get_sql(),
                            (dc[0], cpt)
                        ).fetchone()
                        if dup_line:
                            # Verify the charge service_date matches
                            dup_charge = conn.execute(
                                Q.from_(Table("healthclaw_claim_line")).select(Field("charge_id")).where(Field("id") == P()).get_sql(),
                                (dup_line[0],)
                            ).fetchone()
                            if dup_charge:
                                dup_svc = conn.execute(
                                    Q.from_(Table("healthclaw_charge")).select(Field("service_date")).where(Field("id") == P()).get_sql(),
                                    (dup_charge[0],)
                                ).fetchone()
                                if dup_svc and dup_svc[0] == svc_date:
                                    warnings.append(f"Possible duplicate: claim {dc[0]} has same patient/payer/CPT {cpt}/service date {svc_date}")

    # 8. Timely filing check
    claim_date_str = claim.get("claim_date")
    insurance_id = claim.get("insurance_id")
    if claim_date_str and insurance_id and lines:
        # Get the earliest service_date from claim lines' charges
        earliest_svc = None
        for line in lines:
            ld = row_to_dict(line)
            charge_row = conn.execute(
                Q.from_(Table("healthclaw_charge")).select(Field("service_date")).where(Field("id") == P()).get_sql(),
                (ld["charge_id"],)
            ).fetchone()
            if charge_row and charge_row[0]:
                if earliest_svc is None or charge_row[0] < earliest_svc:
                    earliest_svc = charge_row[0]

        if earliest_svc:
            # Try to find the payer's timely_filing_days via insurance -> payer
            try:
                ins_row = conn.execute(
                    Q.from_(Table("healthclaw_patient_insurance")).select(Field("payer_name")).where(Field("id") == P()).get_sql(),
                    (insurance_id,)
                ).fetchone()
                if ins_row and ins_row[0]:
                    payer_row = conn.execute(
                        Q.from_(Table("healthclaw_payer")).select(Field("timely_filing_days")).where(
                            Field("name") == P()
                        ).get_sql(),
                        (ins_row[0],)
                    ).fetchone()
                    if payer_row and payer_row[0]:
                        from datetime import timedelta
                        svc_dt = datetime.strptime(earliest_svc[:10], "%Y-%m-%d")
                        now_dt = datetime.now(timezone.utc)
                        days_elapsed = (now_dt - svc_dt.replace(tzinfo=timezone.utc)).days
                        if days_elapsed > int(payer_row[0]):
                            errors.append(f"Timely filing exceeded: {days_elapsed} days since service (limit: {payer_row[0]} days)")
                        elif days_elapsed > int(payer_row[0]) * 0.9:
                            warnings.append(f"Timely filing warning: {days_elapsed}/{payer_row[0]} days elapsed")
            except Exception:
                pass  # healthclaw_payer table may not exist

    passed = len(errors) == 0
    ok({"pass": passed, "errors": errors, "warnings": warnings})


# ---------------------------------------------------------------------------
# 12. submit-claim
# ---------------------------------------------------------------------------
def _run_scrub(conn, claim_id):
    """Run scrub checks internally (no JSON output). Returns (passed, errors, warnings)."""
    errors = []
    warnings = []

    row = conn.execute(
        Q.from_(Table("healthclaw_claim")).select(
            Table("healthclaw_claim").star
        ).where(Field("id") == P()).get_sql(),
        (claim_id,)
    ).fetchone()
    if not row:
        return False, ["Claim not found"], []
    claim = row_to_dict(row)
    if claim["claim_status"] != "draft":
        errors.append(f"Claim status is '{claim['claim_status']}', must be 'draft'")

    patient_id = claim.get("patient_id")
    if patient_id:
        pat = conn.execute(
            Q.from_(Table("healthclaw_patient")).select(Field("id")).where(Field("id") == P()).get_sql(),
            (patient_id,)
        ).fetchone()
        if not pat:
            errors.append(f"Patient {patient_id} not found")
        else:
            ins_count = conn.execute(
                Q.from_(Table("healthclaw_patient_insurance")).select(fn.Count("*")).where(
                    (Field("patient_id") == P()) & (Field("status") == P())
                ).get_sql(),
                (patient_id, "active")
            ).fetchone()[0]
            if ins_count == 0:
                errors.append("Patient has no active insurance")
    else:
        errors.append("Claim has no patient_id")

    lines = conn.execute(
        Q.from_(Table("healthclaw_claim_line")).select(
            Table("healthclaw_claim_line").star
        ).where(Field("claim_id") == P()).get_sql(),
        (claim_id,)
    ).fetchall()
    if len(lines) == 0:
        errors.append("No claim lines found")

    for line in lines:
        ld = row_to_dict(line)
        if not ld.get("cpt_code"):
            errors.append(f"Claim line {ld['id']} missing CPT code")

    for line in lines:
        ld = row_to_dict(line)
        dp = ld.get("diagnosis_pointers")
        if not dp or dp.strip() == "":
            errors.append(f"Claim line {ld['id']} missing diagnosis pointer")

    rendering_provider_id = claim.get("rendering_provider_id")
    if rendering_provider_id:
        npi = None
        try:
            emp_cols = [r[1] for r in conn.execute("PRAGMA table_info(employee)").fetchall()]
            if "npi" in emp_cols:
                emp_row = conn.execute(
                    Q.from_(Table("employee")).select(Field("npi")).where(Field("id") == P()).get_sql(),
                    (rendering_provider_id,)
                ).fetchone()
                if emp_row and emp_row[0]:
                    npi = emp_row[0]
        except Exception:
            pass
        if npi:
            if not _validate_npi(npi):
                errors.append(f"Rendering provider NPI '{npi}' is invalid (Luhn check failed)")
        else:
            warnings.append("Rendering provider has no NPI on file")
    else:
        warnings.append("No rendering provider assigned to claim")

    return len(errors) == 0, errors, warnings


def submit_claim(conn, args):
    claim_id = getattr(args, "claim_id", None)
    if not claim_id:
        err("--claim-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_claim")).select(Field("claim_status")).where(Field("id") == P()).get_sql(), (claim_id,)).fetchone()
    if not row:
        err(f"Claim {claim_id} not found")
    if row[0] != "draft":
        err(f"Cannot submit claim with status '{row[0]}'. Must be 'draft'.")

    # Run scrub checks before submission
    passed, scrub_errors, scrub_warnings = _run_scrub(conn, claim_id)
    if not passed:
        err(f"Claim scrub failed: {'; '.join(scrub_errors)}")

    # Verify at least one claim line exists
    line_count = conn.execute(Q.from_(Table("healthclaw_claim_line")).select(fn.Count("*")).where(Field("claim_id") == P()).get_sql(), (claim_id,)).fetchone()[0]
    if line_count == 0:
        err("Cannot submit claim with no claim lines. Add at least one claim line first.")

    sql = update_row("healthclaw_claim",
        data={"claim_status": "submitted", "updated_at": LiteralValue("datetime('now')")},
        where={"id": P()})
    conn.execute(sql, (claim_id,))
    audit(conn, "healthclaw_claim", claim_id, "health-submit-claim", None)
    conn.commit()
    ok({"id": claim_id, "claim_status": "submitted", "line_count": line_count, "scrub_warnings": scrub_warnings})


# ---------------------------------------------------------------------------
# 13. add-claim-line
# ---------------------------------------------------------------------------
def add_claim_line(conn, args):
    claim_id = getattr(args, "claim_id", None)
    if not claim_id:
        err("--claim-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_claim")).select(Field("id")).where(Field("id") == P()).get_sql(), (claim_id,)).fetchone():
        err(f"Claim {claim_id} not found")

    charge_id = getattr(args, "charge_id", None)
    if not charge_id:
        err("--charge-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_charge")).select(Field("id")).where(Field("id") == P()).get_sql(), (charge_id,)).fetchone():
        err(f"Charge {charge_id} not found")

    cpt_code = getattr(args, "cpt_code", None)
    if not cpt_code:
        err("--cpt-code is required")

    cl_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_claim_line", {"id": P(), "claim_id": P(), "charge_id": P(), "line_number": P(), "cpt_code": P(), "modifiers": P(), "diagnosis_pointers": P(), "units": P(), "charge_amount": P(), "allowed_amount": P(), "paid_amount": P(), "adjustment_amount": P(), "patient_amount": P(), "denial_reason": P(), "remark_codes": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        cl_id, claim_id, charge_id,
        int(getattr(args, "line_number", None) or 1),
        cpt_code,
        getattr(args, "modifiers", None),
        getattr(args, "diagnosis_pointers", None),
        int(getattr(args, "units", None) or 1),
        str(round_currency(to_decimal(getattr(args, "charge_amount", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "allowed_amount", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "paid_amount", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "adjustment_amount", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "patient_amount", None) or "0"))),
        getattr(args, "denial_reason", None),
        getattr(args, "remark_codes", None),
        now, now,
    ))
    audit(conn, "healthclaw_claim_line", cl_id, "health-add-claim-line", None)
    conn.commit()
    ok({"id": cl_id, "claim_id": claim_id, "charge_id": charge_id, "cpt_code": cpt_code})


# ---------------------------------------------------------------------------
# 14. list-claim-lines
# ---------------------------------------------------------------------------
def list_claim_lines(conn, args):
    t = Table("healthclaw_claim_line")

    q_count = Q.from_(t).select(fn.Count("*"))

    q_rows = Q.from_(t).select(t.star)

    params = []


    if getattr(args, "claim_id", None):

        q_count = q_count.where(t.claim_id == P())

        q_rows = q_rows.where(t.claim_id == P())

        params.append(args.claim_id)

    if getattr(args, "charge_id", None):

        q_count = q_count.where(t.charge_id == P())

        q_rows = q_rows.where(t.charge_id == P())

        params.append(args.charge_id)


    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.line_number, order=Order.asc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 15. add-payment-posting
# ---------------------------------------------------------------------------
def add_payment_posting(conn, args):
    _validate_company(conn, args.company_id)
    _validate_patient(conn, args.patient_id)

    posting_type = getattr(args, "posting_type", None)
    if not posting_type:
        err("--posting-type is required")
    _validate_enum(posting_type, VALID_POSTING_TYPES, "health-posting-type")

    posting_date = getattr(args, "posting_date", None)
    if not posting_date:
        err("--posting-date is required")

    amount = getattr(args, "amount", None)
    if not amount:
        err("--amount is required")

    # Optional FK checks
    claim_id = getattr(args, "claim_id", None)
    if claim_id:
        if not conn.execute(Q.from_(Table("healthclaw_claim")).select(Field("id")).where(Field("id") == P()).get_sql(), (claim_id,)).fetchone():
            err(f"Claim {claim_id} not found")

    payment_entry_id = getattr(args, "payment_entry_id", None)
    if payment_entry_id:
        if not conn.execute(Q.from_(Table("payment_entry")).select(Field("id")).where(Field("id") == P()).get_sql(), (payment_entry_id,)).fetchone():
            err(f"Payment entry {payment_entry_id} not found")

    payment_method = getattr(args, "payment_method", None)
    _validate_enum(payment_method, VALID_PAYMENT_METHODS, "health-payment-method")

    pp_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_payment_posting", {"id": P(), "claim_id": P(), "patient_id": P(), "posting_type": P(), "posting_date": P(), "amount": P(), "check_number": P(), "payer_name": P(), "payment_method": P(), "payment_entry_id": P(), "eob_date": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        pp_id, claim_id, args.patient_id, posting_type, posting_date,
        str(round_currency(to_decimal(amount))),
        getattr(args, "check_number", None),
        getattr(args, "payer_name", None),
        payment_method,
        payment_entry_id,
        getattr(args, "eob_date", None),
        getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_payment_posting", pp_id, "health-add-payment-posting", args.company_id)
    conn.commit()
    ok({"id": pp_id, "posting_type": posting_type, "amount": str(round_currency(to_decimal(amount)))})


# ---------------------------------------------------------------------------
# 16. list-payment-postings
# ---------------------------------------------------------------------------
def list_payment_postings(conn, args):
    t = Table("healthclaw_payment_posting")

    q_count = Q.from_(t).select(fn.Count("*"))

    q_rows = Q.from_(t).select(t.star)

    params = []


    if getattr(args, "claim_id", None):

        q_count = q_count.where(t.claim_id == P())

        q_rows = q_rows.where(t.claim_id == P())

        params.append(args.claim_id)

    if getattr(args, "patient_id", None):

        q_count = q_count.where(t.patient_id == P())

        q_rows = q_rows.where(t.patient_id == P())

        params.append(args.patient_id)

    if getattr(args, "posting_type", None):

        q_count = q_count.where(t.posting_type == P())

        q_rows = q_rows.where(t.posting_type == P())

        params.append(args.posting_type)

    if getattr(args, "company_id", None):

        q_count = q_count.where(t.company_id == P())

        q_rows = q_rows.where(t.company_id == P())

        params.append(args.company_id)


    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.posting_date, order=Order.desc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# H5: Denial Management
# ---------------------------------------------------------------------------
VALID_DENIAL_CATEGORIES = ("CO", "PR", "OA", "PI")
VALID_APPEAL_METHODS = ("written", "phone", "online")
VALID_APPEAL_OUTCOMES = ("pending", "overturned", "upheld", "partial")


def record_denial(conn, args):
    claim_id = getattr(args, "claim_id", None)
    if not claim_id:
        err("--claim-id is required")
    row = conn.execute(
        Q.from_(Table("healthclaw_claim")).select(Field("claim_status")).where(Field("id") == P()).get_sql(),
        (claim_id,)
    ).fetchone()
    if not row:
        err(f"Claim {claim_id} not found")

    denial_category = getattr(args, "denial_category", None)
    if not denial_category:
        err("--denial-category is required")
    _validate_enum(denial_category, VALID_DENIAL_CATEGORIES, "denial-category")

    denial_code = getattr(args, "denial_code", None)
    if not denial_code:
        err("--denial-code is required")

    denial_reason = getattr(args, "denial_reason", None)
    denial_date = getattr(args, "denial_date", None) or _now_iso()[:10]

    data = {
        "claim_status": "denied",
        "denial_category": denial_category,
        "denial_code": denial_code,
        "denial_date": denial_date,
        "updated_at": LiteralValue("datetime('now')"),
    }
    if denial_reason:
        data["denial_reason"] = denial_reason

    sql, params = dynamic_update("healthclaw_claim", data, {"id": claim_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_claim", claim_id, "health-record-denial", None,
          {"denial_category": denial_category, "denial_code": denial_code})
    conn.commit()
    ok({"id": claim_id, "claim_status": "denied", "denial_category": denial_category,
        "denial_code": denial_code, "denial_date": denial_date})


def submit_appeal(conn, args):
    claim_id = getattr(args, "claim_id", None)
    if not claim_id:
        err("--claim-id is required")
    row = conn.execute(
        Q.from_(Table("healthclaw_claim")).select(Field("claim_status")).where(Field("id") == P()).get_sql(),
        (claim_id,)
    ).fetchone()
    if not row:
        err(f"Claim {claim_id} not found")
    if row[0] != "denied":
        err(f"Cannot appeal claim with status '{row[0]}'. Must be 'denied'.")

    appeal_method = getattr(args, "appeal_method", None)
    if appeal_method:
        _validate_enum(appeal_method, VALID_APPEAL_METHODS, "appeal-method")

    appeal_reference = getattr(args, "appeal_reference", None)
    notes = getattr(args, "notes", None)
    now = _now_iso()

    data = {
        "claim_status": "appealed",
        "appeal_submitted_date": now[:10],
        "appeal_outcome": "pending",
        "updated_at": LiteralValue("datetime('now')"),
    }
    if appeal_method:
        data["appeal_method"] = appeal_method
    if appeal_reference:
        data["appeal_reference"] = appeal_reference
    if notes:
        data["notes"] = notes

    sql, params = dynamic_update("healthclaw_claim", data, {"id": claim_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_claim", claim_id, "health-submit-appeal", None)
    conn.commit()
    ok({"id": claim_id, "claim_status": "appealed", "appeal_submitted_date": now[:10]})


def resolve_appeal(conn, args):
    claim_id = getattr(args, "claim_id", None)
    if not claim_id:
        err("--claim-id is required")
    row = conn.execute(
        Q.from_(Table("healthclaw_claim")).select(Field("claim_status"), Field("appeal_outcome")).where(Field("id") == P()).get_sql(),
        (claim_id,)
    ).fetchone()
    if not row:
        err(f"Claim {claim_id} not found")
    if row[0] != "appealed":
        err(f"Cannot resolve appeal for claim with status '{row[0]}'. Must be 'appealed'.")

    appeal_outcome = getattr(args, "appeal_outcome", None)
    if not appeal_outcome:
        err("--appeal-outcome is required")
    _validate_enum(appeal_outcome, ("overturned", "upheld", "partial"), "appeal-outcome")

    appeal_amount_recovered = getattr(args, "appeal_amount_recovered", None)
    now = _now_iso()

    # Determine new claim status based on outcome
    if appeal_outcome == "overturned":
        new_status = "accepted"
    elif appeal_outcome == "upheld":
        new_status = "denied"
    else:  # partial
        new_status = "partially_paid"

    data = {
        "claim_status": new_status,
        "appeal_outcome": appeal_outcome,
        "appeal_resolved_date": now[:10],
        "updated_at": LiteralValue("datetime('now')"),
    }
    if appeal_amount_recovered:
        data["appeal_amount_recovered"] = str(round_currency(to_decimal(appeal_amount_recovered)))

    sql, params = dynamic_update("healthclaw_claim", data, {"id": claim_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_claim", claim_id, "health-resolve-appeal", None,
          {"appeal_outcome": appeal_outcome})
    conn.commit()
    ok({"id": claim_id, "claim_status": new_status, "appeal_outcome": appeal_outcome,
        "appeal_resolved_date": now[:10]})


def list_denied_claims(conn, args):
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_claim")
    ins = Table("healthclaw_patient_insurance")

    q_count = Q.from_(t).select(fn.Count("*")).where(
        (t.company_id == P()) & (t.claim_status == P())
    )
    q_rows = Q.from_(t).left_join(ins).on(t.insurance_id == ins.id).select(
        t.star, ins.payer_name.as_("insurance_payer_name")
    ).where(
        (t.company_id == P()) & (t.claim_status == P())
    )
    params = [args.company_id, "denied"]

    payer_name = getattr(args, "payer_name", None)
    if payer_name:
        q_count = q_count.where(ins.payer_name == P())
        # Need to add join for count too
        q_count = Q.from_(t).left_join(ins).on(t.insurance_id == ins.id).select(fn.Count("*")).where(
            (t.company_id == P()) & (t.claim_status == P()) & (ins.payer_name == P())
        )
        params = [args.company_id, "denied", payer_name]

    denial_category = getattr(args, "denial_category", None)
    if denial_category:
        q_count = q_count.where(t.denial_category == P())
        q_rows = q_rows.where(t.denial_category == P())
        params.append(denial_category)

    date_from = getattr(args, "date_from", None)
    if date_from:
        q_count = q_count.where(t.denial_date >= P())
        q_rows = q_rows.where(t.denial_date >= P())
        params.append(date_from)

    date_to = getattr(args, "date_to", None)
    if date_to:
        q_count = q_count.where(t.denial_date <= P())
        q_rows = q_rows.where(t.denial_date <= P())
        params.append(date_to)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0
    q_rows = q_rows.orderby(t.denial_date, order=Order.desc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": limit, "offset": offset,
        "has_more": (offset + limit) < total,
    })


def denial_trend_report(conn, args):
    _validate_company(conn, args.company_id)

    months = int(getattr(args, "months", None) or 6)

    # Calculate cutoff date
    now_dt = datetime.now(timezone.utc)
    cutoff_year = now_dt.year
    cutoff_month = now_dt.month - months
    while cutoff_month <= 0:
        cutoff_month += 12
        cutoff_year -= 1
    cutoff_date = f"{cutoff_year:04d}-{cutoff_month:02d}-01"

    t = Table("healthclaw_claim")
    ins = Table("healthclaw_patient_insurance")

    rows = conn.execute(
        Q.from_(t).left_join(ins).on(t.insurance_id == ins.id).select(
            ins.payer_name, t.denial_code, t.denial_category, t.total_charge
        ).where(
            (t.company_id == P()) &
            (t.claim_status == P()) &
            (t.denial_date >= P())
        ).get_sql(),
        (args.company_id, "denied", cutoff_date)
    ).fetchall()

    # Group by payer + denial_code
    trends = {}
    for r in rows:
        payer = r[0] or "Unknown"
        code = r[1] or "Unknown"
        cat = r[2] or "Unknown"
        amount = to_decimal(r[3] or "0")
        key = f"{payer}|{code}"
        if key not in trends:
            trends[key] = {"payer_name": payer, "denial_code": code, "denial_category": cat, "count": 0, "total_amount": Decimal("0")}
        trends[key]["count"] += 1
        trends[key]["total_amount"] += amount

    result = sorted(trends.values(), key=lambda x: x["count"], reverse=True)
    for r in result:
        r["total_amount"] = str(round_currency(r["total_amount"]))

    ok({"report": "denial_trend", "months": months, "cutoff_date": cutoff_date,
        "trends": result, "total_denials": len(rows)})


def appeal_success_rate_report(conn, args):
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_claim")

    # Count appeals submitted (claims that have appeal_submitted_date)
    appeals_submitted = conn.execute(
        Q.from_(t).select(fn.Count("*")).where(
            (t.company_id == P()) & (t.appeal_submitted_date.isnotnull())
        ).get_sql(),
        (args.company_id,)
    ).fetchone()[0]

    # Count by outcome
    outcomes = {}
    for outcome in ("overturned", "upheld", "partial", "pending"):
        count = conn.execute(
            Q.from_(t).select(fn.Count("*")).where(
                (t.company_id == P()) & (t.appeal_outcome == P())
            ).get_sql(),
            (args.company_id, outcome)
        ).fetchone()[0]
        outcomes[outcome] = count

    # Calculate amounts recovered
    recovered_rows = conn.execute(
        Q.from_(t).select(t.appeal_amount_recovered).where(
            (t.company_id == P()) & (t.appeal_amount_recovered.isnotnull())
        ).get_sql(),
        (args.company_id,)
    ).fetchall()
    total_recovered = sum((to_decimal(r[0]) for r in recovered_rows if r[0]), Decimal("0"))

    resolved = outcomes["overturned"] + outcomes["upheld"] + outcomes["partial"]
    success_rate = "0.00"
    if resolved > 0:
        rate = Decimal(str(outcomes["overturned"] + outcomes["partial"])) / Decimal(str(resolved)) * Decimal("100")
        success_rate = str(rate.quantize(Decimal("0.01")))

    ok({
        "report": "appeal_success_rate",
        "appeals_submitted": appeals_submitted,
        "outcomes": outcomes,
        "resolved": resolved,
        "success_rate_pct": success_rate,
        "total_amount_recovered": str(round_currency(total_recovered)),
    })


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-add-fee-schedule": add_fee_schedule,
    "health-update-fee-schedule": update_fee_schedule,
    "health-list-fee-schedules": list_fee_schedules,
    "health-add-fee-schedule-item": add_fee_schedule_item,
    "health-list-fee-schedule-items": list_fee_schedule_items,
    "health-add-charge": add_charge,
    "health-list-charges": list_charges,
    "health-add-claim": add_claim,
    "health-update-claim": update_claim,
    "health-get-claim": get_claim,
    "health-list-claims": list_claims,
    "health-scrub-claim": scrub_claim,
    "health-submit-claim": submit_claim,
    "health-add-claim-line": add_claim_line,
    "health-list-claim-lines": list_claim_lines,
    "health-add-payment-posting": add_payment_posting,
    "health-list-payment-postings": list_payment_postings,
    "health-record-denial": record_denial,
    "health-submit-appeal": submit_appeal,
    "health-resolve-appeal": resolve_appeal,
    "health-list-denied-claims": list_denied_claims,
    "health-denial-trend-report": denial_trend_report,
    "health-appeal-success-rate-report": appeal_success_rate_report,
}
