"""HealthClaw 340B accumulator — local eligibility and accumulation register.

Records qualified dispense rows after explicit validation and reports exact
acquisition and ceiling values. This is a local register only: it makes no
legal eligibility determination and never transmits a claim.
"""
import hashlib
import json
import os
import sys
import uuid
from decimal import Decimal

try:
    import importlib.util
    if importlib.util.find_spec("erpclaw_lib") is None:
        sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row
except ImportError:
    pass

SKILL = "healthclaw"

ACCUM_TABLE = "healthclaw_340b_accumulation"
IDEM_TABLE = "healthclaw_340b_idempotency_key"

CANONICAL_RECORD = "health-record-340b-dispense"
CANONICAL_LIST = "health-list-340b-dispenses"
CANONICAL_GET = "health-get-340b-dispense"


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pick(args, *names):
    for name in names:
        value = getattr(args, name, None)
        if value is not None and value != "":
            return value
    return None


def _norm_money(value, label):
    try:
        amount = round_currency(to_decimal(value))
    except (TypeError, ValueError) as exc:
        err("Invalid %s: %r" % (label, value))
    return amount


def _norm_quantity(value):
    try:
        qty = to_decimal(value)
    except (TypeError, ValueError):
        err("Invalid quantity: %r" % (value,))
    return qty


def _request_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _row_to_receipt(row):
    data = row_to_dict(row)
    return {
        "id": data.get("id"),
        "company_id": data.get("company_id"),
        "encounter_id": data.get("encounter_id"),
        "patient_id": data.get("patient_id"),
        "drug_identifier": data.get("drug_identifier"),
        "quantity": data.get("quantity"),
        "dispense_date": data.get("dispense_date"),
        "qualification_reason": data.get("qualification_reason"),
        "evidence_reference": data.get("evidence_reference"),
        "acquisition_cost": data.get("acquisition_cost"),
        "ceiling_price": data.get("ceiling_price"),
        "ceiling_value": data.get("ceiling_price"),
        "idempotency_key": data.get("idempotency_key"),
        "created_at": data.get("created_at"),
    }


