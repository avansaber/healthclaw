"""HealthClaw — referrals domain module

Actions for the referrals/prior-auth domain (3 tables, 10 actions).
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
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update

    # Register HealthClaw naming prefixes (referrals domain)
    ENTITY_PREFIXES.setdefault("healthclaw_referral", "REF-")
    ENTITY_PREFIXES.setdefault("healthclaw_prior_auth", "AUTH-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_REFERRAL_STATUSES = ("pending", "sent", "accepted", "declined", "completed", "expired", "cancelled")
VALID_REFERRAL_PRIORITIES = ("stat", "urgent", "routine", "elective")
VALID_AUTH_STATUSES = ("pending", "approved", "denied", "partially_approved", "expired", "cancelled", "appealed")
VALID_AUTH_SERVICE_TYPES = ("procedure", "imaging", "medication", "dme", "inpatient", "outpatient", "referral", "therapy", "other")


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
# 1. add-referral
# ---------------------------------------------------------------------------
def add_referral(conn, args):
    _validate_company(conn, args.company_id)
    _validate_patient(conn, args.patient_id)

    referring_provider_id = getattr(args, "referring_provider_id", None)
    if not referring_provider_id:
        err("--referring-provider-id is required")
    if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (referring_provider_id,)).fetchone():
        err(f"Referring provider (employee) {referring_provider_id} not found")

    referred_to_provider = getattr(args, "referred_to_provider", None)
    if not referred_to_provider:
        err("--referred-to-provider is required")

    referral_date = getattr(args, "referral_date", None)
    if not referral_date:
        err("--referral-date is required")

    reason = getattr(args, "reason", None)
    if not reason:
        err("--reason is required")

    priority = getattr(args, "priority", None) or "routine"
    _validate_enum(priority, VALID_REFERRAL_PRIORITIES, "priority")

    # Optional FK checks
    encounter_id = getattr(args, "encounter_id", None)
    if encounter_id:
        if not conn.execute(Q.from_(Table("healthclaw_encounter")).select(Field("id")).where(Field("id") == P()).get_sql(), (encounter_id,)).fetchone():
            err(f"Encounter {encounter_id} not found")
    diagnosis_id = getattr(args, "diagnosis_id", None)
    if diagnosis_id:
        if not conn.execute(Q.from_(Table("healthclaw_diagnosis")).select(Field("id")).where(Field("id") == P()).get_sql(), (diagnosis_id,)).fetchone():
            err(f"Diagnosis {diagnosis_id} not found")
    insurance_id = getattr(args, "insurance_id", None)
    if insurance_id:
        if not conn.execute(Q.from_(Table("healthclaw_patient_insurance")).select(Field("id")).where(Field("id") == P()).get_sql(), (insurance_id,)).fetchone():
            err(f"Insurance {insurance_id} not found")
    prior_auth_id = getattr(args, "prior_auth_id", None)
    if prior_auth_id:
        if not conn.execute(Q.from_(Table("healthclaw_prior_auth")).select(Field("id")).where(Field("id") == P()).get_sql(), (prior_auth_id,)).fetchone():
            err(f"Prior auth {prior_auth_id} not found")

    ref_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_referral", company_id=args.company_id)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_referral", {"id": P(), "naming_series": P(), "patient_id": P(), "encounter_id": P(), "referring_provider_id": P(), "referred_to_provider": P(), "referred_to_specialty": P(), "referred_to_facility": P(), "referred_to_phone": P(), "referred_to_fax": P(), "referral_date": P(), "expiration_date": P(), "reason": P(), "diagnosis_id": P(), "priority": P(), "insurance_id": P(), "prior_auth_required": P(), "prior_auth_id": P(), "status": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        ref_id, naming, args.patient_id, encounter_id,
        referring_provider_id, referred_to_provider,
        getattr(args, "referred_to_specialty", None),
        getattr(args, "referred_to_facility", None),
        getattr(args, "referred_to_phone", None),
        getattr(args, "referred_to_fax", None),
        referral_date,
        getattr(args, "expiration_date", None),
        reason,
        diagnosis_id, priority, insurance_id,
        1 if getattr(args, "prior_auth_required", None) == "1" else 0,
        prior_auth_id,
        "pending",
        getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_referral", ref_id, "health-add-referral", args.company_id)
    conn.commit()
    ok({"id": ref_id, "naming_series": naming, "referred_to_provider": referred_to_provider, "status": "pending"})


# ---------------------------------------------------------------------------
# 2. update-referral
# ---------------------------------------------------------------------------
def update_referral(conn, args):
    ref_id = getattr(args, "referral_id", None)
    if not ref_id:
        err("--referral-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_referral")).select(Field("id")).where(Field("id") == P()).get_sql(), (ref_id,)).fetchone():
        err(f"Referral {ref_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "referred_to_provider": "referred_to_provider",
        "referred_to_specialty": "referred_to_specialty",
        "referred_to_facility": "referred_to_facility",
        "referred_to_phone": "referred_to_phone",
        "referred_to_fax": "referred_to_fax",
        "referral_date": "referral_date",
        "expiration_date": "expiration_date",
        "reason": "reason",
        "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    priority = getattr(args, "priority", None)
    if priority is not None:
        _validate_enum(priority, VALID_REFERRAL_PRIORITIES, "priority")
        data["priority"] = priority
        changed.append("priority")

    referral_status = getattr(args, "referral_status", None)
    if referral_status is not None:
        _validate_enum(referral_status, VALID_REFERRAL_STATUSES, "status")
        data["status"] = referral_status
        changed.append("status")

    # Optional FK updates
    diagnosis_id = getattr(args, "diagnosis_id", None)
    if diagnosis_id is not None:
        if not conn.execute(Q.from_(Table("healthclaw_diagnosis")).select(Field("id")).where(Field("id") == P()).get_sql(), (diagnosis_id,)).fetchone():
            err(f"Diagnosis {diagnosis_id} not found")
        data["diagnosis_id"] = diagnosis_id
        changed.append("diagnosis_id")

    insurance_id = getattr(args, "insurance_id", None)
    if insurance_id is not None:
        if not conn.execute(Q.from_(Table("healthclaw_patient_insurance")).select(Field("id")).where(Field("id") == P()).get_sql(), (insurance_id,)).fetchone():
            err(f"Insurance {insurance_id} not found")
        data["insurance_id"] = insurance_id
        changed.append("insurance_id")

    prior_auth_id = getattr(args, "prior_auth_id", None)
    if prior_auth_id is not None:
        if not conn.execute(Q.from_(Table("healthclaw_prior_auth")).select(Field("id")).where(Field("id") == P()).get_sql(), (prior_auth_id,)).fetchone():
            err(f"Prior auth {prior_auth_id} not found")
        data["prior_auth_id"] = prior_auth_id
        changed.append("prior_auth_id")

    if getattr(args, "prior_auth_required", None) is not None:
        data["prior_auth_required"] = 1 if args.prior_auth_required == "1" else 0
        changed.append("prior_auth_required")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("healthclaw_referral", data, {"id": ref_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_referral", ref_id, "health-update-referral", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": ref_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 3. get-referral
# ---------------------------------------------------------------------------
def get_referral(conn, args):
    ref_id = getattr(args, "referral_id", None)
    if not ref_id:
        err("--referral-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_referral")).select(Table("healthclaw_referral").star).where(Field("id") == P()).get_sql(), (ref_id,)).fetchone()
    if not row:
        err(f"Referral {ref_id} not found")
    data = row_to_dict(row)

    # Enrich: patient name
    _pat_t = Table("healthclaw_patient")
    pat = conn.execute(Q.from_(_pat_t).select(_pat_t.full_name).where(_pat_t.id == P()).get_sql(), (data["patient_id"],)).fetchone()
    if pat:
        data["patient_name"] = pat[0]
    # Enrich: referring provider name
    _emp_t = Table("employee")
    prov = conn.execute(Q.from_(_emp_t).select(_emp_t.full_name).where(_emp_t.id == P()).get_sql(), (data["referring_provider_id"],)).fetchone()
    if prov:
        data["referring_provider_name"] = prov[0]
    # Enrich: prior auth info if linked
    if data.get("prior_auth_id"):
        _auth_t = Table("healthclaw_prior_auth")
        auth = conn.execute(
            Q.from_(_auth_t).select(_auth_t.status, _auth_t.auth_number).where(_auth_t.id == P()).get_sql(),
            (data["prior_auth_id"],)
        ).fetchone()
        if auth:
            data["prior_auth_status"] = auth[0]
            data["prior_auth_number"] = auth[1]
    ok(data)


# ---------------------------------------------------------------------------
# 4. list-referrals
# ---------------------------------------------------------------------------
def list_referrals(conn, args):
    t = Table("healthclaw_referral")

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

    if getattr(args, "company_id", None):

        q_count = q_count.where(t.company_id == P())

        q_rows = q_rows.where(t.company_id == P())

        params.append(args.company_id)

    if getattr(args, "referring_provider_id", None):

        q_count = q_count.where(t.referring_provider_id == P())

        q_rows = q_rows.where(t.referring_provider_id == P())

        params.append(args.referring_provider_id)


    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.referral_date, order=Order.desc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 5. add-prior-auth
# ---------------------------------------------------------------------------
def add_prior_auth(conn, args):
    _validate_company(conn, args.company_id)
    _validate_patient(conn, args.patient_id)

    insurance_id = getattr(args, "insurance_id", None)
    if not insurance_id:
        err("--insurance-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_patient_insurance")).select(Field("id")).where(Field("id") == P()).get_sql(), (insurance_id,)).fetchone():
        err(f"Insurance {insurance_id} not found")

    requesting_provider_id = getattr(args, "requesting_provider_id", None)
    if not requesting_provider_id:
        err("--requesting-provider-id is required")
    if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (requesting_provider_id,)).fetchone():
        err(f"Requesting provider (employee) {requesting_provider_id} not found")

    service_type = getattr(args, "service_type", None)
    if not service_type:
        err("--service-type is required")
    _validate_enum(service_type, VALID_AUTH_SERVICE_TYPES, "health-service-type")

    description = getattr(args, "description", None)
    if not description:
        err("--description is required")

    request_date = getattr(args, "request_date", None)
    if not request_date:
        err("--request-date is required")

    auth_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_prior_auth", company_id=args.company_id)
    now = _now_iso()
    sql, _ = insert_row("healthclaw_prior_auth", {"id": P(), "naming_series": P(), "patient_id": P(), "insurance_id": P(), "requesting_provider_id": P(), "auth_number": P(), "service_type": P(), "cpt_codes": P(), "icd10_codes": P(), "description": P(), "units_requested": P(), "units_approved": P(), "request_date": P(), "effective_date": P(), "expiration_date": P(), "decision_date": P(), "status": P(), "denial_reason": P(), "appeal_deadline": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        auth_id, naming, args.patient_id, insurance_id,
        requesting_provider_id,
        getattr(args, "auth_number", None),
        service_type,
        getattr(args, "cpt_codes", None),
        getattr(args, "icd10_codes", None),
        description,
        int(getattr(args, "units_requested", None) or 1),
        None,  # units_approved set on approval
        request_date,
        getattr(args, "effective_date", None),
        getattr(args, "expiration_date", None),
        None,  # decision_date set on decision
        "pending",
        None, None,
        getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_prior_auth", auth_id, "health-add-prior-auth", args.company_id)
    conn.commit()
    ok({"id": auth_id, "naming_series": naming, "service_type": service_type, "status": "pending"})


# ---------------------------------------------------------------------------
# 6. update-prior-auth
# ---------------------------------------------------------------------------
def update_prior_auth(conn, args):
    auth_id = getattr(args, "prior_auth_id", None)
    if not auth_id:
        err("--prior-auth-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_prior_auth")).select(Field("id")).where(Field("id") == P()).get_sql(), (auth_id,)).fetchone():
        err(f"Prior auth {auth_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "auth_number": "auth_number",
        "cpt_codes": "cpt_codes",
        "icd10_codes": "icd10_codes",
        "description": "description",
        "effective_date": "effective_date",
        "expiration_date": "expiration_date",
        "decision_date": "decision_date",
        "denial_reason": "denial_reason",
        "appeal_deadline": "appeal_deadline",
        "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    service_type = getattr(args, "service_type", None)
    if service_type is not None:
        _validate_enum(service_type, VALID_AUTH_SERVICE_TYPES, "health-service-type")
        data["service_type"] = service_type
        changed.append("service_type")

    auth_status = getattr(args, "auth_status", None)
    if auth_status is not None:
        _validate_enum(auth_status, VALID_AUTH_STATUSES, "status")
        data["status"] = auth_status
        changed.append("status")

    units_requested = getattr(args, "units_requested", None)
    if units_requested is not None:
        data["units_requested"] = int(units_requested)
        changed.append("units_requested")

    units_approved = getattr(args, "units_approved", None)
    if units_approved is not None:
        data["units_approved"] = int(units_approved)
        changed.append("units_approved")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("healthclaw_prior_auth", data, {"id": auth_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_prior_auth", auth_id, "health-update-prior-auth", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": auth_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 7. get-prior-auth
# ---------------------------------------------------------------------------
def get_prior_auth(conn, args):
    auth_id = getattr(args, "prior_auth_id", None)
    if not auth_id:
        err("--prior-auth-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_prior_auth")).select(Table("healthclaw_prior_auth").star).where(Field("id") == P()).get_sql(), (auth_id,)).fetchone()
    if not row:
        err(f"Prior auth {auth_id} not found")
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
    # Enrich: requesting provider name
    _emp_t = Table("employee")
    prov = conn.execute(Q.from_(_emp_t).select(_emp_t.full_name).where(_emp_t.id == P()).get_sql(), (data["requesting_provider_id"],)).fetchone()
    if prov:
        data["requesting_provider_name"] = prov[0]
    # Enrich: usage count
    _au_t = Table("healthclaw_auth_usage")
    usage = conn.execute(
        Q.from_(_au_t).select(fn.Count("*"), fn.Coalesce(fn.Sum(_au_t.units_used), 0)).where(_au_t.prior_auth_id == P()).get_sql(),
        (auth_id,)
    ).fetchone()
    data["usage_count"] = usage[0]
    data["total_units_used"] = usage[1]
    ok(data)


# ---------------------------------------------------------------------------
# 8. list-prior-auths
# ---------------------------------------------------------------------------
def list_prior_auths(conn, args):
    t = Table("healthclaw_prior_auth")

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

    if getattr(args, "company_id", None):

        q_count = q_count.where(t.company_id == P())

        q_rows = q_rows.where(t.company_id == P())

        params.append(args.company_id)

    if getattr(args, "insurance_id", None):

        q_count = q_count.where(t.insurance_id == P())

        q_rows = q_rows.where(t.insurance_id == P())

        params.append(args.insurance_id)


    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.request_date, order=Order.desc).limit(P()).offset(P())

    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 9. add-auth-usage
# ---------------------------------------------------------------------------
def add_auth_usage(conn, args):
    prior_auth_id = getattr(args, "prior_auth_id", None)
    if not prior_auth_id:
        err("--prior-auth-id is required")
    if not conn.execute(Q.from_(Table("healthclaw_prior_auth")).select(Field("id")).where(Field("id") == P()).get_sql(), (prior_auth_id,)).fetchone():
        err(f"Prior auth {prior_auth_id} not found")

    usage_date = getattr(args, "usage_date", None)
    if not usage_date:
        err("--usage-date is required")

    # Optional FK checks
    encounter_id = getattr(args, "encounter_id", None)
    if encounter_id:
        if not conn.execute(Q.from_(Table("healthclaw_encounter")).select(Field("id")).where(Field("id") == P()).get_sql(), (encounter_id,)).fetchone():
            err(f"Encounter {encounter_id} not found")
    claim_id = getattr(args, "claim_id", None)
    if claim_id:
        if not conn.execute(Q.from_(Table("healthclaw_claim")).select(Field("id")).where(Field("id") == P()).get_sql(), (claim_id,)).fetchone():
            err(f"Claim {claim_id} not found")

    au_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_auth_usage", {"id": P(), "prior_auth_id": P(), "encounter_id": P(), "claim_id": P(), "usage_date": P(), "units_used": P(), "notes": P(), "created_at": P()})

    conn.execute(sql, (
        au_id, prior_auth_id, encounter_id, claim_id,
        usage_date,
        int(getattr(args, "units_used", None) or 1),
        getattr(args, "notes", None),
        now,
    ))
    audit(conn, "healthclaw_auth_usage", au_id, "health-add-auth-usage", None)
    conn.commit()
    ok({"id": au_id, "prior_auth_id": prior_auth_id, "usage_date": usage_date})


# ---------------------------------------------------------------------------
# 10. list-auth-usages
# ---------------------------------------------------------------------------
def list_auth_usages(conn, args):
    t = Table("healthclaw_auth_usage")

    q_count = Q.from_(t).select(fn.Count("*"))

    q_rows = Q.from_(t).select(t.star)

    params = []


    if getattr(args, "prior_auth_id", None):

        q_count = q_count.where(t.prior_auth_id == P())

        q_rows = q_rows.where(t.prior_auth_id == P())

        params.append(args.prior_auth_id)

    if getattr(args, "encounter_id", None):

        q_count = q_count.where(t.encounter_id == P())

        q_rows = q_rows.where(t.encounter_id == P())

        params.append(args.encounter_id)

    if getattr(args, "claim_id", None):

        q_count = q_count.where(t.claim_id == P())

        q_rows = q_rows.where(t.claim_id == P())

        params.append(args.claim_id)


    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.usage_date, order=Order.desc).limit(P()).offset(P())

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
    "health-add-referral": add_referral,
    "health-update-referral": update_referral,
    "health-get-referral": get_referral,
    "health-list-referrals": list_referrals,
    "health-add-prior-auth": add_prior_auth,
    "health-update-prior-auth": update_prior_auth,
    "health-get-prior-auth": get_prior_auth,
    "health-list-prior-auths": list_prior_auths,
    "health-add-auth-usage": add_auth_usage,
    "health-list-auth-usages": list_auth_usages,
}
