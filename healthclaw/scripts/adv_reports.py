"""HealthClaw Advanced — reports domain module.

Cross-domain reporting actions.
Imported by db_query.py (unified router).
"""
import os
import sys
from decimal import Decimal

try:
    sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row
except ImportError:
    pass


# ---- Helpers -----------------------------------------------------------------

def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 1. revenue-cycle-report
# ---------------------------------------------------------------------------
def revenue_cycle_report(conn, args):
    """End-to-end revenue cycle metrics: charges -> claims -> payments."""
    company_id = getattr(args, "company_id", None)

    # Total charges
    charge_where, charge_params = ["1=1"], []
    if company_id:
        charge_where.append("company_id = ?"); charge_params.append(company_id)
    date_from = getattr(args, "date_from", None)
    if date_from:
        charge_where.append("service_date >= ?"); charge_params.append(date_from)
    date_to = getattr(args, "date_to", None)
    if date_to:
        charge_where.append("service_date <= ?"); charge_params.append(date_to)
    charge_sql = " AND ".join(charge_where)

    # PyPika: skipped — complex GROUP BY with CAST aggregate
    charge_rows = conn.execute(
        f"SELECT charge_status, COUNT(*) as cnt, COALESCE(SUM(CAST(total_fee AS NUMERIC)), 0) as total FROM healthclaw_charge WHERE {charge_sql} GROUP BY charge_status",
        charge_params
    ).fetchall()

    charges_by_status = {}
    total_charges = Decimal("0.00")
    total_charge_count = 0
    for r in charge_rows:
        d = row_to_dict(r)
        charges_by_status[d["charge_status"]] = {
            "count": d["cnt"],
            "total": str(round_currency(to_decimal(str(d["total"]))))
        }
        total_charges += to_decimal(str(d["total"]))
        total_charge_count += d["cnt"]

    # Total claims
    claim_where, claim_params = ["1=1"], []
    if company_id:
        claim_where.append("company_id = ?"); claim_params.append(company_id)
    claim_sql = " AND ".join(claim_where)

    # PyPika: skipped — complex GROUP BY with CAST aggregate
    claim_rows = conn.execute(
        f"SELECT claim_status, COUNT(*) as cnt, COALESCE(SUM(CAST(total_charged AS NUMERIC)), 0) as charged, COALESCE(SUM(CAST(total_paid AS NUMERIC)), 0) as paid FROM healthclaw_claim WHERE {claim_sql} GROUP BY claim_status",
        claim_params
    ).fetchall()

    claims_by_status = {}
    total_claimed = Decimal("0.00")
    total_paid = Decimal("0.00")
    for r in claim_rows:
        d = row_to_dict(r)
        claims_by_status[d["claim_status"]] = {
            "count": d["cnt"],
            "total_charged": str(round_currency(to_decimal(str(d["charged"])))),
            "total_paid": str(round_currency(to_decimal(str(d["paid"]))))
        }
        total_claimed += to_decimal(str(d["charged"]))
        total_paid += to_decimal(str(d["paid"]))

    collection_rate = round(float(total_paid / total_claimed * 100), 1) if total_claimed > 0 else 0.0

    ok({
        "total_charges": str(round_currency(total_charges)),
        "total_charge_count": total_charge_count,
        "charges_by_status": charges_by_status,
        "total_claimed": str(round_currency(total_claimed)),
        "total_paid": str(round_currency(total_paid)),
        "collection_rate_pct": collection_rate,
        "claims_by_status": claims_by_status,
    })


