"""HealthClaw — Compliance domain module

Actions for HIPAA PHI audit, No Surprises Act Good Faith Estimates,
and CMS MIPS Quality Measures (4 tables, 11 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

try:
    import importlib.util
    if importlib.util.find_spec("erpclaw_lib") is None:
        sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Field, LiteralValue, Order, P, Q, Table, dynamic_update, fn, insert_row, now as sql_now, update_row

    # Register HealthClaw naming prefixes (compliance domain)
    ENTITY_PREFIXES.setdefault("healthclaw_good_faith_estimate", "GFE-")
    ENTITY_PREFIXES.setdefault("healthclaw_quality_measure", "QM-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_ACCESS_TYPES = ("view", "edit", "print", "export", "delete")
VALID_DATA_CATEGORIES = ("demographics", "clinical", "billing", "insurance",
                         "medications", "lab_results", "imaging", "notes", "all")
VALID_GFE_STATUSES = ("draft", "provided", "expired", "superseded")
VALID_MEASURE_CATEGORIES = ("quality", "improvement_activities",
                            "promoting_interoperability", "cost")
VALID_MEASURE_TYPES = ("process", "outcome", "structure", "efficiency")
VALID_MEASURE_RESULT_STATUSES = ("in_progress", "calculated", "submitted", "accepted")


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


# ===========================================================================
# H9: PHI Access Audit (HIPAA 45 C.F.R. 164.312(b))
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. log-phi-access
# ---------------------------------------------------------------------------
def log_phi_access(conn, args):
    patient_id = getattr(args, "patient_id", None)
    _validate_patient(conn, patient_id)

    access_type = getattr(args, "access_type", None)
    if not access_type:
        err("--access-type is required")
    _validate_enum(access_type, VALID_ACCESS_TYPES, "access-type")

    data_category = getattr(args, "data_category", None)
    if not data_category:
        err("--data-category is required")
    _validate_enum(data_category, VALID_DATA_CATEGORIES, "data-category")

    break_the_glass = int(getattr(args, "break_the_glass", None) or 0)
    access_reason = getattr(args, "access_reason", None)

    if break_the_glass == 1 and not access_reason:
        err("--access-reason is required when --break-the-glass is 1")

    log_id = str(uuid.uuid4())
    now = _now_iso()

    sql, _ = insert_row("healthclaw_phi_access_log", {
        "id": P(), "user_id": P(), "patient_id": P(),
        "access_type": P(), "data_category": P(),
        "action_name": P(), "resource_id": P(),
        "ip_address": P(), "user_agent": P(),
        "access_reason": P(), "break_the_glass": P(),
        "created_at": P(),
    })

    conn.execute(sql, (
        log_id,
        getattr(args, "user_id", None),
        patient_id,
        access_type,
        data_category,
        getattr(args, "action_name", None),
        getattr(args, "resource_id", None),
        getattr(args, "ip_address", None),
        getattr(args, "user_agent", None),
        access_reason,
        break_the_glass,
        now,
    ))
    conn.commit()
    ok({
        "id": log_id,
        "patient_id": patient_id,
        "access_type": access_type,
        "data_category": data_category,
        "break_the_glass": break_the_glass,
    })


# ---------------------------------------------------------------------------
# 2. phi-access-report
# ---------------------------------------------------------------------------
def phi_access_report(conn, args):
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_phi_access_log")

    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    # Filter by patient if specified
    patient_id = getattr(args, "patient_id", None)
    if patient_id:
        q_count = q_count.where(t.patient_id == P())
        q_rows = q_rows.where(t.patient_id == P())
        params.append(patient_id)

    # Filter by user if specified
    user_id = getattr(args, "user_id", None)
    if user_id:
        q_count = q_count.where(t.user_id == P())
        q_rows = q_rows.where(t.user_id == P())
        params.append(user_id)

    # Date filters
    date_from = getattr(args, "date_from", None)
    if date_from:
        q_count = q_count.where(t.created_at >= P())
        q_rows = q_rows.where(t.created_at >= P())
        params.append(date_from)

    date_to = getattr(args, "date_to", None)
    if date_to:
        q_count = q_count.where(t.created_at <= P())
        q_rows = q_rows.where(t.created_at <= P())
        params.append(date_to)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total,
        "limit": args.limit,
        "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 3. phi-access-anomaly-check
# ---------------------------------------------------------------------------
def phi_access_anomaly_check(conn, args):
    _validate_company(conn, args.company_id)

    days = int(getattr(args, "days", None) or 30)
    now = _now_iso()

    # Calculate cutoff date
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    t = Table("healthclaw_phi_access_log")
    anomalies = []

    # 1. Users who accessed >50 unique patients in the period
    all_logs = conn.execute(
        Q.from_(t).select(t.user_id, t.patient_id, t.created_at, t.access_type, t.break_the_glass)
        .where(t.created_at >= P())
        .get_sql(),
        (cutoff,)
    ).fetchall()

    # Build user -> unique patients map
    user_patients = {}
    for row in all_logs:
        uid = row[0]
        pid = row[1]
        if uid:
            user_patients.setdefault(uid, set()).add(pid)

    for uid, patients in user_patients.items():
        if len(patients) > 50:
            anomalies.append({
                "type": "high_volume_access",
                "severity": "warning",
                "user_id": uid,
                "unique_patients": len(patients),
                "message": f"User {uid} accessed {len(patients)} unique patients in {days} days",
            })

    # 2. Access outside business hours (before 6am or after 10pm)
    for row in all_logs:
        created_at = row[2]
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                hour = dt.hour
                if hour < 6 or hour >= 22:
                    anomalies.append({
                        "type": "after_hours_access",
                        "severity": "info",
                        "user_id": row[0],
                        "patient_id": row[1],
                        "access_time": created_at,
                        "message": f"Access at {created_at} (outside 6am-10pm)",
                    })
            except (ValueError, AttributeError):
                pass

    # 3. Break-the-glass accesses
    for row in all_logs:
        btg = row[4]
        if btg and int(btg) == 1:
            anomalies.append({
                "type": "break_the_glass",
                "severity": "critical",
                "user_id": row[0],
                "patient_id": row[1],
                "access_time": row[2],
                "message": f"Break-the-glass access by user {row[0]} on patient {row[1]}",
            })

    # 4. Bulk export operations
    for row in all_logs:
        access_type = row[3]
        if access_type == "export":
            anomalies.append({
                "type": "bulk_export",
                "severity": "warning",
                "user_id": row[0],
                "patient_id": row[1],
                "access_time": row[2],
                "message": f"Export operation by user {row[0]} on patient {row[1]}",
            })

    ok({
        "company_id": args.company_id,
        "period_days": days,
        "cutoff_date": cutoff,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    })


# ===========================================================================
# H10: Good Faith Estimate (No Surprises Act 2022)
# ===========================================================================

# ---------------------------------------------------------------------------
# 4. generate-good-faith-estimate
# ---------------------------------------------------------------------------
def generate_good_faith_estimate(conn, args):
    _validate_company(conn, args.company_id)
    _validate_patient(conn, args.patient_id)

    procedure_codes_raw = getattr(args, "procedure_codes", None)
    if not procedure_codes_raw:
        err("--procedure-codes is required (JSON array of CPT codes)")

    try:
        procedure_codes = json.loads(procedure_codes_raw) if isinstance(procedure_codes_raw, str) else procedure_codes_raw
    except (json.JSONDecodeError, TypeError):
        err("--procedure-codes must be valid JSON array")

    if not isinstance(procedure_codes, list) or len(procedure_codes) == 0:
        err("--procedure-codes must be a non-empty JSON array")

    provider_id = getattr(args, "provider_id", None)
    payer_id = getattr(args, "payer_id", None)
    diagnosis_codes_raw = getattr(args, "diagnosis_codes", None)

    diagnosis_codes = None
    if diagnosis_codes_raw:
        try:
            diagnosis_codes = json.loads(diagnosis_codes_raw) if isinstance(diagnosis_codes_raw, str) else diagnosis_codes_raw
        except (json.JSONDecodeError, TypeError):
            err("--diagnosis-codes must be valid JSON array")

    # Look up fee schedule items for each CPT code
    fsi_t = Table("healthclaw_fee_schedule_item")
    fs_t = Table("healthclaw_fee_schedule")

    items = []
    total_estimate = Decimal("0")

    # If payer specified, try to use payer's fee schedule
    payer_fee_schedule_id = None
    if payer_id:
        payer_t = Table("healthclaw_payer")
        payer_row = conn.execute(
            Q.from_(payer_t).select(payer_t.default_fee_schedule_id)
            .where(payer_t.id == P())
            .get_sql(),
            (payer_id,)
        ).fetchone()
        if payer_row and payer_row[0]:
            payer_fee_schedule_id = payer_row[0]

    for cpt_code in procedure_codes:
        # Try to find fee schedule item
        # First try payer fee schedule, then any active fee schedule for this company
        fee_row = None

        if payer_fee_schedule_id:
            fee_row = conn.execute(
                Q.from_(fsi_t).select(fsi_t.standard_charge, fsi_t.allowed_amount, fsi_t.description)
                .where(fsi_t.fee_schedule_id == P())
                .where(fsi_t.cpt_code == P())
                .get_sql(),
                (payer_fee_schedule_id, cpt_code)
            ).fetchone()

        if not fee_row:
            # Try any active fee schedule for this company
            fee_row = conn.execute(
                Q.from_(fsi_t)
                .join(fs_t).on(fsi_t.fee_schedule_id == fs_t.id)
                .select(fsi_t.standard_charge, fsi_t.allowed_amount, fsi_t.description)
                .where(fs_t.company_id == P())
                .where(fs_t.status == P())
                .where(fsi_t.cpt_code == P())
                .limit(1)
                .get_sql(),
                (args.company_id, "active", cpt_code)
            ).fetchone()

        if fee_row:
            charge = to_decimal(fee_row[0])
            allowed = to_decimal(fee_row[1]) if fee_row[1] else charge
            description = fee_row[2] or cpt_code
        else:
            # No fee schedule found — use zero and flag
            charge = Decimal("0")
            allowed = Decimal("0")
            description = cpt_code

        item = {
            "cpt_code": cpt_code,
            "description": description,
            "standard_charge": str(round_currency(charge)),
            "allowed_amount": str(round_currency(allowed)),
        }
        items.append(item)
        total_estimate += charge

    # Calculate patient responsibility
    estimated_insurance = Decimal("0")
    insurance_applied = 0
    if payer_id and payer_fee_schedule_id:
        insurance_applied = 1
        # Use allowed amounts as insurance payment estimate
        for item in items:
            estimated_insurance += to_decimal(item["allowed_amount"])

    patient_responsibility = total_estimate - estimated_insurance
    if patient_responsibility < Decimal("0"):
        patient_responsibility = Decimal("0")

    gfe_id = str(uuid.uuid4())
    now = _now_iso()
    estimate_date = now[:10]

    # Valid for 30 days
    from datetime import timedelta
    valid_until = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    sql, _ = insert_row("healthclaw_good_faith_estimate", {
        "id": P(), "company_id": P(), "patient_id": P(), "provider_id": P(),
        "estimate_date": P(), "procedure_codes": P(), "diagnosis_codes": P(),
        "items": P(), "total_estimate": P(), "facility_fee": P(), "provider_fee": P(),
        "insurance_applied": P(), "payer_id": P(),
        "estimated_insurance_payment": P(), "estimated_patient_responsibility": P(),
        "valid_until": P(), "status": P(), "notes": P(),
        "created_at": P(), "updated_at": P(),
    })

    conn.execute(sql, (
        gfe_id, args.company_id, args.patient_id, provider_id,
        estimate_date,
        json.dumps(procedure_codes),
        json.dumps(diagnosis_codes) if diagnosis_codes else None,
        json.dumps(items),
        str(round_currency(total_estimate)),
        "0",  # facility_fee
        "0",  # provider_fee
        insurance_applied,
        payer_id,
        str(round_currency(estimated_insurance)),
        str(round_currency(patient_responsibility)),
        valid_until,
        "draft",
        getattr(args, "notes", None),
        now, now,
    ))
    audit(conn, "healthclaw_good_faith_estimate", gfe_id, "health-generate-good-faith-estimate", args.company_id)
    conn.commit()
    ok({
        "id": gfe_id,
        "patient_id": args.patient_id,
        "estimate_date": estimate_date,
        "total_estimate": str(round_currency(total_estimate)),
        "estimated_insurance_payment": str(round_currency(estimated_insurance)),
        "estimated_patient_responsibility": str(round_currency(patient_responsibility)),
        "insurance_applied": insurance_applied,
        "items": items,
        "valid_until": valid_until,
        "gfe_status": "draft",
    })


# ---------------------------------------------------------------------------
# 5. list-good-faith-estimates
# ---------------------------------------------------------------------------
def list_good_faith_estimates(conn, args):
    patient_id = getattr(args, "patient_id", None)
    _validate_patient(conn, patient_id)

    t = Table("healthclaw_good_faith_estimate")

    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    q_count = q_count.where(t.patient_id == P())
    q_rows = q_rows.where(t.patient_id == P())
    params.append(patient_id)

    status = getattr(args, "status", None)
    if status:
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(status)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total,
        "limit": args.limit,
        "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 6. provide-good-faith-estimate
# ---------------------------------------------------------------------------
def provide_good_faith_estimate(conn, args):
    estimate_id = getattr(args, "estimate_id", None)
    if not estimate_id:
        err("--estimate-id is required")

    t = Table("healthclaw_good_faith_estimate")
    row = conn.execute(
        Q.from_(t).select(t.id, t.status).where(t.id == P()).get_sql(),
        (estimate_id,)
    ).fetchone()
    if not row:
        err(f"Good faith estimate {estimate_id} not found")

    if row[1] == "provided":
        err("Estimate has already been provided")

    now = _now_iso()
    data = {
        "status": "provided",
        "provided_at": now,
        "updated_at": sql_now(),
    }
    sql, params = dynamic_update("healthclaw_good_faith_estimate", data, {"id": estimate_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_good_faith_estimate", estimate_id, "health-provide-good-faith-estimate", None)
    conn.commit()
    ok({"id": estimate_id, "gfe_status": "provided", "provided_at": now})


# ===========================================================================
# H11: MIPS Quality Measures (CMS Merit-based Incentive Payment System)
# ===========================================================================

# ---------------------------------------------------------------------------
# 7. add-quality-measure
# ---------------------------------------------------------------------------
def add_quality_measure(conn, args):
    _validate_company(conn, args.company_id)

    measure_id = getattr(args, "measure_id", None)
    if not measure_id:
        err("--measure-id is required")

    name = getattr(args, "name", None)
    if not name:
        err("--name is required")

    category = getattr(args, "category", None)
    if not category:
        err("--category is required")
    _validate_enum(category, VALID_MEASURE_CATEGORIES, "category")

    measure_type = getattr(args, "measure_type", None)
    _validate_enum(measure_type, VALID_MEASURE_TYPES, "measure-type")

    qm_id = str(uuid.uuid4())
    now = _now_iso()

    sql, _ = insert_row("healthclaw_quality_measure", {
        "id": P(), "company_id": P(), "measure_id": P(), "name": P(),
        "category": P(), "description": P(),
        "numerator_criteria": P(), "denominator_criteria": P(), "exclusion_criteria": P(),
        "measure_type": P(), "reporting_period": P(), "benchmark": P(),
        "status": P(), "created_at": P(), "updated_at": P(),
    })

    conn.execute(sql, (
        qm_id, args.company_id, measure_id, name,
        category,
        getattr(args, "description", None),
        getattr(args, "numerator_criteria", None),
        getattr(args, "denominator_criteria", None),
        getattr(args, "exclusion_criteria", None),
        measure_type or "process",
        getattr(args, "reporting_period", None),
        getattr(args, "benchmark", None),
        "active",
        now, now,
    ))
    audit(conn, "healthclaw_quality_measure", qm_id, "health-add-quality-measure", args.company_id)
    conn.commit()
    ok({
        "id": qm_id,
        "measure_id": measure_id,
        "name": name,
        "category": category,
        "measure_status": "active",
    })


# ---------------------------------------------------------------------------
# 8. list-quality-measures
# ---------------------------------------------------------------------------
def list_quality_measures(conn, args):
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_quality_measure")

    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    q_count = q_count.where(t.company_id == P())
    q_rows = q_rows.where(t.company_id == P())
    params.append(args.company_id)

    category = getattr(args, "category", None)
    if category:
        q_count = q_count.where(t.category == P())
        q_rows = q_rows.where(t.category == P())
        params.append(category)

    status = getattr(args, "status", None)
    if status:
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(status)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.measure_id, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total,
        "limit": args.limit,
        "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 9. calculate-measure-result
# ---------------------------------------------------------------------------
def calculate_measure_result(conn, args):
    measure_id_fk = getattr(args, "measure_id", None)
    if not measure_id_fk:
        err("--measure-id is required")

    # Validate that the measure exists
    qm_t = Table("healthclaw_quality_measure")
    measure_row = conn.execute(
        Q.from_(qm_t).select(qm_t.id, qm_t.benchmark, qm_t.name)
        .where(qm_t.id == P())
        .get_sql(),
        (measure_id_fk,)
    ).fetchone()
    if not measure_row:
        err(f"Quality measure {measure_id_fk} not found")

    reporting_period = getattr(args, "reporting_period", None)
    if not reporting_period:
        err("--reporting-period is required")

    numerator = int(getattr(args, "numerator", None) or 0)
    denominator = int(getattr(args, "denominator", None) or 0)
    exclusions = int(getattr(args, "exclusions", None) or 0)

    # Calculate performance rate
    effective_denominator = denominator - exclusions
    if effective_denominator > 0:
        performance_rate = Decimal(str(numerator)) / Decimal(str(effective_denominator)) * Decimal("100")
        performance_rate = round_currency(performance_rate)
    else:
        performance_rate = Decimal("0")

    # Compare to benchmark
    measure_benchmark = measure_row[1]
    points_earned = Decimal("0")
    if measure_benchmark:
        benchmark_val = to_decimal(measure_benchmark)
        if performance_rate >= benchmark_val:
            points_earned = Decimal("10")  # Full points
        elif performance_rate >= benchmark_val * Decimal("0.5"):
            points_earned = Decimal("5")  # Partial points
        else:
            points_earned = Decimal("0")

    result_id = str(uuid.uuid4())
    now = _now_iso()
    provider_id = getattr(args, "provider_id", None)

    sql, _ = insert_row("healthclaw_quality_measure_result", {
        "id": P(), "measure_id": P(), "provider_id": P(),
        "reporting_period": P(), "numerator": P(), "denominator": P(),
        "exclusions": P(), "performance_rate": P(), "benchmark": P(),
        "points_earned": P(), "status": P(), "calculated_at": P(),
        "notes": P(), "created_at": P(),
    })

    conn.execute(sql, (
        result_id, measure_id_fk, provider_id,
        reporting_period, numerator, denominator,
        exclusions, str(performance_rate), measure_benchmark,
        str(points_earned), "calculated", now,
        getattr(args, "notes", None), now,
    ))
    audit(conn, "healthclaw_quality_measure_result", result_id, "health-calculate-measure-result", None)
    conn.commit()
    ok({
        "id": result_id,
        "measure_id": measure_id_fk,
        "measure_name": measure_row[2],
        "reporting_period": reporting_period,
        "numerator": numerator,
        "denominator": denominator,
        "exclusions": exclusions,
        "effective_denominator": effective_denominator,
        "performance_rate": str(performance_rate),
        "benchmark": measure_benchmark,
        "points_earned": str(round_currency(points_earned)),
        "result_status": "calculated",
    })


# ---------------------------------------------------------------------------
# 10. mips-performance-dashboard
# ---------------------------------------------------------------------------
def mips_performance_dashboard(conn, args):
    _validate_company(conn, args.company_id)

    reporting_period = getattr(args, "reporting_period", None)

    qm_t = Table("healthclaw_quality_measure")
    qmr_t = Table("healthclaw_quality_measure_result")

    # Get all measures for this company
    measures = conn.execute(
        Q.from_(qm_t).select(qm_t.star)
        .where(qm_t.company_id == P())
        .where(qm_t.status == P())
        .orderby(qm_t.measure_id, order=Order.asc)
        .get_sql(),
        (args.company_id, "active")
    ).fetchall()

    dashboard = []
    total_points = Decimal("0")
    max_points = Decimal("0")

    for m in measures:
        m_data = row_to_dict(m)
        m_id = m_data["id"]
        max_points += Decimal("10")

        # Get latest result for this measure (optionally filtered by reporting period)
        q_result = Q.from_(qmr_t).select(qmr_t.star).where(qmr_t.measure_id == P())
        result_params = [m_id]

        if reporting_period:
            q_result = q_result.where(qmr_t.reporting_period == P())
            result_params.append(reporting_period)

        q_result = q_result.orderby(qmr_t.created_at, order=Order.desc).limit(1)
        result_row = conn.execute(q_result.get_sql(), result_params).fetchone()

        latest_result = None
        if result_row:
            latest_result = row_to_dict(result_row)
            total_points += to_decimal(latest_result.get("points_earned", "0"))

        dashboard.append({
            "measure_id": m_data["measure_id"],
            "name": m_data["name"],
            "category": m_data["category"],
            "measure_type": m_data.get("measure_type", "process"),
            "benchmark": m_data.get("benchmark"),
            "latest_result": latest_result,
        })

    composite_score = Decimal("0")
    if max_points > Decimal("0"):
        composite_score = (total_points / max_points) * Decimal("100")

    ok({
        "company_id": args.company_id,
        "reporting_period": reporting_period,
        "measure_count": len(dashboard),
        "measures": dashboard,
        "total_points_earned": str(round_currency(total_points)),
        "max_possible_points": str(round_currency(max_points)),
        "composite_score": str(round_currency(composite_score)),
    })


# ---------------------------------------------------------------------------
# 11. mips-submission-report
# ---------------------------------------------------------------------------
def mips_submission_report(conn, args):
    _validate_company(conn, args.company_id)

    reporting_period = getattr(args, "reporting_period", None)
    if not reporting_period:
        err("--reporting-period is required")

    qm_t = Table("healthclaw_quality_measure")
    qmr_t = Table("healthclaw_quality_measure_result")

    # Get all measures for this company
    measures = conn.execute(
        Q.from_(qm_t).select(qm_t.star)
        .where(qm_t.company_id == P())
        .orderby(qm_t.measure_id, order=Order.asc)
        .get_sql(),
        (args.company_id,)
    ).fetchall()

    submission_items = []
    total_points = Decimal("0")
    submitted_count = 0
    calculated_count = 0

    for m in measures:
        m_data = row_to_dict(m)
        m_id = m_data["id"]

        # Get result for this measure and reporting period
        result_row = conn.execute(
            Q.from_(qmr_t).select(qmr_t.star)
            .where(qmr_t.measure_id == P())
            .where(qmr_t.reporting_period == P())
            .where(qmr_t.status.isin([P(), P()]))
            .orderby(qmr_t.created_at, order=Order.desc)
            .limit(1)
            .get_sql(),
            (m_id, reporting_period, "calculated", "submitted")
        ).fetchone()

        if result_row:
            r_data = row_to_dict(result_row)
            total_points += to_decimal(r_data.get("points_earned", "0"))
            if r_data["status"] == "submitted":
                submitted_count += 1
            else:
                calculated_count += 1

            submission_items.append({
                "measure_id": m_data["measure_id"],
                "measure_name": m_data["name"],
                "category": m_data["category"],
                "numerator": r_data.get("numerator", 0),
                "denominator": r_data.get("denominator", 0),
                "exclusions": r_data.get("exclusions", 0),
                "performance_rate": r_data.get("performance_rate", "0"),
                "benchmark": r_data.get("benchmark"),
                "points_earned": r_data.get("points_earned", "0"),
                "result_status": r_data["status"],
            })

    ok({
        "company_id": args.company_id,
        "reporting_period": reporting_period,
        "total_measures": len(submission_items),
        "calculated_count": calculated_count,
        "submitted_count": submitted_count,
        "total_points_earned": str(round_currency(total_points)),
        "measures": submission_items,
    })


# ===========================================================================
# H12: BAA (Business Associate Agreement) Tracking
# ===========================================================================

VALID_BAA_STATUSES = ("active", "expired", "terminated")


def add_baa(conn, args):
    _validate_company(conn, args.company_id)

    vendor_name = getattr(args, "vendor_name", None)
    if not vendor_name:
        err("--vendor-name is required")
    agreement_date = getattr(args, "agreement_date", None)
    if not agreement_date:
        err("--agreement-date is required")

    baa_id = str(uuid.uuid4())
    now = _now_iso()

    sql, _ = insert_row("healthclaw_baa", {
        "id": P(), "vendor_name": P(), "vendor_contact": P(),
        "agreement_date": P(), "expiration_date": P(), "review_date": P(),
        "phi_categories": P(), "breach_notification_days": P(),
        "status": P(), "company_id": P(), "created_at": P(),
    })
    conn.execute(sql, (
        baa_id, vendor_name,
        getattr(args, "vendor_contact", None),
        agreement_date,
        getattr(args, "expiration_date", None),
        getattr(args, "review_date", None),
        getattr(args, "phi_categories", None),
        int(getattr(args, "breach_notification_days", None) or 60),
        "active", args.company_id, now,
    ))
    audit(conn, "healthclaw_baa", baa_id, "health-add-baa", args.company_id)
    conn.commit()
    ok({
        "id": baa_id,
        "vendor_name": vendor_name,
        "agreement_date": agreement_date,
        "baa_status": "active",
    })


def list_baas(conn, args):
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_baa")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    q_count = q_count.where(t.company_id == P())
    q_rows = q_rows.where(t.company_id == P())
    params.append(args.company_id)

    status = getattr(args, "status", None)
    if status:
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(status)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.expiration_date, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


def check_expiring_baas(conn, args):
    """Check for BAAs expiring within the next N days."""
    _validate_company(conn, args.company_id)

    days = int(getattr(args, "days", None) or 90)
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")

    t = Table("healthclaw_baa")
    rows = conn.execute(
        Q.from_(t).select(t.star)
        .where(t.company_id == P())
        .where(t.status == P())
        .where(t.expiration_date.isnotnull())
        .where(t.expiration_date <= P())
        .orderby(t.expiration_date, order=Order.asc)
        .get_sql(),
        (args.company_id, "active", cutoff)
    ).fetchall()

    expiring = [row_to_dict(r) for r in rows]
    ok({
        "company_id": args.company_id,
        "days_ahead": days,
        "cutoff_date": cutoff,
        "expiring_count": len(expiring),
        "expiring_baas": expiring,
    })


# ===========================================================================
# H13: Breach Incident Management
# ===========================================================================

VALID_RISK_LEVELS = ("low", "medium", "high")
VALID_BREACH_STATUSES = ("investigating", "contained", "remediated", "closed")


def add_breach_incident(conn, args):
    _validate_company(conn, args.company_id)

    discovery_date = getattr(args, "discovery_date", None)
    if not discovery_date:
        err("--discovery-date is required")
    description = getattr(args, "description", None)
    if not description:
        err("--description is required")

    risk_level = getattr(args, "risk_level", None)
    _validate_enum(risk_level, VALID_RISK_LEVELS, "risk-level")

    breach_id = str(uuid.uuid4())
    now = _now_iso()

    sql, _ = insert_row("healthclaw_breach_incident", {
        "id": P(), "discovery_date": P(), "incident_date": P(),
        "description": P(), "phi_type": P(), "individuals_affected": P(),
        "risk_level": P(), "notification_required": P(),
        "notification_sent_date": P(), "hhs_reported": P(),
        "hhs_report_date": P(), "remediation": P(),
        "status": P(), "company_id": P(), "created_at": P(),
    })
    conn.execute(sql, (
        breach_id, discovery_date,
        getattr(args, "incident_date", None),
        description,
        getattr(args, "phi_type", None),
        int(getattr(args, "individuals_affected", None) or 0),
        risk_level or "medium",
        int(getattr(args, "notification_required", None) or 0),
        None, 0, None,
        getattr(args, "remediation", None),
        "investigating", args.company_id, now,
    ))
    audit(conn, "healthclaw_breach_incident", breach_id, "health-add-breach-incident", args.company_id)
    conn.commit()
    ok({
        "id": breach_id,
        "discovery_date": discovery_date,
        "risk_level": risk_level or "medium",
        "breach_status": "investigating",
    })


def update_breach_incident(conn, args):
    breach_id = getattr(args, "breach_id", None)
    if not breach_id:
        err("--breach-id is required")

    t = Table("healthclaw_breach_incident")
    row = conn.execute(
        Q.from_(t).select(t.id).where(t.id == P()).get_sql(),
        (breach_id,)
    ).fetchone()
    if not row:
        err(f"Breach incident {breach_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "description": "description", "phi_type": "phi_type",
        "remediation": "remediation", "notification_sent_date": "notification_sent_date",
        "hhs_report_date": "hhs_report_date", "incident_date": "incident_date",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    risk_level = getattr(args, "risk_level", None)
    if risk_level:
        _validate_enum(risk_level, VALID_RISK_LEVELS, "risk-level")
        data["risk_level"] = risk_level
        changed.append("risk_level")

    status = getattr(args, "status", None)
    if status:
        _validate_enum(status, VALID_BREACH_STATUSES, "status")
        data["status"] = status
        changed.append("status")

    individuals = getattr(args, "individuals_affected", None)
    if individuals is not None:
        data["individuals_affected"] = int(individuals)
        changed.append("individuals_affected")

    notification_required = getattr(args, "notification_required", None)
    if notification_required is not None:
        data["notification_required"] = int(notification_required)
        changed.append("notification_required")

    hhs_reported = getattr(args, "hhs_reported", None)
    if hhs_reported is not None:
        data["hhs_reported"] = int(hhs_reported)
        changed.append("hhs_reported")

    if not data:
        err("No fields to update")

    sql, params = dynamic_update("healthclaw_breach_incident", data, {"id": breach_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_breach_incident", breach_id, "health-update-breach-incident", None)
    conn.commit()
    ok({"id": breach_id, "updated_fields": changed})


def list_breach_incidents(conn, args):
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_breach_incident")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    q_count = q_count.where(t.company_id == P())
    q_rows = q_rows.where(t.company_id == P())
    params.append(args.company_id)

    status = getattr(args, "status", None)
    if status:
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(status)

    risk_level = getattr(args, "risk_level", None)
    if risk_level:
        q_count = q_count.where(t.risk_level == P())
        q_rows = q_rows.where(t.risk_level == P())
        params.append(risk_level)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.discovery_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


def breach_summary_report(conn, args):
    """Summary report of all breach incidents."""
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_breach_incident")
    all_rows = conn.execute(
        Q.from_(t).select(t.star)
        .where(t.company_id == P())
        .get_sql(),
        (args.company_id,)
    ).fetchall()

    by_status = {}
    by_risk = {}
    total_affected = 0
    hhs_reported_count = 0

    for r in all_rows:
        d = row_to_dict(r)
        s = d.get("status", "investigating")
        rl = d.get("risk_level", "medium")
        by_status[s] = by_status.get(s, 0) + 1
        by_risk[rl] = by_risk.get(rl, 0) + 1
        total_affected += int(d.get("individuals_affected", 0) or 0)
        if int(d.get("hhs_reported", 0) or 0) == 1:
            hhs_reported_count += 1

    ok({
        "company_id": args.company_id,
        "total_incidents": len(all_rows),
        "by_status": by_status,
        "by_risk_level": by_risk,
        "total_individuals_affected": total_affected,
        "hhs_reported_count": hhs_reported_count,
    })


# ===========================================================================
# H38: Consent Form Versioning
# ===========================================================================

def add_consent_template(conn, args):
    """Add a consent template (versioned). Stored as a consent record with template metadata."""
    _validate_company(conn, args.company_id)

    consent_type = getattr(args, "consent_type", None)
    if not consent_type:
        err("--consent-type is required")

    description = getattr(args, "description", None)
    if not description:
        err("--description is required (template body text)")

    # Store as a consent record with a special patient_id = 'TEMPLATE'
    # and version info in the notes field
    version = getattr(args, "version", None) or "1.0"
    template_id = str(uuid.uuid4())
    now = _now_iso()

    sql, _ = insert_row("healthclaw_consent", {
        "id": P(), "patient_id": P(), "consent_type": P(),
        "description": P(), "granted_date": P(), "expiration_date": P(),
        "status": P(), "witness_name": P(), "obtained_by_id": P(),
        "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P(),
    })

    # Use a template marker — store under company's first patient or create a system patient
    # Find any patient in this company to satisfy FK (template records are filtered by notes JSON)
    any_patient = conn.execute(
        Q.from_(Table("healthclaw_patient")).select(Field("id"))
        .where(Field("company_id") == P()).limit(1).get_sql(),
        (args.company_id,)
    ).fetchone()
    if not any_patient:
        err("At least one patient must exist before creating consent templates")
    template_patient_id = any_patient[0]

    conn.execute(sql, (
        template_id, template_patient_id, consent_type,
        description, now[:10], None,
        "active", None, None,
        json.dumps({"template": True, "version": version}),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_consent", template_id, "health-add-consent-template", args.company_id)
    conn.commit()
    ok({
        "id": template_id,
        "consent_type": consent_type,
        "version": version,
        "template_status": "active",
    })


def list_consent_templates(conn, args):
    """List consent templates (consent records where notes contains template=true)."""
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_consent")
    # Templates are stored with notes containing {"template": true}
    # We use LIKE to filter for template records
    template_filter = LiteralValue('"notes" LIKE \'%"template": true%\'')

    q_count = Q.from_(t).select(fn.Count("*")).where(
        (t.company_id == P()) & template_filter
    )
    q_rows = Q.from_(t).select(t.star).where(
        (t.company_id == P()) & template_filter
    )
    params = [args.company_id]

    consent_type = getattr(args, "consent_type", None)
    if consent_type:
        q_count = q_count.where(t.consent_type == P())
        q_rows = q_rows.where(t.consent_type == P())
        params.append(consent_type)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()

    # Enrich with version from notes JSON
    enriched = []
    for r in rows:
        d = row_to_dict(r)
        try:
            meta = json.loads(d.get("notes", "{}"))
            d["version"] = meta.get("version", "1.0")
            d["is_template"] = meta.get("template", False)
        except (json.JSONDecodeError, TypeError):
            d["version"] = "1.0"
            d["is_template"] = True
        enriched.append(d)

    ok({
        "rows": enriched,
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-log-phi-access": log_phi_access,
    "health-phi-access-report": phi_access_report,
    "health-phi-access-anomaly-check": phi_access_anomaly_check,
    "health-generate-good-faith-estimate": generate_good_faith_estimate,
    "health-list-good-faith-estimates": list_good_faith_estimates,
    "health-provide-good-faith-estimate": provide_good_faith_estimate,
    "health-add-quality-measure": add_quality_measure,
    "health-list-quality-measures": list_quality_measures,
    "health-calculate-measure-result": calculate_measure_result,
    "health-mips-performance-dashboard": mips_performance_dashboard,
    "health-mips-submission-report": mips_submission_report,
    # H12: BAA Tracking
    "health-add-baa": add_baa,
    "health-list-baas": list_baas,
    "health-check-expiring-baas": check_expiring_baas,
    # H13: Breach Incident
    "health-add-breach-incident": add_breach_incident,
    "health-update-breach-incident": update_breach_incident,
    "health-list-breach-incidents": list_breach_incidents,
    "health-breach-summary-report": breach_summary_report,
    # H38: Consent Templates
    "health-add-consent-template": add_consent_template,
    "health-list-consent-templates": list_consent_templates,
}
