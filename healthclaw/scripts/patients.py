"""HealthClaw — patients domain module

Actions for the patients domain (6 tables, 16 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sqlite3
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
    from erpclaw_lib.crypto import encrypt_field as _enc_raw, decrypt_field as _dec_raw, derive_key
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update, now

    # Register HealthClaw naming prefixes (patients domain)
    ENTITY_PREFIXES.setdefault("healthclaw_patient", "PAT-")
    ENTITY_PREFIXES.setdefault("healthclaw_patient_insurance", "INS-")
except ImportError:
    pass

# --- SSN encryption helpers ---
_SSN_KEY = None
try:
    _passphrase = os.environ.get("ERPCLAW_FIELD_KEY", "")
    if _passphrase:
        _SSN_KEY = derive_key(_passphrase, b"healthclaw_ssn_salt_v1")
    else:
        import secrets
        _SSN_KEY = derive_key(secrets.token_hex(32), b"healthclaw_ssn_salt_v1")
        print("WARNING: ERPCLAW_FIELD_KEY not set. SSN encryption key is ephemeral.", file=sys.stderr)
except Exception:
    pass


def _encrypt_ssn(raw_ssn):
    """Encrypt SSN for storage. Returns (encrypted_value, last4)."""
    if not raw_ssn:
        return None, None
    digits = raw_ssn.replace("-", "").replace(" ", "")
    last4 = digits[-4:] if len(digits) >= 4 else digits
    if _SSN_KEY:
        return _enc_raw(raw_ssn, _SSN_KEY), last4
    raise ValueError("Cannot store SSN: encryption key not available. Set ERPCLAW_FIELD_KEY env var.")


def _mask_ssn_in_row(data):
    """Remove raw SSN from response, keep only last 4."""
    if "ssn" in data:
        raw = data.pop("ssn", None)
        if raw and isinstance(raw, str) and raw.startswith("enc:"):
            data["ssn_last4"] = data.get("ssn_last4") or "****"
        elif raw:
            # Legacy unencrypted — mask it
            digits = raw.replace("-", "").replace(" ", "")
            data["ssn_last4"] = digits[-4:] if len(digits) >= 4 else "****"
        else:
            data["ssn_last4"] = data.get("ssn_last4") or None
    return data

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_GENDERS = ("male", "female", "other", "unknown")
VALID_PATIENT_STATUSES = ("active", "inactive", "deceased")
VALID_MARITAL_STATUSES = ("single", "married", "divorced", "widowed", "separated", "unknown")
VALID_ETHNICITIES = ("hispanic_latino", "not_hispanic_latino", "unknown")
VALID_INSURANCE_TYPES = ("primary", "secondary", "tertiary")
VALID_PLAN_TYPES = ("hmo", "ppo", "epo", "pos", "hdhp", "medicare", "medicaid", "tricare", "workers_comp", "self_pay", "other")
VALID_SUBSCRIBER_RELATIONSHIPS = ("self", "spouse", "child", "other")
VALID_INSURANCE_STATUSES = ("active", "inactive", "expired", "terminated")
VALID_ALLERGEN_TYPES = ("drug", "food", "environmental", "other")
VALID_SEVERITIES = ("mild", "moderate", "severe", "life_threatening")
VALID_ALLERGY_STATUSES = ("active", "inactive", "resolved")
VALID_MEDHIST_STATUSES = ("active", "resolved", "chronic")
VALID_CONTACT_TYPES = ("emergency", "next_of_kin", "guardian", "power_of_attorney", "other")
VALID_CONSENT_TYPES = ("hipaa_privacy", "treatment", "surgery", "anesthesia", "research", "telehealth", "photo_video", "release_of_info", "other")
VALID_CONSENT_STATUSES = ("active", "expired", "revoked")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    row = conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (company_id,)).fetchone()
    if not row:
        err(f"Company {company_id} not found")


def _validate_patient(conn, patient_id):
    if not patient_id:
        err("--patient-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_patient")).select(Field("id")).where(Field("id") == P()).get_sql(), (patient_id,)).fetchone()
    if not row:
        err(f"Patient {patient_id} not found")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


# ---------------------------------------------------------------------------
# 1. add-patient
# ---------------------------------------------------------------------------
def add_patient(conn, args):
    _validate_company(conn, args.company_id)
    if not args.first_name:
        err("--first-name is required")
    if not args.last_name:
        err("--last-name is required")
    if not args.date_of_birth:
        err("--date-of-birth is required")
    if not args.gender:
        err("--gender is required")
    _validate_enum(args.gender, VALID_GENDERS, "gender")
    _validate_enum(getattr(args, "marital_status", None), VALID_MARITAL_STATUSES, "health-marital-status")
    _validate_enum(getattr(args, "ethnicity", None), VALID_ETHNICITIES, "ethnicity")

    # Check provider exists if specified
    provider_id = getattr(args, "primary_provider_id", None)
    if provider_id:
        row = conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (provider_id,)).fetchone()
        if not row:
            err(f"Provider (employee) {provider_id} not found")

    patient_id = str(uuid.uuid4())
    full_name = f"{args.first_name} {args.last_name}"

    # Generate naming series (MRN)
    mrn = get_next_name(conn, "healthclaw_patient", company_id=args.company_id)

    # Optionally link to customer
    customer_id = getattr(args, "customer_id", None)
    if customer_id:
        row = conn.execute(Q.from_(Table("customer")).select(Field("id")).where(Field("id") == P()).get_sql(), (customer_id,)).fetchone()
        if not row:
            err(f"Customer {customer_id} not found")

    # Encrypt SSN before storage
    raw_ssn = getattr(args, "ssn", None)
    encrypted_ssn, ssn_last4 = None, None
    if raw_ssn:
        encrypted_ssn, ssn_last4 = _encrypt_ssn(raw_ssn)

    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_patient", {"id": P(), "naming_series": P(), "customer_id": P(), "first_name": P(), "last_name": P(), "full_name": P(), "date_of_birth": P(), "gender": P(), "ssn": P(), "ssn_last4": P(), "mrn": P(), "marital_status": P(), "race": P(), "ethnicity": P(), "preferred_language": P(), "primary_phone": P(), "secondary_phone": P(), "email": P(), "address_line1": P(), "address_line2": P(), "city": P(), "state": P(), "zip_code": P(), "primary_provider_id": P(), "status": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        patient_id, mrn, customer_id,
        args.first_name, args.last_name, full_name,
        args.date_of_birth, args.gender,
        encrypted_ssn, ssn_last4, mrn,
        getattr(args, "marital_status", None),
        getattr(args, "race", None),
        getattr(args, "ethnicity", None),
        getattr(args, "preferred_language", None) or "English",
        getattr(args, "primary_phone", None),
        getattr(args, "secondary_phone", None),
        getattr(args, "email", None),
        getattr(args, "address_line1", None),
        getattr(args, "address_line2", None),
        getattr(args, "city", None),
        getattr(args, "state", None),
        getattr(args, "zip_code", None),
        provider_id,
        "active",
        getattr(args, "notes", None),
        args.company_id, _ts, _ts,
    ))
    audit(conn, "healthclaw_patient", patient_id, "health-add-patient", args.company_id)
    conn.commit()
    ok({"id": patient_id, "naming_series": mrn, "full_name": full_name, "mrn": mrn})


# ---------------------------------------------------------------------------
# 2. get-patient
# ---------------------------------------------------------------------------
def get_patient(conn, args):
    _validate_patient(conn, args.patient_id)
    row = conn.execute(Q.from_(Table("healthclaw_patient")).select(Table("healthclaw_patient").star).where(Field("id") == P()).get_sql(), (args.patient_id,)).fetchone()
    data = row_to_dict(row)
    _mask_ssn_in_row(data)

    # Enrich with counts
    _ins = Table("healthclaw_patient_insurance")
    ins_count = conn.execute(
        Q.from_(_ins).select(fn.Count("*")).where(_ins.patient_id == P()).where(_ins.status == "active").get_sql(),
        (args.patient_id,)
    ).fetchone()[0]
    _alg = Table("healthclaw_allergy")
    allergy_count = conn.execute(
        Q.from_(_alg).select(fn.Count("*")).where(_alg.patient_id == P()).where(_alg.status == "active").get_sql(),
        (args.patient_id,)
    ).fetchone()[0]
    data["active_insurance_count"] = ins_count
    data["active_allergy_count"] = allergy_count
    ok(data)


# ---------------------------------------------------------------------------
# 3. update-patient
# ---------------------------------------------------------------------------
def update_patient(conn, args):
    _validate_patient(conn, args.patient_id)

    data = {}
    changed = []

    # Handle SSN separately (needs encryption)
    raw_ssn = getattr(args, "ssn", None)
    if raw_ssn is not None:
        encrypted_ssn, ssn_last4 = _encrypt_ssn(raw_ssn)
        data["ssn"] = encrypted_ssn; changed.append("ssn")
        data["ssn_last4"] = ssn_last4; changed.append("ssn_last4")

    field_map = {
        "first_name": "first_name", "last_name": "last_name",
        "date_of_birth": "date_of_birth", "gender": "gender",
        "marital_status": "marital_status",
        "race": "race", "ethnicity": "ethnicity",
        "preferred_language": "preferred_language",
        "primary_phone": "primary_phone", "secondary_phone": "secondary_phone",
        "email": "email", "address_line1": "address_line1",
        "address_line2": "address_line2", "city": "city",
        "state": "state", "zip_code": "zip_code",
        "primary_provider_id": "primary_provider_id",
        "status": "status", "notes": "notes", "customer_id": "customer_id",
    }

    for arg_name, col_name in field_map.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            # Validate enums
            if col_name == "gender":
                _validate_enum(val, VALID_GENDERS, "gender")
            elif col_name == "status":
                _validate_enum(val, VALID_PATIENT_STATUSES, "status")
            elif col_name == "marital_status":
                _validate_enum(val, VALID_MARITAL_STATUSES, "health-marital-status")
            elif col_name == "ethnicity":
                _validate_enum(val, VALID_ETHNICITIES, "ethnicity")
            elif col_name == "primary_provider_id":
                row = conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (val,)).fetchone()
                if not row:
                    err(f"Provider (employee) {val} not found")
            elif col_name == "customer_id":
                row = conn.execute(Q.from_(Table("customer")).select(Field("id")).where(Field("id") == P()).get_sql(), (val,)).fetchone()
                if not row:
                    err(f"Customer {val} not found")
            data[col_name] = val
            changed.append(col_name)

    if not data:
        err("No fields to update")

    # Recompute full_name if first/last changed
    if "first_name" in changed or "last_name" in changed:
        row = conn.execute(Q.from_(Table("healthclaw_patient")).select(Field("first_name"), Field("last_name")).where(Field("id") == P()).get_sql(), (args.patient_id,)).fetchone()
        _fn = getattr(args, "first_name", None) or row[0]
        _ln = getattr(args, "last_name", None) or row[1]
        data["full_name"] = f"{_fn} {_ln}"

    data["updated_at"] = now()

    sql, params = dynamic_update("healthclaw_patient", data, {"id": args.patient_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_patient", args.patient_id, "health-update-patient", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": args.patient_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 4. list-patients
# ---------------------------------------------------------------------------
def list_patients(conn, args):
    t = Table("healthclaw_patient")
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
    if getattr(args, "primary_provider_id", None):
        q_count = q_count.where(t.primary_provider_id == P())
        q_rows = q_rows.where(t.primary_provider_id == P())
        params.append(args.primary_provider_id)
    if getattr(args, "search", None):
        s = f"%{args.search}%"
        crit = LiteralValue(f"(LOWER(\"full_name\") LIKE LOWER(?) OR LOWER(\"mrn\") LIKE LOWER(?) OR LOWER(\"email\") LIKE LOWER(?))")
        q_count = q_count.where(crit)
        q_rows = q_rows.where(crit)
        params.extend([s, s, s])

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]

    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [_mask_ssn_in_row(row_to_dict(r)) for r in rows],
        "total_count": total,
        "limit": args.limit,
        "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 5. add-patient-insurance
# ---------------------------------------------------------------------------
def add_patient_insurance(conn, args):
    _validate_patient(conn, args.patient_id)
    _validate_company(conn, args.company_id)

    if not args.payer_name:
        err("--payer-name is required")
    if not args.member_id:
        err("--member-id is required")
    if not args.effective_date:
        err("--effective-date is required")

    insurance_type = getattr(args, "insurance_type", None) or "primary"
    _validate_enum(insurance_type, VALID_INSURANCE_TYPES, "health-insurance-type")
    plan_type = getattr(args, "plan_type", None)
    _validate_enum(plan_type, VALID_PLAN_TYPES, "health-plan-type")
    sub_rel = getattr(args, "subscriber_relationship", None) or "self"
    _validate_enum(sub_rel, VALID_SUBSCRIBER_RELATIONSHIPS, "health-subscriber-relationship")

    ins_id = str(uuid.uuid4())
    naming = get_next_name(conn, "healthclaw_patient_insurance", company_id=args.company_id)
    _ts = _now_iso()

    sql, _ = insert_row("healthclaw_patient_insurance", {"id": P(), "naming_series": P(), "patient_id": P(), "insurance_type": P(), "payer_name": P(), "payer_id": P(), "plan_name": P(), "plan_type": P(), "group_number": P(), "member_id": P(), "subscriber_name": P(), "subscriber_dob": P(), "subscriber_relationship": P(), "copay_amount": P(), "deductible": P(), "deductible_met": P(), "out_of_pocket_max": P(), "effective_date": P(), "termination_date": P(), "preauth_required": P(), "status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})


    conn.execute(sql, (
        ins_id, naming, args.patient_id, insurance_type,
        args.payer_name, getattr(args, "payer_id", None),
        getattr(args, "plan_name", None), plan_type,
        getattr(args, "group_number", None), args.member_id,
        getattr(args, "subscriber_name", None),
        getattr(args, "subscriber_dob", None), sub_rel,
        str(round_currency(to_decimal(getattr(args, "copay_amount", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "deductible", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "deductible_met", None) or "0"))),
        str(round_currency(to_decimal(getattr(args, "out_of_pocket_max", None) or "0"))),
        args.effective_date,
        getattr(args, "termination_date", None),
        1 if getattr(args, "preauth_required", None) == "1" else 0,
        "active", args.company_id, _ts, _ts,
    ))
    audit(conn, "healthclaw_patient_insurance", ins_id, "health-add-patient-insurance", args.company_id)
    conn.commit()
    ok({"id": ins_id, "naming_series": naming, "insurance_type": insurance_type})


# ---------------------------------------------------------------------------
# 6. update-patient-insurance
# ---------------------------------------------------------------------------
def update_patient_insurance(conn, args):
    ins_id = getattr(args, "insurance_id", None)
    if not ins_id:
        err("--insurance-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_patient_insurance")).select(Field("id")).where(Field("id") == P()).get_sql(), (ins_id,)).fetchone()
    if not row:
        err(f"Insurance {ins_id} not found")

    data = {}
    changed = []
    field_map = {
        "insurance_type": "insurance_type", "payer_name": "payer_name",
        "payer_id": "payer_id", "plan_name": "plan_name", "plan_type": "plan_type",
        "group_number": "group_number", "member_id": "member_id",
        "subscriber_name": "subscriber_name", "subscriber_dob": "subscriber_dob",
        "subscriber_relationship": "subscriber_relationship",
        "effective_date": "effective_date", "termination_date": "termination_date",
        "status": "status",
    }
    money_fields = {"copay_amount", "deductible", "deductible_met", "out_of_pocket_max"}

    for arg_name, col_name in field_map.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            if col_name == "insurance_type":
                _validate_enum(val, VALID_INSURANCE_TYPES, "health-insurance-type")
            elif col_name == "plan_type":
                _validate_enum(val, VALID_PLAN_TYPES, "health-plan-type")
            elif col_name == "subscriber_relationship":
                _validate_enum(val, VALID_SUBSCRIBER_RELATIONSHIPS, "health-subscriber-relationship")
            elif col_name == "status":
                _validate_enum(val, VALID_INSURANCE_STATUSES, "status")
            data[col_name] = val
            changed.append(col_name)

    for mf in money_fields:
        val = getattr(args, mf, None)
        if val is not None:
            data[mf] = str(round_currency(to_decimal(val)))
            changed.append(mf)

    if getattr(args, "preauth_required", None) is not None:
        data["preauth_required"] = 1 if args.preauth_required == "1" else 0
        changed.append("preauth_required")

    if not data:
        err("No fields to update")

    data["updated_at"] = now()
    sql, params = dynamic_update("healthclaw_patient_insurance", data, {"id": ins_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_patient_insurance", ins_id, "health-update-patient-insurance", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": ins_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 7. list-patient-insurances
# ---------------------------------------------------------------------------
def list_patient_insurances(conn, args):
    t = Table("healthclaw_patient_insurance")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P())
        q_rows = q_rows.where(t.patient_id == P())
        params.append(args.patient_id)
    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "status", None):
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(args.status)
    if getattr(args, "insurance_type", None):
        q_count = q_count.where(t.insurance_type == P())
        q_rows = q_rows.where(t.insurance_type == P())
        params.append(args.insurance_type)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.insurance_type, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 8. add-allergy
# ---------------------------------------------------------------------------
def add_allergy(conn, args):
    _validate_patient(conn, args.patient_id)
    if not args.allergen:
        err("--allergen is required")
    allergen_type = getattr(args, "allergen_type", None) or "other"
    _validate_enum(allergen_type, VALID_ALLERGEN_TYPES, "health-allergen-type")
    severity = getattr(args, "severity", None) or "moderate"
    _validate_enum(severity, VALID_SEVERITIES, "severity")

    noted_by = getattr(args, "noted_by_id", None)
    if noted_by:
        row = conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (noted_by,)).fetchone()
        if not row:
            err(f"Employee {noted_by} not found")

    allergy_id = str(uuid.uuid4())
    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_allergy", {"id": P(), "patient_id": P(), "allergen": P(), "allergen_type": P(), "reaction": P(), "severity": P(), "onset_date": P(), "status": P(), "noted_by_id": P(), "notes": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        allergy_id, args.patient_id, args.allergen, allergen_type,
        getattr(args, "reaction", None), severity,
        getattr(args, "onset_date", None), "active",
        noted_by, getattr(args, "notes", None), _ts, _ts,
    ))
    audit(conn, "healthclaw_allergy", allergy_id, "health-add-allergy", None)
    conn.commit()
    ok({"id": allergy_id, "allergen": args.allergen, "severity": severity})


# ---------------------------------------------------------------------------
# 9. update-allergy
# ---------------------------------------------------------------------------
def update_allergy(conn, args):
    allergy_id = getattr(args, "allergy_id", None)
    if not allergy_id:
        err("--allergy-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_allergy")).select(Field("id")).where(Field("id") == P()).get_sql(), (allergy_id,)).fetchone()
    if not row:
        err(f"Allergy {allergy_id} not found")

    data = {}
    changed = []
    for arg_name, col_name in {
        "allergen": "allergen", "allergen_type": "allergen_type",
        "reaction": "reaction", "severity": "severity",
        "onset_date": "onset_date", "status": "status", "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            if col_name == "allergen_type":
                _validate_enum(val, VALID_ALLERGEN_TYPES, "health-allergen-type")
            elif col_name == "severity":
                _validate_enum(val, VALID_SEVERITIES, "severity")
            elif col_name == "status":
                _validate_enum(val, VALID_ALLERGY_STATUSES, "status")
            data[col_name] = val
            changed.append(col_name)

    if not data:
        err("No fields to update")

    data["updated_at"] = now()
    sql, params = dynamic_update("healthclaw_allergy", data, {"id": allergy_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_allergy", allergy_id, "health-update-allergy", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": allergy_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 10. list-allergies
# ---------------------------------------------------------------------------
def list_allergies(conn, args):
    t = Table("healthclaw_allergy")
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
    if getattr(args, "allergen_type", None):
        q_count = q_count.where(t.allergen_type == P())
        q_rows = q_rows.where(t.allergen_type == P())
        params.append(args.allergen_type)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 11. add-medical-history
# ---------------------------------------------------------------------------
def add_medical_history(conn, args):
    _validate_patient(conn, args.patient_id)
    condition = getattr(args, "condition", None)
    if not condition:
        err("--condition is required")

    medhist_id = str(uuid.uuid4())
    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_medical_history", {"id": P(), "patient_id": P(), "condition": P(), "icd10_code": P(), "diagnosis_date": P(), "resolution_date": P(), "status": P(), "notes": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        medhist_id, args.patient_id, condition,
        getattr(args, "icd10_code", None),
        getattr(args, "diagnosis_date", None),
        getattr(args, "resolution_date", None),
        getattr(args, "medhist_status", None) or "active",
        getattr(args, "notes", None), _ts, _ts,
    ))
    audit(conn, "healthclaw_medical_history", medhist_id, "health-add-medical-history", None)
    conn.commit()
    ok({"id": medhist_id, "condition": condition})


# ---------------------------------------------------------------------------
# 12. update-medical-history
# ---------------------------------------------------------------------------
def update_medical_history(conn, args):
    mh_id = getattr(args, "medical_history_id", None)
    if not mh_id:
        err("--medical-history-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_medical_history")).select(Field("id")).where(Field("id") == P()).get_sql(), (mh_id,)).fetchone()
    if not row:
        err(f"Medical history {mh_id} not found")

    data = {}
    changed = []
    for arg_name, col_name in {
        "condition": "condition", "icd10_code": "icd10_code",
        "diagnosis_date": "diagnosis_date", "resolution_date": "resolution_date",
        "medhist_status": "status", "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            if col_name == "status":
                _validate_enum(val, VALID_MEDHIST_STATUSES, "status")
            data[col_name] = val
            changed.append(col_name)

    if not data:
        err("No fields to update")

    data["updated_at"] = now()
    sql, params = dynamic_update("healthclaw_medical_history", data, {"id": mh_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_medical_history", mh_id, "health-update-medical-history", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": mh_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 13. list-medical-history
# ---------------------------------------------------------------------------
def list_medical_history(conn, args):
    t = Table("healthclaw_medical_history")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "patient_id", None):
        q_count = q_count.where(t.patient_id == P())
        q_rows = q_rows.where(t.patient_id == P())
        params.append(args.patient_id)
    if getattr(args, "medhist_status", None):
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(args.medhist_status)
    if getattr(args, "search", None):
        s = f"%{args.search}%"
        crit = LiteralValue(f"(LOWER(\"condition\") LIKE LOWER(?) OR LOWER(\"icd10_code\") LIKE LOWER(?))")
        q_count = q_count.where(crit)
        q_rows = q_rows.where(crit)
        params.extend([s, s])

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 14. add-patient-contact
# ---------------------------------------------------------------------------
def add_patient_contact(conn, args):
    _validate_patient(conn, args.patient_id)
    contact_name = getattr(args, "contact_name", None)
    if not contact_name:
        err("--contact-name is required")
    contact_type = getattr(args, "contact_type", None) or "emergency"
    _validate_enum(contact_type, VALID_CONTACT_TYPES, "health-contact-type")

    contact_id = str(uuid.uuid4())
    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_patient_contact", {"id": P(), "patient_id": P(), "contact_type": P(), "name": P(), "relationship": P(), "phone": P(), "email": P(), "address": P(), "is_primary": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        contact_id, args.patient_id, contact_type, contact_name,
        getattr(args, "relationship", None),
        getattr(args, "contact_phone", None),
        getattr(args, "contact_email", None),
        getattr(args, "contact_address", None),
        1 if getattr(args, "is_primary", None) == "1" else 0,
        _ts, _ts,
    ))
    audit(conn, "healthclaw_patient_contact", contact_id, "health-add-patient-contact", None)
    conn.commit()
    ok({"id": contact_id, "name": contact_name, "contact_type": contact_type})


# ---------------------------------------------------------------------------
# 15. update-patient-contact
# ---------------------------------------------------------------------------
def update_patient_contact(conn, args):
    contact_id = getattr(args, "contact_id", None)
    if not contact_id:
        err("--contact-id is required")
    row = conn.execute(Q.from_(Table("healthclaw_patient_contact")).select(Field("id")).where(Field("id") == P()).get_sql(), (contact_id,)).fetchone()
    if not row:
        err(f"Contact {contact_id} not found")

    data = {}
    changed = []
    for arg_name, col_name in {
        "contact_type": "contact_type", "contact_name": "name",
        "relationship": "relationship", "contact_phone": "phone",
        "contact_email": "email", "contact_address": "address",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            if col_name == "contact_type":
                _validate_enum(val, VALID_CONTACT_TYPES, "health-contact-type")
            data[col_name] = val
            changed.append(col_name)

    if getattr(args, "is_primary", None) is not None:
        data["is_primary"] = 1 if args.is_primary == "1" else 0
        changed.append("is_primary")

    if not data:
        err("No fields to update")

    data["updated_at"] = now()
    sql, params = dynamic_update("healthclaw_patient_contact", data, {"id": contact_id})
    conn.execute(sql, params)
    audit(conn, "healthclaw_patient_contact", contact_id, "health-update-patient-contact", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": contact_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 16. add-consent
# ---------------------------------------------------------------------------
def add_consent(conn, args):
    _validate_patient(conn, args.patient_id)
    _validate_company(conn, args.company_id)

    consent_type = getattr(args, "consent_type", None)
    if not consent_type:
        err("--consent-type is required")
    _validate_enum(consent_type, VALID_CONSENT_TYPES, "health-consent-type")

    granted_date = getattr(args, "granted_date", None)
    if not granted_date:
        err("--granted-date is required")

    obtained_by = getattr(args, "obtained_by_id", None)
    if obtained_by:
        row = conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (obtained_by,)).fetchone()
        if not row:
            err(f"Employee {obtained_by} not found")

    consent_id = str(uuid.uuid4())
    _ts = _now_iso()
    sql, _ = insert_row("healthclaw_consent", {"id": P(), "patient_id": P(), "consent_type": P(), "description": P(), "granted_date": P(), "expiration_date": P(), "revoked_date": P(), "status": P(), "witness_name": P(), "obtained_by_id": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})

    conn.execute(sql, (
        consent_id, args.patient_id, consent_type,
        getattr(args, "description", None), granted_date,
        getattr(args, "expiration_date", None), None,
        "active",
        getattr(args, "witness_name", None),
        obtained_by,
        getattr(args, "notes", None),
        args.company_id, _ts, _ts,
    ))
    audit(conn, "healthclaw_consent", consent_id, "health-add-consent", args.company_id)
    conn.commit()
    ok({"id": consent_id, "consent_type": consent_type, "status": "active"})


# ===========================================================================
# H42: Patient Merge
# ===========================================================================

# Tables with patient_id FK that need to be repointed during merge
_PATIENT_FK_TABLES = [
    "healthclaw_patient_insurance",
    "healthclaw_allergy",
    "healthclaw_medical_history",
    "healthclaw_consent",
    "healthclaw_appointment",
    "healthclaw_encounter",
    "healthclaw_vitals",
    "healthclaw_diagnosis",
    "healthclaw_prescription",
    "healthclaw_procedure",
    "healthclaw_clinical_note",
    "healthclaw_charge",
    "healthclaw_claim",
    "healthclaw_payment_posting",
    "healthclaw_lab_order",
    "healthclaw_referral",
    "healthclaw_patient_contact",
    "healthclaw_med_reconciliation",
    "healthclaw_immunization",
]


def merge_patients(conn, args):
    """Merge source patient into target patient.

    Repoints ALL FK references from source to target across all healthclaw tables,
    then soft-deletes the source patient (status='inactive', notes='merged into {target}').
    """
    source_id = getattr(args, "source_patient_id", None)
    target_id = getattr(args, "target_patient_id", None)
    if not source_id:
        err("--source-patient-id is required")
    if not target_id:
        err("--target-patient-id is required")
    if source_id == target_id:
        err("Source and target patient cannot be the same")

    # Validate both patients exist
    _validate_patient(conn, source_id)
    _validate_patient(conn, target_id)

    # Check source is not already inactive
    pat_t = Table("healthclaw_patient")
    source_row = conn.execute(
        Q.from_(pat_t).select(pat_t.status, pat_t.full_name)
        .where(pat_t.id == P()).get_sql(), (source_id,)
    ).fetchone()
    if source_row[0] == "inactive":
        err(f"Source patient {source_id} is already inactive (may have been merged previously)")

    target_row = conn.execute(
        Q.from_(pat_t).select(pat_t.full_name)
        .where(pat_t.id == P()).get_sql(), (target_id,)
    ).fetchone()

    source_name = source_row[1]
    target_name = target_row[0]

    # Repoint all FK references within a single transaction
    repoint_counts = {}
    for table_name in _PATIENT_FK_TABLES:
        # Check if table exists (some Phase 8 tables may not exist in older schemas)
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        ).fetchone()
        if not table_exists:
            continue

        t = Table(table_name)
        count = conn.execute(
            Q.from_(t).select(fn.Count("*")).where(t.patient_id == P()).get_sql(),
            (source_id,)
        ).fetchone()[0]
        if count > 0:
            sql, params = dynamic_update(table_name, {"patient_id": target_id}, {"patient_id": source_id})
            conn.execute(sql, params)
            repoint_counts[table_name] = count

    # Soft-delete source patient
    merge_note = f"Merged into patient {target_id} ({target_name}) on {_now_iso()}"
    upd_data = {
        "status": "inactive",
        "notes": merge_note,
        "updated_at": now(),
    }
    sql, params = dynamic_update("healthclaw_patient", upd_data, {"id": source_id})
    conn.execute(sql, params)

    audit(conn, "healthclaw_patient", source_id, "health-merge-patients", None, {
        "source_id": source_id, "target_id": target_id,
        "repoint_counts": repoint_counts,
    })
    audit(conn, "healthclaw_patient", target_id, "health-merge-patients-target", None, {
        "source_id": source_id, "merged_from": source_name,
    })
    conn.commit()

    total_repointed = sum(repoint_counts.values())
    ok({
        "source_patient_id": source_id,
        "target_patient_id": target_id,
        "source_name": source_name,
        "target_name": target_name,
        "total_records_repointed": total_repointed,
        "repoint_details": repoint_counts,
        "source_status": "inactive",
    })


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-add-patient": add_patient,
    "health-get-patient": get_patient,
    "health-update-patient": update_patient,
    "health-list-patients": list_patients,
    "health-add-patient-insurance": add_patient_insurance,
    "health-update-patient-insurance": update_patient_insurance,
    "health-list-patient-insurances": list_patient_insurances,
    "health-add-allergy": add_allergy,
    "health-update-allergy": update_allergy,
    "health-list-allergies": list_allergies,
    "health-add-medical-history": add_medical_history,
    "health-update-medical-history": update_medical_history,
    "health-list-medical-history": list_medical_history,
    "health-add-patient-contact": add_patient_contact,
    "health-update-patient-contact": update_patient_contact,
    "health-add-consent": add_consent,
    # H42: Patient Merge
    "health-merge-patients": merge_patients,
}