# ---------------------------------------------------------------------------
# 2. payer-mix-report
# ---------------------------------------------------------------------------
def payer_mix_report(conn, args):
    """Breakdown of claims and payments by payer."""
    company_id = getattr(args, "company_id", None)
    where, params = ["1=1"], []
    if company_id:
        where.append("company_id = ?"); params.append(company_id)
    where_sql = " AND ".join(where)

    # PyPika: skipped — complex GROUP BY with multiple CAST aggregates
    rows = conn.execute(
        f"""SELECT payer_name,
            COUNT(*) as claim_count,
            COALESCE(SUM(CAST(total_charged AS NUMERIC)), 0) as total_charged,
            COALESCE(SUM(CAST(total_paid AS NUMERIC)), 0) as total_paid,
            COALESCE(SUM(CAST(total_adjustment AS NUMERIC)), 0) as total_adjustment
            FROM healthclaw_claim WHERE {where_sql}
            GROUP BY payer_name ORDER BY total_charged DESC""",
        params
    ).fetchall()

    grand_total = Decimal("0.00")
    payers = []
    for r in rows:
        d = row_to_dict(r)
        charged = to_decimal(str(d["total_charged"]))
        grand_total += charged
        payers.append({
            "payer_name": d["payer_name"],
            "claim_count": d["claim_count"],
            "total_charged": str(round_currency(charged)),
            "total_paid": str(round_currency(to_decimal(str(d["total_paid"])))),
            "total_adjustment": str(round_currency(to_decimal(str(d["total_adjustment"])))),
        })

    # Calculate percentages
    for p in payers:
        charged = to_decimal(p["total_charged"])
        p["pct_of_total"] = round(float(charged / grand_total * 100), 1) if grand_total > 0 else 0.0

    ok({
        "grand_total_charged": str(round_currency(grand_total)),
        "payer_count": len(payers),
        "payers": payers,
    })


# ---------------------------------------------------------------------------
# 3. denial-rate-report
# ---------------------------------------------------------------------------
def denial_rate_report(conn, args):
    """Claim denial analysis."""
    company_id = getattr(args, "company_id", None)
    where, params = ["1=1"], []
    if company_id:
        where.append("company_id = ?"); params.append(company_id)
    where_sql = " AND ".join(where)

    # PyPika: skipped — denial rate report uses complex grouped queries
    # Total claims
    total_row = conn.execute(
        f"SELECT COUNT(*) as total FROM healthclaw_claim WHERE {where_sql}", params
    ).fetchone()
    total_claims = total_row[0] if total_row else 0

    # Denied claims
    denied_params = list(params)
    denied_where = where + ["claim_status = 'denied'"]
    denied_sql = " AND ".join(denied_where)
    denied_row = conn.execute(
        f"SELECT COUNT(*) as cnt, COALESCE(SUM(CAST(total_charged AS NUMERIC)), 0) as total FROM healthclaw_claim WHERE {denied_sql}",
        denied_params
    ).fetchone()
    denied_count = denied_row[0] if denied_row else 0
    denied_amount = to_decimal(str(denied_row[1])) if denied_row else Decimal("0.00")

    denial_rate = round(denied_count / total_claims * 100, 1) if total_claims > 0 else 0.0

    # Denial reasons breakdown
    reason_rows = conn.execute(
        f"""SELECT COALESCE(denial_reason, 'Not specified') as reason, COUNT(*) as cnt
            FROM healthclaw_claim WHERE {denied_sql}
            GROUP BY denial_reason ORDER BY cnt DESC""",
        denied_params
    ).fetchall()

    reasons = [{"reason": row_to_dict(r)["reason"], "count": row_to_dict(r)["cnt"]} for r in reason_rows]

    # Denied by payer
    payer_rows = conn.execute(
        f"""SELECT payer_name, COUNT(*) as cnt
            FROM healthclaw_claim WHERE {denied_sql}
            GROUP BY payer_name ORDER BY cnt DESC""",
        denied_params
    ).fetchall()
    denied_by_payer = [{"payer_name": row_to_dict(r)["payer_name"], "count": row_to_dict(r)["cnt"]}
                       for r in payer_rows]

    ok({
        "total_claims": total_claims,
        "denied_count": denied_count,
        "denied_amount": str(round_currency(denied_amount)),
        "denial_rate_pct": denial_rate,
        "denial_reasons": reasons,
        "denied_by_payer": denied_by_payer,
    })


# ---------------------------------------------------------------------------
# Action Router
# ---------------------------------------------------------------------------
ACTIONS = {
    "health-revenue-cycle-report": revenue_cycle_report,
    "health-payer-mix-report": payer_mix_report,
    "health-denial-rate-report": denial_rate_report,
}