def record_340b_dispense(conn, args, _action=CANONICAL_RECORD):
    company_id = getattr(args, "company_id", None)
    encounter_id = getattr(args, "encounter_id", None)
    drug_identifier = _pick(args, "drug_identifier", "drug_code", "ndc_code", "ndc")
    quantity_raw = _pick(args, "quantity", "quantity_dispensed")
    dispense_date = _pick(args, "dispense_date", "dispensed_date")
    qualification_reason = _pick(args, "qualification_reason", "qualification_code")
    evidence_reference = _pick(
        args, "evidence_reference", "evidence_id", "supporting_evidence", "evidence_note", "evidence")
    acquisition_raw = _pick(
        args, "acquisition_cost", "acquisition_price", "acquisition_amount")
    ceiling_raw = _pick(
        args, "ceiling_price", "ceiling_value", "ceiling_amount")
    idempotency_key = _pick(args, "idempotency_key", "request_id")

    if not company_id:
        err("--company-id is required")
    if not encounter_id:
        err("--encounter-id is required")
    if drug_identifier is None:
        err("--drug-identifier is required")
    if quantity_raw is None:
        err("--quantity is required")
    if dispense_date is None:
        err("--dispense-date is required")
    if qualification_reason is None:
        err("--qualification-reason is required")
    if evidence_reference is None:
        err("--evidence-reference is required: qualification evidence is required")
    if isinstance(evidence_reference, str) and not evidence_reference.strip():
        conn.rollback()
        err("--evidence-reference is required: qualification evidence is required")
    if acquisition_raw is None:
        err("--acquisition-cost is required")
    if ceiling_raw is None:
        err("--ceiling-price is required")

    quantity = _norm_quantity(quantity_raw)
    if quantity <= Decimal("0"):
        conn.rollback()
        err("Quantity must be positive, got %r" % (quantity_raw,))
    quantity_str = format(quantity, "f")

    acquisition = _norm_money(acquisition_raw, "acquisition cost")
    ceiling = _norm_money(ceiling_raw, "ceiling value")
    if acquisition < Decimal("0") or ceiling < Decimal("0"):
        conn.rollback()
        err("Negative money is not allowed: acquisition %r ceiling %r" % (
            acquisition_raw, ceiling_raw))
    acquisition_str = str(acquisition)
    ceiling_str = str(ceiling)
    if acquisition > ceiling:
        conn.rollback()
        err("Acquisition cost %s exceeds ceiling value %s" % (
            acquisition_str, ceiling_str))

    encounter_row = conn.execute(
        Q.from_(Table("healthclaw_encounter")).select(
            Table("healthclaw_encounter").star).where(
            Field("id") == P()).get_sql(),
        (encounter_id,)).fetchone()
    if not encounter_row:
        conn.rollback()
        err("Encounter %s not found" % (encounter_id,))
    encounter = row_to_dict(encounter_row)
    if encounter.get("company_id") != company_id:
        conn.rollback()
        err("Encounter %s belongs to company %s, not %s" % (
            encounter_id, encounter.get("company_id"), company_id))
    patient_id = encounter.get("patient_id")

    payload = {
        "company_id": company_id,
        "encounter_id": encounter_id,
        "drug_identifier": str(drug_identifier),
        "quantity": quantity_str,
        "dispense_date": str(dispense_date),
        "qualification_reason": str(qualification_reason),
        "evidence_reference": str(evidence_reference),
        "acquisition_cost": acquisition_str,
        "ceiling_price": ceiling_str,
    }
    digest = _request_hash(payload)

    if idempotency_key is not None:
        idempotency_key = str(idempotency_key)
        existing = conn.execute(
            Q.from_(Table(IDEM_TABLE)).select(
                Table(IDEM_TABLE).star).where(
                Field("company_id") == P()).where(
                Field("idempotency_key") == P()).get_sql(),
            (company_id, idempotency_key)).fetchone()
        if existing is not None:
            stored = row_to_dict(existing)
            if stored.get("request_hash") != digest:
                conn.rollback()
                err("Idempotency key %s already used with conflicting fields; refusing changed retry" % (
                    idempotency_key,))
            row = conn.execute(
                Q.from_(Table(ACCUM_TABLE)).select(
                    Table(ACCUM_TABLE).star).where(
                    Field("id") == P()).get_sql(),
                (stored.get("accumulation_id"),)).fetchone()
            if row is None:
                conn.rollback()
                err("Idempotency key %s points at missing row" % (
                    idempotency_key,))
            ok(_row_to_receipt(row))

    row_id = str(uuid.uuid4())
    created = _now_iso()
    try:
        sql, _ = insert_row(ACCUM_TABLE, {
            "id": P(), "company_id": P(), "encounter_id": P(),
            "patient_id": P(), "drug_identifier": P(), "quantity": P(),
            "dispense_date": P(), "qualification_reason": P(),
            "evidence_reference": P(), "acquisition_cost": P(),
            "ceiling_price": P(), "idempotency_key": P(),
            "created_at": P()})
        conn.execute(sql, (
            row_id, company_id, encounter_id, patient_id,
            str(drug_identifier), quantity_str, str(dispense_date),
            str(qualification_reason), str(evidence_reference),
            acquisition_str, ceiling_str, idempotency_key, created))
        if idempotency_key is not None:
            key_sql, _ = insert_row(IDEM_TABLE, {
                "id": P(), "company_id": P(), "idempotency_key": P(),
                "accumulation_id": P(), "request_hash": P(),
                "created_at": P()})
            conn.execute(key_sql, (
                str(uuid.uuid4()), company_id, idempotency_key,
                row_id, digest, created))
        audit(conn, SKILL, _action, ACCUM_TABLE, row_id,
              new_values={
                  "company_id": company_id, "encounter_id": encounter_id,
                  "patient_id": patient_id,
                  "drug_identifier": str(drug_identifier),
                  "quantity": quantity_str,
                  "dispense_date": str(dispense_date),
                  "qualification_reason": str(qualification_reason),
                  "evidence_reference": str(evidence_reference),
                  "acquisition_cost": acquisition_str,
                  "ceiling_price": ceiling_str,
                  "ceiling_value": ceiling_str,
                  "idempotency_key": idempotency_key})
    except SystemExit:
        raise
    except Exception as exc:
        conn.rollback()
        err("Failed to record 340B dispense: %s" % (exc,))
    conn.commit()
    ok({
        "id": row_id,
        "company_id": company_id,
        "encounter_id": encounter_id,
        "patient_id": patient_id,
        "drug_identifier": str(drug_identifier),
        "quantity": quantity_str,
        "dispense_date": str(dispense_date),
        "qualification_reason": str(qualification_reason),
        "evidence_reference": str(evidence_reference),
        "acquisition_cost": acquisition_str,
        "ceiling_price": ceiling_str,
        "ceiling_value": ceiling_str,
        "idempotency_key": idempotency_key,
        "created_at": created,
    })


