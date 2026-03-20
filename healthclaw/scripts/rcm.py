"""HealthClaw — RCM (Revenue Cycle Management) domain module

Actions for payer registry and eligibility verification (2 tables, 10 actions).
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

    # Register HealthClaw naming prefixes (RCM domain)
    ENTITY_PREFIXES.setdefault("healthclaw_payer", "PAYER-")
    ENTITY_PREFIXES.setdefault("healthclaw_eligibility_check", "ELIG-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_PAYER_TYPES = ("commercial", "medicare", "medicaid", "tricare", "workers_comp", "self_pay", "other")
VALID_PAYER_STATUSES = ("active", "inactive")
VALID_SUBMISSION_METHODS = ("electronic", "paper", "portal")
VALID_ERA_ENROLLMENTS = ("enrolled", "not_enrolled", "pending")
VALID_CHECK_METHODS = ("manual", "electronic", "phone")
VALID_COVERAGE_STATUSES = ("active", "inactive", "termed", "pending", "unknown")


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
# 1. add-payer
# ---------------------------------------------------------------------------
def add_payer(conn, args):
    _validate_company(conn, args.company_id)

    name = getattr(args, "name", None)
    if not name:
        err("--name is required")

    payer_type = getattr(args, "payer_type", None)
    if not payer_type:
        err("--payer-type is required")
    _validate_enum(payer_type, VALID_PAYER_TYPES, "payer-type")

    submission_method = getattr(args, "submission_method", None)
    _validate_enum(submission_method, VALID_SUBMISSION_METHODS, "submission-method")

    era_enrollment = getattr(args, "era_enrollment", None)
    _validate_enum(era_enrollment, VALID_ERA_ENROLLMENTS, "era-enrollment")

    payer_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_payer", {
        "id": P(), "company_id": P(), "name": P(), "payer_type": P(),
        "edi_payer_id": P(), "electronic_filing_id": P(),
        "address": P(), "city": P(), "state": P(), "zip": P(), "phone": P(),
        "claims_address": P(), "claims_city": P(), "claims_state": P(), "claims_zip": P(),
        "submission_method": P(), "timely_filing_days": P(), "era_enrollment": P(),
        "default_fee_schedule_id": P(), "notes": P(), "status": P(),
        "created_at": P(), "updated_at": P(),
    })

    conn.execute(sql, (
        payer_id, args.company_id, name, payer_type,
        getattr(args, "edi_payer_id", None),
        getattr(args, "electronic_filing_id", None),
        getattr(args, "address", None),
        getattr(args, "city", None),
        getattr(args, "state", None),
        getattr(args, "zip_code", None),
        getattr(args, "phone", None),
        getattr(args, "claims_address", None),
        getattr(args, "claims_city", None),
        getattr(args, "claims_state", None),
        getattr(args, "claims_zip", None),
        submission_method or "electronic",
        int(getattr(args, "timely_filing_days", None) or 365),
        era_enrollment or "not_enrolled",
        getattr(args, "default_fee_schedule_id", None),
        getattr(args, "notes", None),
        "active",
        now, now,
    ))
    audit(conn, "healthclaw_payer", payer_id, "health-add-payer", args.company_id)
    conn.commit()
    ok({"id": payer_id, "name": name, "payer_type": payer_type, "status": "active"})


# ---------------------------------------------------------------------------
# 2. update-payer
# ---------------------------------------------------------------------------
def update_payer(conn, args):
    payer_id = getattr(args, "payer_id", None)
    if not payer_id:
        err("--payer-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_payer")).select(Field("id")).where(Field("id") == P()).get_sql(), (payer_id,)).fetchone():
        err(f"Payer {payer_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "name": "name",
        "edi_payer_id": "edi_payer_id",
        "electronic_filing_id": "electronic_filing_id",
        "address": "address",
        "city": "city",
        "state": "state",
        "zip_code": "zip",
        "phone": "phone",
        "claims_address": "claims_address",
        "claims_city": "claims_city",
        "claims_state": "claims_state",
        "claims_zip": "claims_zip",
        "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    payer_type = getattr(args, "payer_type", None)
    if payer_type is not None:
        _validate_enum(payer_type, VALID_PAYER_TYPES, "payer-type")
        data["payer_type"] = payer_type
        changed.append("payer_type")

    submission_method = getattr(args, "submission_method", None)
    if submission_method is not None:
        _validate_enum(submission_method, VALID_SUBMISSION_METHODS, "submission-method")
        data["submission_method"] = submission_method
        changed.append("submission_method")

    era_enrollment = getattr(args, "era_enrollment", None)
    if era_enrollment is not None:
        _validate_enum(era_enrollment, VALID_ERA_ENROLLMENTS, "era-enrollment")
        data["era_enrollment"] = era_enrollment
        changed.append("era_enrollment")

    payer_status = getattr(args, "payer_status", None)
    if payer_status is not None:
        _validate_enum(payer_status, VALID_PAYER_STATUSES, "payer-status")
        data["status"] = payer_status
        changed.append("status")

    timely_filing_days = getattr(args, "timely_filing_days", None)
    if timely_filing_days is not None:
        data["timely_filing_days"] = int(timely_filing_days)
        changed.append("timely_filing_days")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("healthclaw_payer", data, {"id": payer_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_payer", payer_id, "health-update-payer", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": payer_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 3. get-payer
# ---------------------------------------------------------------------------
def get_payer(conn, args):
    payer_id = getattr(args, "payer_id", None)
    if not payer_id:
        err("--payer-id is required")
    row = conn.execute(
        Q.from_(Table("healthclaw_payer")).select(Table("healthclaw_payer").star).where(Field("id") == P()).get_sql(),
        (payer_id,)
    ).fetchone()
    if not row:
        err(f"Payer {payer_id} not found")
    data = row_to_dict(row)
    # Preserve payer status before ok() overwrites it with "ok"
    data["payer_status"] = data.get("status", "active")
    ok(data)


# ---------------------------------------------------------------------------
# 4. list-payers
# ---------------------------------------------------------------------------
def list_payers(conn, args):
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_payer")

    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    q_count = q_count.where(t.company_id == P())
    q_rows = q_rows.where(t.company_id == P())
    params.append(args.company_id)

    if getattr(args, "payer_type", None):
        q_count = q_count.where(t.payer_type == P())
        q_rows = q_rows.where(t.payer_type == P())
        params.append(args.payer_type)

    if getattr(args, "status", None):
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(args.status)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.name, order=Order.asc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 5. link-payer-fee-schedule
# ---------------------------------------------------------------------------
def link_payer_fee_schedule(conn, args):
    payer_id = getattr(args, "payer_id", None)
    if not payer_id:
        err("--payer-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_payer")).select(Field("id")).where(Field("id") == P()).get_sql(), (payer_id,)).fetchone():
        err(f"Payer {payer_id} not found")

    fee_schedule_id = getattr(args, "fee_schedule_id", None)
    if not fee_schedule_id:
        err("--fee-schedule-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_fee_schedule")).select(Field("id")).where(Field("id") == P()).get_sql(), (fee_schedule_id,)).fetchone():
        err(f"Fee schedule {fee_schedule_id} not found")

    data = {
        "default_fee_schedule_id": fee_schedule_id,
        "updated_at": LiteralValue("datetime('now')"),
    }
    sql, params = dynamic_update("healthclaw_payer", data, {"id": payer_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_payer", payer_id, "health-link-payer-fee-schedule", None, {"fee_schedule_id": fee_schedule_id})
    conn.commit()
    ok({"id": payer_id, "default_fee_schedule_id": fee_schedule_id})


# ---------------------------------------------------------------------------
# 6. payer-performance-report
# ---------------------------------------------------------------------------
def payer_performance_report(conn, args):
    _validate_company(conn, args.company_id)

    # Get all payers for this company
    payer_t = Table("healthclaw_payer")
    payers = conn.execute(
        Q.from_(payer_t).select(payer_t.id, payer_t.name, payer_t.payer_type)
        .where(payer_t.company_id == P())
        .where(payer_t.status == P())
        .orderby(payer_t.name, order=Order.asc)
        .get_sql(),
        (args.company_id, "active")
    ).fetchall()

    claim_t = Table("healthclaw_claim")
    ins_t = Table("healthclaw_patient_insurance")

    report = []
    for payer_row in payers:
        pid = payer_row[0]
        pname = payer_row[1]
        ptype = payer_row[2]

        # Find all insurance records linked to this payer_name, then count claims
        # Claims are linked to insurance_id. We match via payer_name on insurance records.
        # But we also check claims whose insurance references match payer by payer_name.
        ins_rows = conn.execute(
            Q.from_(ins_t).select(ins_t.id)
            .where(ins_t.payer_name == P())
            .get_sql(),
            (pname,)
        ).fetchall()
        ins_ids = [r[0] for r in ins_rows]

        total_claims = 0
        total_submitted = 0
        total_paid = 0
        total_denied = 0
        total_charged = Decimal("0")
        total_paid_amount = Decimal("0")

        if ins_ids:
            for ins_id in ins_ids:
                claims = conn.execute(
                    Q.from_(claim_t).select(claim_t.claim_status, claim_t.total_charge, claim_t.total_paid)
                    .where(claim_t.insurance_id == P())
                    .where(claim_t.company_id == P())
                    .get_sql(),
                    (ins_id, args.company_id)
                ).fetchall()
                for c in claims:
                    total_claims += 1
                    status = c[0]
                    if status == "submitted":
                        total_submitted += 1
                    elif status == "paid":
                        total_paid += 1
                    elif status == "denied":
                        total_denied += 1
                    total_charged += to_decimal(c[1])
                    total_paid_amount += to_decimal(c[2])

        report.append({
            "payer_id": pid,
            "payer_name": pname,
            "payer_type": ptype,
            "total_claims": total_claims,
            "submitted": total_submitted,
            "paid": total_paid,
            "denied": total_denied,
            "total_charged": str(round_currency(total_charged)),
            "total_paid": str(round_currency(total_paid_amount)),
        })

    ok({"company_id": args.company_id, "payers": report, "payer_count": len(report)})


# ---------------------------------------------------------------------------
# 7. record-eligibility-check
# ---------------------------------------------------------------------------
def record_eligibility_check(conn, args):
    _validate_patient(conn, args.patient_id)

    patient_insurance_id = getattr(args, "patient_insurance_id", None)
    if not patient_insurance_id:
        err("--patient-insurance-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_patient_insurance")).select(Field("id")).where(Field("id") == P()).get_sql(), (patient_insurance_id,)).fetchone():
        err(f"Patient insurance {patient_insurance_id} not found")

    coverage_status = getattr(args, "coverage_status", None)
    if not coverage_status:
        err("--coverage-status is required")
    _validate_enum(coverage_status, VALID_COVERAGE_STATUSES, "coverage-status")

    check_method = getattr(args, "check_method", None)
    _validate_enum(check_method, VALID_CHECK_METHODS, "check-method")

    # Optional FK: payer
    payer_id = getattr(args, "payer_id", None)
    if payer_id:
        if not conn.execute(Q.from_(Table("healthclaw_payer")).select(Field("id")).where(Field("id") == P()).get_sql(), (payer_id,)).fetchone():
            err(f"Payer {payer_id} not found")

    check_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_eligibility_check", {
        "id": P(), "patient_id": P(), "patient_insurance_id": P(), "payer_id": P(),
        "check_date": P(), "check_method": P(), "coverage_status": P(),
        "copay": P(), "deductible": P(), "deductible_met": P(),
        "coinsurance_pct": P(), "out_of_pocket_max": P(), "oop_met": P(),
        "plan_begin_date": P(), "plan_end_date": P(),
        "in_network": P(), "prior_auth_required": P(),
        "notes": P(), "checked_by": P(), "created_at": P(),
    })

    # Money fields stored as TEXT Decimal
    copay = getattr(args, "copay", None)
    deductible = getattr(args, "deductible", None)
    deductible_met = getattr(args, "deductible_met", None)
    coinsurance_pct = getattr(args, "coinsurance_pct", None)
    oop_max = getattr(args, "out_of_pocket_max", None)
    oop_met = getattr(args, "oop_met", None)

    conn.execute(sql, (
        check_id, args.patient_id, patient_insurance_id, payer_id,
        now[:10],  # check_date = today
        check_method or "manual",
        coverage_status,
        str(round_currency(to_decimal(copay))) if copay else None,
        str(round_currency(to_decimal(deductible))) if deductible else None,
        str(round_currency(to_decimal(deductible_met))) if deductible_met else None,
        coinsurance_pct,
        str(round_currency(to_decimal(oop_max))) if oop_max else None,
        str(round_currency(to_decimal(oop_met))) if oop_met else None,
        getattr(args, "plan_begin_date", None),
        getattr(args, "plan_end_date", None),
        int(getattr(args, "in_network", None) or 1),
        int(getattr(args, "prior_auth_required", None) or 0),
        getattr(args, "notes", None),
        getattr(args, "checked_by", None),
        now,
    ))
    audit(conn, "healthclaw_eligibility_check", check_id, "health-record-eligibility-check", None)
    conn.commit()
    ok({"id": check_id, "patient_id": args.patient_id, "coverage_status": coverage_status})


# ---------------------------------------------------------------------------
# 8. get-latest-eligibility
# ---------------------------------------------------------------------------
def get_latest_eligibility(conn, args):
    _validate_patient(conn, args.patient_id)

    patient_insurance_id = getattr(args, "patient_insurance_id", None)
    if not patient_insurance_id:
        err("--patient-insurance-id is required")

    t = Table("healthclaw_eligibility_check")
    row = conn.execute(
        Q.from_(t).select(t.star)
        .where(t.patient_id == P())
        .where(t.patient_insurance_id == P())
        .orderby(t.created_at, order=Order.desc)
        .limit(1)
        .get_sql(),
        (args.patient_id, patient_insurance_id)
    ).fetchone()
    if not row:
        err(f"No eligibility checks found for patient {args.patient_id} insurance {patient_insurance_id}")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# 9. list-eligibility-checks
# ---------------------------------------------------------------------------
def list_eligibility_checks(conn, args):
    _validate_patient(conn, args.patient_id)

    t = Table("healthclaw_eligibility_check")

    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    q_count = q_count.where(t.patient_id == P())
    q_rows = q_rows.where(t.patient_id == P())
    params.append(args.patient_id)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 10. check-eligibility-status
# ---------------------------------------------------------------------------
def check_eligibility_status(conn, args):
    _validate_patient(conn, args.patient_id)

    # Get all active insurance records for this patient
    ins_t = Table("healthclaw_patient_insurance")
    insurances = conn.execute(
        Q.from_(ins_t).select(ins_t.id, ins_t.insurance_type, ins_t.payer_name, ins_t.member_id, ins_t.status)
        .where(ins_t.patient_id == P())
        .where(ins_t.status == P())
        .orderby(ins_t.insurance_type, order=Order.asc)
        .get_sql(),
        (args.patient_id, "active")
    ).fetchall()

    elig_t = Table("healthclaw_eligibility_check")
    results = []
    for ins_row in insurances:
        ins_id = ins_row[0]
        ins_type = ins_row[1]
        payer_name = ins_row[2]
        member_id = ins_row[3]

        # Get latest eligibility check for this insurance
        latest = conn.execute(
            Q.from_(elig_t).select(elig_t.star)
            .where(elig_t.patient_insurance_id == P())
            .orderby(elig_t.created_at, order=Order.desc)
            .limit(1)
            .get_sql(),
            (ins_id,)
        ).fetchone()

        entry = {
            "insurance_id": ins_id,
            "insurance_type": ins_type,
            "payer_name": payer_name,
            "member_id": member_id,
            "latest_check": row_to_dict(latest) if latest else None,
            "coverage_status": latest["coverage_status"] if latest else "unknown",
            "last_checked": latest["created_at"] if latest else None,
        }
        results.append(entry)

    ok({
        "patient_id": args.patient_id,
        "insurance_count": len(results),
        "insurances": results,
    })


# ---------------------------------------------------------------------------
# 11. import-era-file
# ---------------------------------------------------------------------------
VALID_ERA_STATUSES = ("received", "processing", "posted", "partial", "error")
VALID_ERA_MATCH_STATUSES = ("matched", "unmatched", "partial", "denied")


def import_era_file(conn, args):
    _validate_company(conn, args.company_id)

    received_date = getattr(args, "received_date", None)
    if not received_date:
        err("--received-date is required")

    check_number = getattr(args, "check_number", None)
    if not check_number:
        err("--check-number is required")

    check_amount = getattr(args, "check_amount", None)
    if not check_amount:
        err("--check-amount is required")

    claims_data_raw = getattr(args, "claims_data", None)
    if not claims_data_raw:
        err("--claims-data is required (JSON array)")

    try:
        claims_data = json.loads(claims_data_raw) if isinstance(claims_data_raw, str) else claims_data_raw
    except (json.JSONDecodeError, TypeError):
        err("--claims-data must be valid JSON array")

    if not isinstance(claims_data, list) or len(claims_data) == 0:
        err("--claims-data must be a non-empty JSON array")

    # Optional FK: payer
    payer_id = getattr(args, "payer_id", None)
    if payer_id:
        if not conn.execute(Q.from_(Table("healthclaw_payer")).select(Field("id")).where(Field("id") == P()).get_sql(), (payer_id,)).fetchone():
            err(f"Payer {payer_id} not found")

    era_file_id = str(uuid.uuid4())
    now = _now_iso()

    sql, _ = insert_row("healthclaw_era_file", {
        "id": P(), "company_id": P(), "file_name": P(), "payer_id": P(),
        "received_date": P(), "check_number": P(), "check_amount": P(),
        "eft_trace": P(), "claim_count": P(), "matched_count": P(),
        "posted_amount": P(), "status": P(), "notes": P(), "created_at": P(),
    })

    claim_count = len(claims_data)
    matched_count = 0

    # Insert ERA file header
    conn.execute(sql, (
        era_file_id, args.company_id,
        getattr(args, "file_name", None),
        payer_id,
        received_date, check_number,
        str(round_currency(to_decimal(check_amount))),
        getattr(args, "eft_trace", None),
        claim_count, 0,  # matched_count updated below
        "0",  # posted_amount starts at 0
        "received",
        getattr(args, "notes", None),
        now,
    ))

    # Process each claim detail
    detail_ids = []
    claim_t = Table("healthclaw_claim")

    for cd in claims_data:
        detail_id = str(uuid.uuid4())
        claim_number = cd.get("claim_number")
        patient_name = cd.get("patient_name")

        # Try to match claim_number against healthclaw_claim.naming_series
        matched_claim_id = None
        matched_patient_id = None
        match_status = "unmatched"

        if claim_number:
            match_row = conn.execute(
                Q.from_(claim_t).select(claim_t.id, claim_t.patient_id)
                .where(claim_t.naming_series == P())
                .get_sql(),
                (claim_number,)
            ).fetchone()
            if match_row:
                matched_claim_id = match_row[0]
                matched_patient_id = match_row[1]
                match_status = "matched"
                matched_count += 1

        detail_sql, _ = insert_row("healthclaw_era_claim_detail", {
            "id": P(), "era_file_id": P(), "claim_id": P(),
            "patient_name": P(), "patient_id": P(), "claim_number": P(),
            "service_date": P(), "billed_amount": P(), "allowed_amount": P(),
            "paid_amount": P(), "patient_responsibility": P(),
            "adjustment_amount": P(), "adjustment_codes": P(),
            "remark_codes": P(), "match_status": P(), "created_at": P(),
        })

        conn.execute(detail_sql, (
            detail_id, era_file_id, matched_claim_id,
            patient_name, matched_patient_id, claim_number,
            cd.get("service_date"),
            str(round_currency(to_decimal(cd.get("billed_amount", "0")))),
            str(round_currency(to_decimal(cd.get("allowed_amount", "0")))),
            str(round_currency(to_decimal(cd.get("paid_amount", "0")))),
            str(round_currency(to_decimal(cd.get("patient_responsibility", "0")))),
            str(round_currency(to_decimal(cd.get("adjustment_amount", "0")))),
            cd.get("adjustment_codes"),
            cd.get("remark_codes"),
            match_status,
            now,
        ))
        detail_ids.append({"id": detail_id, "match_status": match_status, "claim_number": claim_number})

    # Update matched_count on the ERA file header
    if matched_count > 0:
        data = {"matched_count": matched_count}
        sql_upd, params_upd = dynamic_update("healthclaw_era_file", data, {"id": era_file_id})
        conn.execute(sql_upd, params_upd)

    audit(conn, "healthclaw_era_file", era_file_id, "health-import-era-file", args.company_id)
    conn.commit()
    ok({
        "id": era_file_id,
        "claim_count": claim_count,
        "matched_count": matched_count,
        "check_amount": str(round_currency(to_decimal(check_amount))),
        "details": detail_ids,
    })


# ---------------------------------------------------------------------------
# 12. list-era-files
# ---------------------------------------------------------------------------
def list_era_files(conn, args):
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_era_file")

    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    q_count = q_count.where(t.company_id == P())
    q_rows = q_rows.where(t.company_id == P())
    params.append(args.company_id)

    if getattr(args, "status", None):
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(args.status)

    if getattr(args, "date_from", None):
        q_count = q_count.where(t.received_date >= P())
        q_rows = q_rows.where(t.received_date >= P())
        params.append(args.date_from)

    if getattr(args, "date_to", None):
        q_count = q_count.where(t.received_date <= P())
        q_rows = q_rows.where(t.received_date <= P())
        params.append(args.date_to)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.received_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 13. get-era-file-details
# ---------------------------------------------------------------------------
def get_era_file_details(conn, args):
    era_file_id = getattr(args, "era_file_id", None)
    if not era_file_id:
        err("--era-file-id is required")

    t = Table("healthclaw_era_file")
    row = conn.execute(
        Q.from_(t).select(t.star).where(t.id == P()).get_sql(),
        (era_file_id,)
    ).fetchone()
    if not row:
        err(f"ERA file {era_file_id} not found")

    header = row_to_dict(row)

    # Get all claim details
    dt = Table("healthclaw_era_claim_detail")
    detail_rows = conn.execute(
        Q.from_(dt).select(dt.star).where(dt.era_file_id == P())
        .orderby(dt.created_at, order=Order.asc)
        .get_sql(),
        (era_file_id,)
    ).fetchall()

    header["claim_details"] = [row_to_dict(r) for r in detail_rows]
    ok(header)


# ---------------------------------------------------------------------------
# 14. auto-post-era
# ---------------------------------------------------------------------------
def auto_post_era(conn, args):
    era_file_id = getattr(args, "era_file_id", None)
    if not era_file_id:
        err("--era-file-id is required")

    era_t = Table("healthclaw_era_file")
    era_row = conn.execute(
        Q.from_(era_t).select(era_t.star).where(era_t.id == P()).get_sql(),
        (era_file_id,)
    ).fetchone()
    if not era_row:
        err(f"ERA file {era_file_id} not found")
    era_data = row_to_dict(era_row)

    if era_data["status"] == "posted":
        err("ERA file already fully posted")

    company_id = era_data["company_id"]

    # Get all matched, un-posted claim details
    dt = Table("healthclaw_era_claim_detail")
    details = conn.execute(
        Q.from_(dt).select(dt.star)
        .where(dt.era_file_id == P())
        .where(dt.match_status == P())
        .where(dt.auto_posted == P())
        .get_sql(),
        (era_file_id, "matched", 0)
    ).fetchall()

    if not details:
        err("No matched, un-posted claims found in this ERA file")

    posted_count = 0
    total_posted = Decimal("0")
    now = _now_iso()
    claim_t = Table("healthclaw_claim")
    pp_t = Table("healthclaw_payment_posting")

    for detail_row in details:
        d = row_to_dict(detail_row)
        claim_id = d["claim_id"]
        paid_amount = to_decimal(d["paid_amount"])

        if not claim_id:
            continue

        # Create payment_posting record
        pp_id = str(uuid.uuid4())
        pp_sql, _ = insert_row("healthclaw_payment_posting", {
            "id": P(), "claim_id": P(), "patient_id": P(),
            "posting_type": P(), "posting_date": P(), "amount": P(),
            "check_number": P(), "payer_name": P(), "payment_method": P(),
            "payment_entry_id": P(), "eob_date": P(), "notes": P(),
            "company_id": P(), "created_at": P(), "updated_at": P(),
        })
        conn.execute(pp_sql, (
            pp_id, claim_id, d.get("patient_id"),
            "insurance_payment", now[:10],
            str(round_currency(paid_amount)),
            era_data.get("check_number"),
            None,  # payer_name
            "check",  # payment_method
            None,  # payment_entry_id
            None,  # eob_date
            f"Auto-posted from ERA file {era_file_id}",
            company_id, now, now,
        ))

        # Update claim status based on amounts
        claim_row = conn.execute(
            Q.from_(claim_t).select(claim_t.total_charge, claim_t.total_paid)
            .where(claim_t.id == P()).get_sql(),
            (claim_id,)
        ).fetchone()

        if claim_row:
            existing_paid = to_decimal(claim_row[1])
            total_charge = to_decimal(claim_row[0])
            new_total_paid = existing_paid + paid_amount

            new_status = "partially_paid"
            if new_total_paid >= total_charge and total_charge > Decimal("0"):
                new_status = "paid"

            upd_data = {
                "total_paid": str(round_currency(new_total_paid)),
                "claim_status": new_status,
                "updated_at": LiteralValue("datetime('now')"),
            }
            upd_sql, upd_params = dynamic_update("healthclaw_claim", upd_data, {"id": claim_id})
            conn.execute(upd_sql, upd_params)

        # Mark detail as auto_posted
        detail_upd = {"auto_posted": 1}
        detail_sql, detail_params = dynamic_update("healthclaw_era_claim_detail", detail_upd, {"id": d["id"]})
        conn.execute(detail_sql, detail_params)

        posted_count += 1
        total_posted += paid_amount

    # Update ERA file totals
    existing_posted = to_decimal(era_data.get("posted_amount", "0"))
    new_posted_total = existing_posted + total_posted
    existing_matched = int(era_data.get("matched_count", 0))
    total_claims = int(era_data.get("claim_count", 0))

    new_era_status = "partial"
    if posted_count >= existing_matched and existing_matched > 0:
        new_era_status = "posted"

    era_upd = {
        "posted_amount": str(round_currency(new_posted_total)),
        "status": new_era_status,
        "posted_at": now,
        "posted_by": getattr(args, "posted_by", None) or "auto",
    }
    era_sql, era_params = dynamic_update("healthclaw_era_file", era_upd, {"id": era_file_id})
    conn.execute(era_sql, era_params)

    audit(conn, "healthclaw_era_file", era_file_id, "health-auto-post-era", company_id)
    conn.commit()
    ok({
        "era_file_id": era_file_id,
        "posted_count": posted_count,
        "total_posted": str(round_currency(total_posted)),
        "era_status": new_era_status,
    })


# ---------------------------------------------------------------------------
# 15. era-reconciliation-report
# ---------------------------------------------------------------------------
def era_reconciliation_report(conn, args):
    _validate_company(conn, args.company_id)

    era_t = Table("healthclaw_era_file")
    dt = Table("healthclaw_era_claim_detail")

    # Build ERA file filter
    q_eras = Q.from_(era_t).select(era_t.star).where(era_t.company_id == P())
    era_params = [args.company_id]

    if getattr(args, "date_from", None):
        q_eras = q_eras.where(era_t.received_date >= P())
        era_params.append(args.date_from)

    if getattr(args, "date_to", None):
        q_eras = q_eras.where(era_t.received_date <= P())
        era_params.append(args.date_to)

    era_rows = conn.execute(q_eras.get_sql(), era_params).fetchall()

    total_files = len(era_rows)
    total_claims = 0
    total_matched = 0
    total_unmatched = 0
    total_posted = Decimal("0")
    total_pending = Decimal("0")

    for era_row in era_rows:
        era = row_to_dict(era_row)
        era_id = era["id"]

        # Get all details for this ERA file
        details = conn.execute(
            Q.from_(dt).select(dt.match_status, dt.paid_amount, dt.auto_posted)
            .where(dt.era_file_id == P())
            .get_sql(),
            (era_id,)
        ).fetchall()

        for d in details:
            total_claims += 1
            match_status = d[0]
            paid = to_decimal(d[1])
            auto_posted = d[2]

            if match_status == "matched":
                total_matched += 1
            else:
                total_unmatched += 1

            if auto_posted:
                total_posted += paid
            else:
                total_pending += paid

    ok({
        "company_id": args.company_id,
        "total_files": total_files,
        "total_claims": total_claims,
        "total_matched": total_matched,
        "total_unmatched": total_unmatched,
        "total_posted": str(round_currency(total_posted)),
        "total_pending": str(round_currency(total_pending)),
    })


# ===========================================================================
# H20: Payer Enrollment
# ===========================================================================
VALID_ENROLLMENT_STATUSES = ("pending", "active", "inactive", "terminated")


def add_payer_enrollment(conn, args):
    """Enroll a provider with a payer."""
    _validate_company(conn, args.company_id)

    provider_id = getattr(args, "provider_id", None)
    if not provider_id:
        err("--provider-id is required")
    if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (provider_id,)).fetchone():
        err(f"Provider (employee) {provider_id} not found")

    payer_id = getattr(args, "payer_id", None)
    if not payer_id:
        err("--payer-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_payer")).select(Field("id")).where(Field("id") == P()).get_sql(), (payer_id,)).fetchone():
        err(f"Payer {payer_id} not found")

    enrollment_status = getattr(args, "enrollment_status", None) or "pending"
    _validate_enum(enrollment_status, VALID_ENROLLMENT_STATUSES, "enrollment-status")

    enroll_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_payer_enrollment", {
        "id": P(), "provider_id": P(), "payer_id": P(),
        "enrollment_status": P(), "effective_date": P(),
        "termination_date": P(), "revalidation_date": P(),
        "provider_number": P(), "group_npi": P(), "notes": P(),
        "company_id": P(), "created_at": P(), "updated_at": P(),
    })
    conn.execute(sql, (
        enroll_id, provider_id, payer_id, enrollment_status,
        getattr(args, "effective_date", None),
        getattr(args, "termination_date", None),
        getattr(args, "revalidation_date", None),
        getattr(args, "provider_number", None),
        getattr(args, "group_npi", None),
        getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_payer_enrollment", enroll_id, "health-add-payer-enrollment", args.company_id)
    conn.commit()
    ok({"id": enroll_id, "provider_id": provider_id, "payer_id": payer_id, "enrollment_status": enrollment_status})


def list_payer_enrollments(conn, args):
    """List payer enrollments for a provider or payer."""
    t = Table("healthclaw_payer_enrollment")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P()); q_rows = q_rows.where(t.company_id == P()); params.append(args.company_id)
    if getattr(args, "provider_id", None):
        q_count = q_count.where(t.provider_id == P()); q_rows = q_rows.where(t.provider_id == P()); params.append(args.provider_id)
    if getattr(args, "payer_id", None):
        q_count = q_count.where(t.payer_id == P()); q_rows = q_rows.where(t.payer_id == P()); params.append(args.payer_id)
    if getattr(args, "enrollment_status", None):
        q_count = q_count.where(t.enrollment_status == P()); q_rows = q_rows.where(t.enrollment_status == P()); params.append(args.enrollment_status)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


def check_enrollment_revalidation(conn, args):
    """Check for payer enrollments needing revalidation within N days."""
    _validate_company(conn, args.company_id)

    from datetime import timedelta as _td
    days = int(getattr(args, "days", None) or 90)
    cutoff = (datetime.now(timezone.utc) + _td(days=days)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    t = Table("healthclaw_payer_enrollment")
    q = (Q.from_(t).select(t.star)
         .where(t.company_id == P())
         .where(t.enrollment_status == P())
         .where(t.revalidation_date.isnotnull())
         .where(t.revalidation_date <= P())
         .orderby(t.revalidation_date, order=Order.asc))

    rows = conn.execute(q.get_sql(), (args.company_id, "active", cutoff)).fetchall()

    due = []
    overdue = []
    for r in rows:
        data = row_to_dict(r)
        reval_date = data.get("revalidation_date", "")
        entry = {
            "id": data["id"],
            "provider_id": data["provider_id"],
            "payer_id": data["payer_id"],
            "provider_number": data.get("provider_number"),
            "revalidation_date": reval_date,
        }
        if reval_date < today:
            overdue.append(entry)
        else:
            due.append(entry)

    ok({
        "company_id": args.company_id,
        "check_window_days": days,
        "cutoff_date": cutoff,
        "due_count": len(due),
        "overdue_count": len(overdue),
        "due": due,
        "overdue": overdue,
    })


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-add-payer": add_payer,
    "health-update-payer": update_payer,
    "health-get-payer": get_payer,
    "health-list-payers": list_payers,
    "health-link-payer-fee-schedule": link_payer_fee_schedule,
    "health-payer-performance-report": payer_performance_report,
    "health-record-eligibility-check": record_eligibility_check,
    "health-get-latest-eligibility": get_latest_eligibility,
    "health-list-eligibility-checks": list_eligibility_checks,
    "health-check-eligibility-status": check_eligibility_status,
    "health-import-era-file": import_era_file,
    "health-list-era-files": list_era_files,
    "health-get-era-file-details": get_era_file_details,
    "health-auto-post-era": auto_post_era,
    "health-era-reconciliation-report": era_reconciliation_report,
    # H20: Payer Enrollment
    "health-add-payer-enrollment": add_payer_enrollment,
    "health-list-payer-enrollments": list_payer_enrollments,
    "health-check-enrollment-revalidation": check_enrollment_revalidation,
}
