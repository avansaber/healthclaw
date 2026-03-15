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
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row

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

    updates, params, changed = [], [], []
    for arg_name, col_name in {
        "fee_schedule_name": "name", "description": "description",
        "effective_date": "effective_date", "expiration_date": "expiration_date",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            updates.append(f"{col_name} = ?")
            params.append(val)
            changed.append(col_name)

    payer_type = getattr(args, "payer_type", None)
    if payer_type is not None:
        _validate_enum(payer_type, VALID_PAYER_TYPES, "health-payer-type")
        updates.append("payer_type = ?")
        params.append(payer_type)
        changed.append("payer_type")

    fee_schedule_status = getattr(args, "fee_schedule_status", None)
    if fee_schedule_status is not None:
        _validate_enum(fee_schedule_status, VALID_FEE_SCHEDULE_STATUSES, "status")
        updates.append("status = ?")
        params.append(fee_schedule_status)
        changed.append("status")

    if not updates:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(fs_id)
    conn.execute(f"UPDATE healthclaw_fee_schedule SET {', '.join(updates)} WHERE id = ?", params)
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
    sql, _ = insert_row("healthclaw_claim", {"id": P(), "naming_series": P(), "patient_id": P(), "insurance_id": P(), "encounter_id": P(), "claim_date": P(), "total_charge": P(), "total_allowed": P(), "total_paid": P(), "patient_responsibility": P(), "adjustment_amount": P(), "billing_provider_id": P(), "rendering_provider_id": P(), "place_of_service": P(), "claim_type": P(), "filing_indicator": P(), "prior_auth_id": P(), "sales_invoice_id": P(), "claim_status": P(), "denial_reason": P(), "appeal_deadline": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})

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
        None, None,
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

    updates, params, changed = [], [], []
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
            updates.append(f"{col_name} = ?")
            params.append(val)
            changed.append(col_name)

    claim_type = getattr(args, "claim_type", None)
    if claim_type is not None:
        _validate_enum(claim_type, VALID_CLAIM_TYPES, "health-claim-type")
        updates.append("claim_type = ?")
        params.append(claim_type)
        changed.append("claim_type")

    claim_status = getattr(args, "claim_status", None)
    if claim_status is not None:
        _validate_enum(claim_status, VALID_CLAIM_STATUSES, "status")
        updates.append("claim_status = ?")
        params.append(claim_status)
        changed.append("claim_status")

    # Money fields
    for mf in ("total_charge", "total_allowed", "total_paid", "patient_responsibility", "adjustment_amount"):
        val = getattr(args, mf, None)
        if val is not None:
            updates.append(f"{mf} = ?")
            params.append(str(round_currency(to_decimal(val))))
            changed.append(mf)

    # Optional FK updates
    billing_provider_id = getattr(args, "billing_provider_id", None)
    if billing_provider_id is not None:
        if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (billing_provider_id,)).fetchone():
            err(f"Billing provider {billing_provider_id} not found")
        updates.append("billing_provider_id = ?")
        params.append(billing_provider_id)
        changed.append("billing_provider_id")

    rendering_provider_id = getattr(args, "rendering_provider_id", None)
    if rendering_provider_id is not None:
        if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (rendering_provider_id,)).fetchone():
            err(f"Rendering provider {rendering_provider_id} not found")
        updates.append("rendering_provider_id = ?")
        params.append(rendering_provider_id)
        changed.append("rendering_provider_id")

    prior_auth_id = getattr(args, "prior_auth_id", None)
    if prior_auth_id is not None:
        if not conn.execute(Q.from_(Table("healthclaw_prior_auth")).select(Field("id")).where(Field("id") == P()).get_sql(), (prior_auth_id,)).fetchone():
            err(f"Prior auth {prior_auth_id} not found")
        updates.append("prior_auth_id = ?")
        params.append(prior_auth_id)
        changed.append("prior_auth_id")

    sales_invoice_id = getattr(args, "sales_invoice_id", None)
    if sales_invoice_id is not None:
        updates.append("sales_invoice_id = ?")
        params.append(sales_invoice_id)
        changed.append("sales_invoice_id")

    if not updates:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(claim_id)
    conn.execute(f"UPDATE healthclaw_claim SET {', '.join(updates)} WHERE id = ?", params)
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
    pat = conn.execute("SELECT full_name FROM healthclaw_patient WHERE id = ?", (data["patient_id"],)).fetchone()
    if pat:
        data["patient_name"] = pat[0]
    # Enrich: insurance payer name
    ins = conn.execute("SELECT payer_name FROM healthclaw_patient_insurance WHERE id = ?", (data["insurance_id"],)).fetchone()
    if ins:
        data["payer_name"] = ins[0]
    # Enrich: line count
    data["line_count"] = conn.execute(Q.from_(Table("healthclaw_claim_line")).select(fn.Count("*")).where(Field("claim_id") == P()).get_sql(), (claim_id,)).fetchone()[0]
    # Enrich: payment posting total (Python Decimal summation — never CAST AS REAL)
    posting_rows = conn.execute(
        "SELECT amount FROM healthclaw_payment_posting WHERE claim_id = ?",
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
# 12. submit-claim
# ---------------------------------------------------------------------------
def submit_claim(conn, args):
    claim_id = getattr(args, "claim_id", None)
    if not claim_id:
        err("--claim-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_claim")).select(Field("claim_status")).where(Field("id") == P()).get_sql(), (claim_id,)).fetchone()
    if not row:
        err(f"Claim {claim_id} not found")
    if row[0] != "draft":
        err(f"Cannot submit claim with status '{row[0]}'. Must be 'draft'.")

    # Verify at least one claim line exists
    line_count = conn.execute(Q.from_(Table("healthclaw_claim_line")).select(fn.Count("*")).where(Field("claim_id") == P()).get_sql(), (claim_id,)).fetchone()[0]
    if line_count == 0:
        err("Cannot submit claim with no claim lines. Add at least one claim line first.")

    conn.execute(
        "UPDATE healthclaw_claim SET claim_status = 'submitted', updated_at = datetime('now') WHERE id = ?",
        (claim_id,)
    )
    audit(conn, "healthclaw_claim", claim_id, "health-submit-claim", None)
    conn.commit()
    ok({"id": claim_id, "claim_status": "submitted", "line_count": line_count})


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
    "health-submit-claim": submit_claim,
    "health-add-claim-line": add_claim_line,
    "health-list-claim-lines": list_claim_lines,
    "health-add-payment-posting": add_payment_posting,
    "health-list-payment-postings": list_payment_postings,
}