def list_340b_dispenses(conn, args, _action=CANONICAL_LIST):
    table = Table(ACCUM_TABLE)
    query_count = Q.from_(table).select(fn.Count("*"))
    query_rows = Q.from_(table).select(table.star)
    params = []
    company_id = getattr(args, "company_id", None)
    if company_id:
        query_count = query_count.where(table.company_id == P())
        query_rows = query_rows.where(table.company_id == P())
        params.append(company_id)
    encounter_id = getattr(args, "encounter_id", None)
    if encounter_id:
        query_count = query_count.where(table.encounter_id == P())
        query_rows = query_rows.where(table.encounter_id == P())
        params.append(encounter_id)
    drug_identifier = _pick(args, "drug_identifier", "drug_code", "ndc_code", "ndc")
    if drug_identifier is not None:
        query_count = query_count.where(table.drug_identifier == P())
        query_rows = query_rows.where(table.drug_identifier == P())
        params.append(str(drug_identifier))
    total = conn.execute(query_count.get_sql(), params).fetchone()[0]
    limit = getattr(args, "limit", None) or 50
    offset = getattr(args, "offset", None) or 0
    query_rows = query_rows.orderby(
        table.dispense_date, order=Order.asc).orderby(
        table.id, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(
        query_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"rows": [_row_to_receipt(r) for r in rows],
        "total_count": total, "limit": limit, "offset": offset,
        "has_more": (offset + limit) < total})


def get_340b_dispense(conn, args, _action=CANONICAL_GET):
    row_id = _pick(args, "accumulation_id", "dispense_id", "id_340b", "id")
    if row_id is None:
        row_id = getattr(args, "accumulation_id", None) or getattr(
            args, "dispense_id", None) or getattr(args, "id", None)
    record_id = _pick(args, "record_id", "row_id")
    if row_id is None:
        row_id = record_id
    if row_id is None:
        err("--accumulation-id is required")
    row = conn.execute(
        Q.from_(Table(ACCUM_TABLE)).select(
            Table(ACCUM_TABLE).star).where(
            Field("id") == P()).get_sql(),
        (row_id,)).fetchone()
    if row is None:
        err("340B accumulation %s not found" % (row_id,))
    data = _row_to_receipt(row)
    company_id = getattr(args, "company_id", None)
    if company_id and data.get("company_id") != company_id:
        err("340B accumulation %s belongs to company %s, not %s" % (
            row_id, data.get("company_id"), company_id))
    ok(data)


def _record_alias_canonical(conn, args):
    return record_340b_dispense(conn, args, _action=CANONICAL_RECORD)


def _make_record_alias(name):
    def _alias(conn, args, _name=name):
        return record_340b_dispense(conn, args, _action=_name)
    _alias.__name__ = "record_alias_" + name.replace("-", "_")
    return _alias


def _make_list_alias(name):
    def _alias(conn, args, _name=name):
        return list_340b_dispenses(conn, args, _action=_name)
    _alias.__name__ = "list_alias_" + name.replace("-", "_")
    return _alias


def _make_get_alias(name):
    def _alias(conn, args, _name=name):
        return get_340b_dispense(conn, args, _action=_name)
    _alias.__name__ = "get_alias_" + name.replace("-", "_")
    return _alias


ACTIONS = {
    "health-record-340b-dispense": _record_alias_canonical,
    "health-add-340b-accumulation": _make_record_alias("health-add-340b-accumulation"),
    "health-record-340b-accumulation": _make_record_alias("health-record-340b-accumulation"),
    "health-list-340b-dispenses": list_340b_dispenses,
    "health-list-340b-accumulations": _make_list_alias("health-list-340b-accumulations"),
    "health-get-340b-dispense": get_340b_dispense,
    "health-get-340b-accumulation": _make_get_alias("health-get-340b-accumulation"),
}
