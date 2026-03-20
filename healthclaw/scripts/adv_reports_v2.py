"""HealthClaw — Phase 11 advanced reports & misc actions.

H29-32: Billing reports (collections aging, charge reconciliation, batch submit, provider productivity)
H25: Underpayment detection
H26: Superbill generation
H33-35: Interoperability stubs (FHIR, CCD, Lab)
H39-44: Misc (scheduling rules, growth chart)

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
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update, update_row
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


# ===========================================================================
# H29: Collections Aging Report
# ===========================================================================

def collections_aging_report(conn, args):
    """AR aging by patient: current, 30, 60, 90, 120+ day buckets."""
    _validate_company(conn, args.company_id)

    # Get all payment postings grouped by patient
    pp_t = Table("healthclaw_payment_posting")
    ch_t = Table("healthclaw_charge")
    pat_t = Table("healthclaw_patient")

    # Get all charges for this company
    charges = conn.execute(
        Q.from_(ch_t).select(ch_t.patient_id, ch_t.charge_amount, ch_t.service_date)
        .where(ch_t.company_id == P())
        .get_sql(),
        (args.company_id,)
    ).fetchall()

    # Get all payments for this company
    payments = conn.execute(
        Q.from_(pp_t).select(pp_t.patient_id, pp_t.amount)
        .where(pp_t.company_id == P())
        .get_sql(),
        (args.company_id,)
    ).fetchall()

    # Build patient totals
    patient_charges = {}
    patient_aging = {}
    now_dt = datetime.now(timezone.utc)

    for r in charges:
        pid = r[0]
        amt = to_decimal(r[1] or "0")
        svc_date = r[2]
        patient_charges.setdefault(pid, Decimal("0"))
        patient_charges[pid] += amt

        # Calculate aging bucket
        if svc_date:
            try:
                svc_dt = datetime.strptime(svc_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days = (now_dt - svc_dt).days
                bucket = "current" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 else "91_120" if days <= 120 else "120_plus"
            except ValueError:
                bucket = "current"
        else:
            bucket = "current"

        patient_aging.setdefault(pid, {"current": Decimal("0"), "31_60": Decimal("0"),
                                       "61_90": Decimal("0"), "91_120": Decimal("0"),
                                       "120_plus": Decimal("0")})
        patient_aging[pid][bucket] += amt

    patient_payments = {}
    for r in payments:
        pid = r[0]
        amt = to_decimal(r[1] or "0")
        patient_payments.setdefault(pid, Decimal("0"))
        patient_payments[pid] += amt

    # Build report
    aging_rows = []
    total_ar = Decimal("0")
    for pid, total_charge in patient_charges.items():
        total_paid = patient_payments.get(pid, Decimal("0"))
        balance = total_charge - total_paid
        if balance <= Decimal("0"):
            continue

        # Get patient name
        pat_row = conn.execute(
            Q.from_(pat_t).select(pat_t.full_name).where(pat_t.id == P()).get_sql(),
            (pid,)
        ).fetchone()
        pat_name = pat_row[0] if pat_row else "Unknown"

        buckets = patient_aging.get(pid, {})
        aging_rows.append({
            "patient_id": pid,
            "patient_name": pat_name,
            "total_charges": str(round_currency(total_charge)),
            "total_payments": str(round_currency(total_paid)),
            "balance_due": str(round_currency(balance)),
            "current": str(round_currency(buckets.get("current", Decimal("0")))),
            "31_60_days": str(round_currency(buckets.get("31_60", Decimal("0")))),
            "61_90_days": str(round_currency(buckets.get("61_90", Decimal("0")))),
            "91_120_days": str(round_currency(buckets.get("91_120", Decimal("0")))),
            "120_plus_days": str(round_currency(buckets.get("120_plus", Decimal("0")))),
        })
        total_ar += balance

    aging_rows.sort(key=lambda x: to_decimal(x["balance_due"]), reverse=True)

    ok({
        "company_id": args.company_id,
        "total_ar": str(round_currency(total_ar)),
        "patient_count": len(aging_rows),
        "aging": aging_rows[:int(getattr(args, "limit", 50) or 50)],
    })


# ===========================================================================
# H30: Charge Reconciliation Report
# ===========================================================================

def charge_reconciliation_report(conn, args):
    """Compare encounters vs charges to detect missed charges."""
    _validate_company(conn, args.company_id)

    enc_t = Table("healthclaw_encounter")
    ch_t = Table("healthclaw_charge")

    # Get completed encounters
    q_enc = Q.from_(enc_t).select(enc_t.id, enc_t.patient_id, enc_t.encounter_date, enc_t.provider_id)
    q_enc = q_enc.where(enc_t.company_id == P()).where(enc_t.status == P())
    params = [args.company_id, "completed"]

    date_from = getattr(args, "date_from", None)
    if date_from:
        q_enc = q_enc.where(enc_t.encounter_date >= P())
        params.append(date_from)
    date_to = getattr(args, "date_to", None)
    if date_to:
        q_enc = q_enc.where(enc_t.encounter_date <= P())
        params.append(date_to)

    encounters = conn.execute(q_enc.get_sql(), params).fetchall()

    missing_charges = []
    for enc in encounters:
        enc_id = enc[0]
        # Check if there are charges for this encounter
        charge_count = conn.execute(
            Q.from_(ch_t).select(fn.Count("*")).where(ch_t.encounter_id == P()).get_sql(),
            (enc_id,)
        ).fetchone()[0]

        if charge_count == 0:
            missing_charges.append({
                "encounter_id": enc_id,
                "patient_id": enc[1],
                "encounter_date": enc[2],
                "provider_id": enc[3],
                "charge_count": 0,
                "issue": "No charges found for completed encounter",
            })

    ok({
        "company_id": args.company_id,
        "total_completed_encounters": len(encounters),
        "encounters_without_charges": len(missing_charges),
        "missing_charges": missing_charges[:int(getattr(args, "limit", 50) or 50)],
    })


# ===========================================================================
# H31: Batch Submit Claims
# ===========================================================================

def batch_submit_claims(conn, args):
    """Submit multiple draft claims at once."""
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_claim")
    # Get all draft claims for this company
    draft_claims = conn.execute(
        Q.from_(t).select(t.id).where(
            (t.company_id == P()) & (t.claim_status == P())
        ).get_sql(),
        (args.company_id, "draft")
    ).fetchall()

    submitted = []
    failed = []

    for row in draft_claims:
        claim_id = row[0]
        # Check if claim has lines
        line_count = conn.execute(
            Q.from_(Table("healthclaw_claim_line")).select(fn.Count("*"))
            .where(Field("claim_id") == P()).get_sql(),
            (claim_id,)
        ).fetchone()[0]

        if line_count == 0:
            failed.append({"claim_id": claim_id, "reason": "No claim lines"})
            continue

        # Submit
        sql = update_row("healthclaw_claim",
            data={"claim_status": "submitted", "updated_at": LiteralValue("datetime('now')")},
            where={"id": P()})
        conn.execute(sql, (claim_id,))
        audit(conn, "healthclaw_claim", claim_id, "health-batch-submit-claims", args.company_id)
        submitted.append(claim_id)

    conn.commit()
    ok({
        "company_id": args.company_id,
        "submitted_count": len(submitted),
        "failed_count": len(failed),
        "submitted_claim_ids": submitted,
        "failures": failed,
    })


# ===========================================================================
# H32: Provider Productivity Report
# ===========================================================================

def provider_productivity_report(conn, args):
    """wRVUs, patients/day, revenue per provider."""
    _validate_company(conn, args.company_id)

    enc_t = Table("healthclaw_encounter")
    ch_t = Table("healthclaw_charge")
    emp_t = Table("employee")

    # Get all providers (employees with encounters)
    providers = conn.execute(
        Q.from_(enc_t).select(enc_t.provider_id)
        .where(enc_t.company_id == P())
        .groupby(enc_t.provider_id)
        .get_sql(),
        (args.company_id,)
    ).fetchall()

    date_from = getattr(args, "date_from", None)
    date_to = getattr(args, "date_to", None)

    report = []
    for prov in providers:
        provider_id = prov[0]
        if not provider_id:
            continue

        # Provider name
        prov_row = conn.execute(
            Q.from_(emp_t).select(emp_t.full_name).where(emp_t.id == P()).get_sql(),
            (provider_id,)
        ).fetchone()
        prov_name = prov_row[0] if prov_row else "Unknown"

        # Encounter count
        q_enc = Q.from_(enc_t).select(fn.Count("*")).where(
            (enc_t.company_id == P()) & (enc_t.provider_id == P())
        )
        enc_params = [args.company_id, provider_id]
        if date_from:
            q_enc = q_enc.where(enc_t.encounter_date >= P())
            enc_params.append(date_from)
        if date_to:
            q_enc = q_enc.where(enc_t.encounter_date <= P())
            enc_params.append(date_to)

        enc_count = conn.execute(q_enc.get_sql(), enc_params).fetchone()[0]

        # Unique patient count
        q_pat = Q.from_(enc_t).select(enc_t.patient_id).where(
            (enc_t.company_id == P()) & (enc_t.provider_id == P())
        ).groupby(enc_t.patient_id)
        pat_params = [args.company_id, provider_id]
        if date_from:
            q_pat = q_pat.where(enc_t.encounter_date >= P())
            pat_params.append(date_from)
        if date_to:
            q_pat = q_pat.where(enc_t.encounter_date <= P())
            pat_params.append(date_to)
        patient_count = len(conn.execute(q_pat.get_sql(), pat_params).fetchall())

        # Revenue from charges
        q_rev = Q.from_(ch_t).select(ch_t.charge_amount).where(
            (ch_t.company_id == P()) & (ch_t.provider_id == P())
        )
        rev_params = [args.company_id, provider_id]
        if date_from:
            q_rev = q_rev.where(ch_t.service_date >= P())
            rev_params.append(date_from)
        if date_to:
            q_rev = q_rev.where(ch_t.service_date <= P())
            rev_params.append(date_to)

        rev_rows = conn.execute(q_rev.get_sql(), rev_params).fetchall()
        total_revenue = sum((to_decimal(r[0] or "0") for r in rev_rows), Decimal("0"))

        # Unique encounter dates for patients/day calculation
        q_dates = Q.from_(enc_t).select(enc_t.encounter_date).where(
            (enc_t.company_id == P()) & (enc_t.provider_id == P())
        ).groupby(enc_t.encounter_date)
        dates_params = [args.company_id, provider_id]
        if date_from:
            q_dates = q_dates.where(enc_t.encounter_date >= P())
            dates_params.append(date_from)
        if date_to:
            q_dates = q_dates.where(enc_t.encounter_date <= P())
            dates_params.append(date_to)
        work_days = len(conn.execute(q_dates.get_sql(), dates_params).fetchall())
        patients_per_day = round(enc_count / work_days, 1) if work_days > 0 else 0.0

        report.append({
            "provider_id": provider_id,
            "provider_name": prov_name,
            "encounter_count": enc_count,
            "unique_patients": patient_count,
            "work_days": work_days,
            "patients_per_day": patients_per_day,
            "total_revenue": str(round_currency(total_revenue)),
            "revenue_per_encounter": str(round_currency(total_revenue / Decimal(str(enc_count)))) if enc_count > 0 else "0.00",
        })

    report.sort(key=lambda x: to_decimal(x["total_revenue"]), reverse=True)
    ok({"company_id": args.company_id, "provider_count": len(report), "providers": report})


# ===========================================================================
# H25: Underpayment Detection
# ===========================================================================

def underpayment_report(conn, args):
    """Compare paid_amount vs allowed_amount on payment_posting / claim lines."""
    _validate_company(conn, args.company_id)

    cl_t = Table("healthclaw_claim_line")
    clm_t = Table("healthclaw_claim")

    # Get claim lines with both allowed and paid amounts
    rows = conn.execute(
        Q.from_(cl_t).join(clm_t).on(cl_t.claim_id == clm_t.id)
        .select(cl_t.id, cl_t.claim_id, cl_t.cpt_code, cl_t.allowed_amount,
                cl_t.paid_amount, cl_t.charge_amount, clm_t.patient_id, clm_t.payer_name)
        .where(clm_t.company_id == P())
        .where(clm_t.claim_status.isin([P(), P()]))
        .get_sql(),
        (args.company_id, "paid", "partially_paid")
    ).fetchall()

    underpayments = []
    total_underpaid = Decimal("0")

    for r in rows:
        d = row_to_dict(r)
        allowed = to_decimal(d.get("allowed_amount", "0"))
        paid = to_decimal(d.get("paid_amount", "0"))
        if allowed > Decimal("0") and paid < allowed:
            diff = allowed - paid
            total_underpaid += diff
            underpayments.append({
                "claim_line_id": d["id"],
                "claim_id": d["claim_id"],
                "cpt_code": d["cpt_code"],
                "allowed_amount": str(round_currency(allowed)),
                "paid_amount": str(round_currency(paid)),
                "underpayment": str(round_currency(diff)),
                "patient_id": d.get("patient_id"),
                "payer_name": d.get("payer_name"),
            })

    underpayments.sort(key=lambda x: to_decimal(x["underpayment"]), reverse=True)
    ok({
        "company_id": args.company_id,
        "underpayment_count": len(underpayments),
        "total_underpaid": str(round_currency(total_underpaid)),
        "underpayments": underpayments[:int(getattr(args, "limit", 50) or 50)],
    })


# ===========================================================================
# H26: Superbill Generation
# ===========================================================================

def generate_superbill(conn, args):
    """Generate a superbill from an encounter: diagnoses + CPT codes + charges."""
    encounter_id = getattr(args, "encounter_id", None)
    if not encounter_id:
        err("--encounter-id is required")

    enc_t = Table("healthclaw_encounter")
    enc_row = conn.execute(
        Q.from_(enc_t).select(enc_t.star).where(enc_t.id == P()).get_sql(),
        (encounter_id,)
    ).fetchone()
    if not enc_row:
        err(f"Encounter {encounter_id} not found")
    enc = row_to_dict(enc_row)

    # Get diagnoses
    dx_t = Table("healthclaw_diagnosis")
    dx_rows = conn.execute(
        Q.from_(dx_t).select(dx_t.icd10_code, dx_t.description, dx_t.diagnosis_type)
        .where(dx_t.encounter_id == P())
        .orderby(dx_t.diagnosis_type, order=Order.asc)
        .get_sql(),
        (encounter_id,)
    ).fetchall()
    diagnoses = [{"icd10_code": r[0], "description": r[1], "type": r[2]} for r in dx_rows]

    # Get procedures
    proc_t = Table("healthclaw_procedure")
    proc_rows = conn.execute(
        Q.from_(proc_t).select(proc_t.cpt_code, proc_t.description, proc_t.modifiers)
        .where(proc_t.encounter_id == P())
        .get_sql(),
        (encounter_id,)
    ).fetchall()
    procedures = [{"cpt_code": r[0], "description": r[1], "modifiers": r[2]} for r in proc_rows]

    # Get charges
    ch_t = Table("healthclaw_charge")
    ch_rows = conn.execute(
        Q.from_(ch_t).select(ch_t.cpt_code, ch_t.charge_amount, ch_t.units, ch_t.modifiers, ch_t.service_date)
        .where(ch_t.encounter_id == P())
        .get_sql(),
        (encounter_id,)
    ).fetchall()
    charges = []
    total_charges = Decimal("0")
    for r in ch_rows:
        amt = to_decimal(r[1] or "0")
        total_charges += amt
        charges.append({
            "cpt_code": r[0], "charge_amount": str(round_currency(amt)),
            "units": r[2], "modifiers": r[3], "service_date": r[4],
        })

    # Patient info
    pat_t = Table("healthclaw_patient")
    pat_row = conn.execute(
        Q.from_(pat_t).select(pat_t.full_name, pat_t.date_of_birth)
        .where(pat_t.id == P()).get_sql(),
        (enc["patient_id"],)
    ).fetchone()

    # Provider info
    emp_t = Table("employee")
    prov_row = conn.execute(
        Q.from_(emp_t).select(emp_t.full_name).where(emp_t.id == P()).get_sql(),
        (enc["provider_id"],)
    ).fetchone()

    ok({
        "encounter_id": encounter_id,
        "encounter_date": enc.get("encounter_date"),
        "encounter_type": enc.get("encounter_type"),
        "patient_id": enc["patient_id"],
        "patient_name": pat_row[0] if pat_row else None,
        "patient_dob": pat_row[1] if pat_row else None,
        "provider_id": enc["provider_id"],
        "provider_name": prov_row[0] if prov_row else None,
        "diagnoses": diagnoses,
        "procedures": procedures,
        "charges": charges,
        "total_charges": str(round_currency(total_charges)),
    })


# ===========================================================================
# H33-35: Interoperability Stubs (FHIR, CCD, Lab Interface)
# ===========================================================================

def fhir_export_patient(conn, args):
    """Stub: FHIR patient export."""
    _validate_patient(conn, args.patient_id)
    ok({
        "feature_status": "not_implemented",
        "message": "FHIR export not yet implemented. This feature will support FHIR R4 Patient resource export.",
        "patient_id": args.patient_id,
    })


def generate_ccd(conn, args):
    """Stub: CDA/CCD generation."""
    _validate_patient(conn, args.patient_id)
    ok({
        "feature_status": "not_implemented",
        "message": "CCD generation not yet implemented. This feature will support C-CDA 2.1 Continuity of Care Document.",
        "patient_id": args.patient_id,
    })


def lab_interface_status(conn, args):
    """Stub: Lab interface status check."""
    _validate_company(conn, args.company_id)
    ok({
        "feature_status": "not_configured",
        "message": "Lab interface not yet configured. This feature will support HL7v2 lab orders and results.",
        "company_id": args.company_id,
    })


# ===========================================================================
# H39: Online Scheduling Rules
# ===========================================================================

def online_scheduling_rules(conn, args):
    """Return scheduling policy info / rules."""
    _validate_company(conn, args.company_id)

    t = Table("healthclaw_scheduling_rule")
    rows = conn.execute(
        Q.from_(t).select(t.star)
        .where(t.company_id == P())
        .where(t.status == P())
        .orderby(t.rule_type, order=Order.asc)
        .get_sql(),
        (args.company_id, "active")
    ).fetchall()

    rules = [row_to_dict(r) for r in rows]

    # If no rules, return defaults
    if not rules:
        rules = [
            {"rule_type": "buffer_time", "rule_value": "15", "description": "Minutes between appointments"},
            {"rule_type": "max_per_day", "rule_value": "20", "description": "Max appointments per provider per day"},
            {"rule_type": "advance_booking_days", "rule_value": "90", "description": "Days in advance patients can book"},
            {"rule_type": "cancellation_hours", "rule_value": "24", "description": "Hours notice required for cancellation"},
        ]

    ok({
        "company_id": args.company_id,
        "rule_count": len(rules),
        "rules": rules,
    })


# ===========================================================================
# H44: Growth Chart (Pediatric)
# ===========================================================================

# CDC growth chart percentile lookup (simplified - weight-for-age, boys, 0-36 months)
CDC_WEIGHT_PERCENTILES = {
    # age_months: {3rd, 10th, 25th, 50th, 75th, 90th, 97th} in kg
    0: {"3": 2.5, "10": 2.8, "25": 3.1, "50": 3.4, "75": 3.7, "90": 4.0, "97": 4.3},
    6: {"3": 6.0, "10": 6.6, "25": 7.1, "50": 7.8, "75": 8.5, "90": 9.0, "97": 9.6},
    12: {"3": 7.9, "10": 8.6, "25": 9.4, "50": 10.2, "75": 11.0, "90": 11.8, "97": 12.5},
    24: {"3": 10.0, "10": 10.8, "25": 11.8, "50": 12.8, "75": 13.9, "90": 15.0, "97": 16.1},
    36: {"3": 11.5, "10": 12.5, "25": 13.6, "50": 14.8, "75": 16.1, "90": 17.4, "97": 18.6},
}


def growth_chart(conn, args):
    """Return percentile data given age, sex, measurement."""
    age_months = getattr(args, "age_months", None)
    if age_months is None:
        err("--age-months is required")
    age_months = int(age_months)

    sex = getattr(args, "gender", None) or "male"
    measurement = getattr(args, "weight", None)
    measurement_type = "weight_for_age"

    if measurement:
        measurement = float(measurement)
    else:
        err("--weight is required (in kg)")

    # Find closest age bracket
    brackets = sorted(CDC_WEIGHT_PERCENTILES.keys())
    closest = min(brackets, key=lambda x: abs(x - age_months))
    percentiles = CDC_WEIGHT_PERCENTILES[closest]

    # Determine percentile range
    pct = "below_3rd"
    for p in ["3", "10", "25", "50", "75", "90", "97"]:
        if measurement >= percentiles[p]:
            pct = f"at_or_above_{p}th"

    ok({
        "age_months": age_months,
        "sex": sex,
        "measurement_type": measurement_type,
        "measurement_value": measurement,
        "measurement_unit": "kg",
        "reference_age_months": closest,
        "percentile_range": pct,
        "percentile_reference": percentiles,
    })


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    # H29-32: Reports
    "health-collections-aging-report": collections_aging_report,
    "health-charge-reconciliation-report": charge_reconciliation_report,
    "health-batch-submit-claims": batch_submit_claims,
    "health-provider-productivity-report": provider_productivity_report,
    # H25: Underpayment Detection
    "health-underpayment-report": underpayment_report,
    # H26: Superbill
    "health-generate-superbill": generate_superbill,
    # H33-35: Interoperability Stubs
    "health-fhir-export-patient": fhir_export_patient,
    "health-generate-ccd": generate_ccd,
    "health-lab-interface-status": lab_interface_status,
    # H39-44: Misc
    "health-online-scheduling-rules": online_scheduling_rules,
    "health-growth-chart": growth_chart,
}
