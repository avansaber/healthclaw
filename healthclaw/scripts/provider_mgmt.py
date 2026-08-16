"""HealthClaw — Provider Management domain module

Actions for provider credentialing (H19) (1 table, 4 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

try:
    import importlib.util
    if importlib.util.find_spec("erpclaw_lib") is None:
        sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_CREDENTIAL_TYPES = (
    "medical_license", "dea", "npi", "board_certification",
    "malpractice_insurance", "cds", "state_license", "other",
)
VALID_CREDENTIAL_STATUSES = ("active", "expired", "pending", "revoked")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


def _validate_provider(conn, provider_id):
    if not provider_id:
        err("--provider-id is required")
    if not conn.execute(Q.from_(Table("employee")).select(Field("id")).where(Field("id") == P()).get_sql(), (provider_id,)).fetchone():
        err(f"Provider (employee) {provider_id} not found")


# ---------------------------------------------------------------------------
# 1. add-provider-credential
# ---------------------------------------------------------------------------
def add_provider_credential(conn, args):
    """Create a provider credential record."""
    if not args.company_id:
        err("--company-id is required")
    _validate_provider(conn, args.provider_id)

    credential_type = getattr(args, "credential_type", None)
    if not credential_type:
        err("--credential-type is required")
    _validate_enum(credential_type, VALID_CREDENTIAL_TYPES, "credential-type")

    cred_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("healthclaw_provider_credential", {
        "id": P(), "provider_id": P(), "credential_type": P(),
        "credential_number": P(), "issuing_authority": P(),
        "issue_date": P(), "expiration_date": P(), "status": P(),
        "verification_date": P(), "verified_by": P(), "notes": P(),
        "company_id": P(), "created_at": P(), "updated_at": P(),
    })
    conn.execute(sql, (
        cred_id, args.provider_id, credential_type,
        getattr(args, "credential_number", None),
        getattr(args, "issuing_authority", None),
        getattr(args, "issue_date", None),
        getattr(args, "expiration_date", None),
        "active",
        getattr(args, "verification_date", None),
        getattr(args, "verified_by", None),
        getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "healthclaw_provider_credential", cred_id, "health-add-provider-credential", args.company_id)
    conn.commit()
    ok({"id": cred_id, "provider_id": args.provider_id, "credential_type": credential_type, "credential_status": "active"})


# ---------------------------------------------------------------------------
# 2. list-provider-credentials
# ---------------------------------------------------------------------------
def list_provider_credentials(conn, args):
    """List credentials for a provider."""
    t = Table("healthclaw_provider_credential")
    q_count = Q.from_(t).select(fn.Count("*"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    if getattr(args, "provider_id", None):
        q_count = q_count.where(t.provider_id == P())
        q_rows = q_rows.where(t.provider_id == P())
        params.append(args.provider_id)
    if getattr(args, "company_id", None):
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "credential_type", None):
        q_count = q_count.where(t.credential_type == P())
        q_rows = q_rows.where(t.credential_type == P())
        params.append(args.credential_type)
    if getattr(args, "status", None):
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(args.status)

    total = conn.execute(q_count.get_sql(), params).fetchone()[0]
    q_rows = q_rows.orderby(t.expiration_date, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# 3. check-expiring-credentials
# ---------------------------------------------------------------------------
def check_expiring_credentials(conn, args):
    """Check for credentials expiring within N days (default 90)."""
    if not args.company_id:
        err("--company-id is required")

    days = int(getattr(args, "days", None) or 90)
    cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    t = Table("healthclaw_provider_credential")
    q = (Q.from_(t).select(t.star)
         .where(t.company_id == P())
         .where(t.status == P())
         .where(t.expiration_date.isnotnull())
         .where(t.expiration_date <= P())
         .orderby(t.expiration_date, order=Order.asc))

    rows = conn.execute(q.get_sql(), (args.company_id, "active", cutoff)).fetchall()

    expiring = []
    already_expired = []
    for r in rows:
        data = row_to_dict(r)
        exp_date = data.get("expiration_date", "")
        entry = {
            "id": data["id"],
            "provider_id": data["provider_id"],
            "credential_type": data["credential_type"],
            "credential_number": data.get("credential_number"),
            "expiration_date": exp_date,
        }
        if exp_date < today:
            already_expired.append(entry)
        else:
            expiring.append(entry)

    ok({
        "company_id": args.company_id,
        "check_window_days": days,
        "cutoff_date": cutoff,
        "expiring_count": len(expiring),
        "expired_count": len(already_expired),
        "expiring": expiring,
        "already_expired": already_expired,
    })


# ---------------------------------------------------------------------------
# 4. provider-credential-report
# ---------------------------------------------------------------------------
def provider_credential_report(conn, args):
    """Full credential status report for a provider."""
    _validate_provider(conn, args.provider_id)

    t = Table("healthclaw_provider_credential")
    rows = conn.execute(
        Q.from_(t).select(t.star)
        .where(t.provider_id == P())
        .orderby(t.credential_type, order=Order.asc)
        .get_sql(),
        (args.provider_id,)
    ).fetchall()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    credentials = []
    active_count = 0
    expired_count = 0
    pending_count = 0

    for r in rows:
        data = row_to_dict(r)
        cred_status = data.get("status", "active")
        exp_date = data.get("expiration_date")

        # Auto-detect expired (expiration_date in the past but status still active)
        if cred_status == "active" and exp_date and exp_date < today:
            cred_status = "expired"

        if cred_status == "active":
            active_count += 1
        elif cred_status == "expired":
            expired_count += 1
        elif cred_status == "pending":
            pending_count += 1

        credentials.append({
            "id": data["id"],
            "credential_type": data["credential_type"],
            "credential_number": data.get("credential_number"),
            "issuing_authority": data.get("issuing_authority"),
            "issue_date": data.get("issue_date"),
            "expiration_date": exp_date,
            "status": cred_status,
            "verification_date": data.get("verification_date"),
        })

    ok({
        "provider_id": args.provider_id,
        "total_credentials": len(credentials),
        "active": active_count,
        "expired": expired_count,
        "pending": pending_count,
        "credentials": credentials,
    })


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-add-provider-credential": add_provider_credential,
    "health-list-provider-credentials": list_provider_credentials,
    "health-check-expiring-credentials": check_expiring_credentials,
    "health-provider-credential-report": provider_credential_report,
}
