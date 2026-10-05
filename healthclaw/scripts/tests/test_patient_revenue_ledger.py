"""Patient revenue to the ledger: one submitted claim posts exactly once.

Action driven:
  - health-post-patient-revenue  (adv_billing.py post_patient_revenue)

The handler debits a receivable asset account and credits a revenue income
account for the claim's exact total charged through the shared GL posting
seam in one transaction. A retry naming the same accounts returns the
original receipt; a retry naming different accounts is refused. Draft,
void, missing, foreign-company, and zero-total claims are refused, as are
accounts that are missing, grouped, disabled, of the wrong root type, or
from another company. Every refusal writes nothing.
"""
import json
import os
import sys
import uuid
from decimal import Decimal

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from health_helpers import call_action, is_error, is_ok, load_db_query, ns  # noqa: E402

ACTIONS = load_db_query().ACTIONS

POSTING_DATE = "2026-06-15"


def _uuid():
    return str(uuid.uuid4())


def seed_account(conn, company_id, name, root_type, account_type, number):
    aid = _uuid()
    direction = "debit_normal" if root_type in ("asset", "expense") else "credit_normal"
    conn.execute(
        """INSERT INTO account (id, name, account_number, root_type, account_type,
           balance_direction, company_id, depth)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
        (aid, name, number, root_type, account_type, direction, company_id))
    conn.commit()
    return aid


def seed_fiscal_year(conn, company_id, start="2026-01-01", end="2026-12-31"):
    fid = _uuid()
    conn.execute(
        "INSERT INTO fiscal_year (id, name, start_date, end_date, company_id)"
        " VALUES (?, ?, ?, ?, ?)",
        (fid, f"FY-{fid[:6]}", start, end, company_id))
    conn.commit()
    return fid


def seed_cost_center(conn, company_id, name="Main CC"):
    ccid = _uuid()
    conn.execute(
        "INSERT INTO cost_center (id, name, company_id, is_group)"
        " VALUES (?, ?, ?, 0)",
        (ccid, name, company_id))
    conn.commit()
    return ccid


def seed_ledger(conn, company_id):
    seed_fiscal_year(conn, company_id)
    seed_cost_center(conn, company_id)
    receivable = seed_account(conn, company_id, "Patient Receivable",
                              "asset", "receivable", f"1100-{company_id[:4]}")
    revenue = seed_account(conn, company_id, "Patient Revenue",
                           "income", "revenue", f"4000-{company_id[:4]}")
    return receivable, revenue


def _charge(conn, env, unit_fee, quantity="1"):
    r = call_action(ACTIONS["health-adv-add-charge"], conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], procedure_code_id=None,
        service_date="2026-03-15", cpt_code="99213", icd10_codes=None,
        description=None, quantity=quantity, unit_fee=unit_fee, notes=None))
    assert is_ok(r), r
    return r["id"]


def _claim(conn, env, charge_ids, company_id=None):
    r = call_action(ACTIONS["health-adv-add-claim"], conn, ns(
        company_id=company_id or env["company_id"], patient_id=env["patient_id"],
        payer_name="Acme Health", payer_id_number=None, policy_number=None,
        group_number=None, claim_number=None, claim_date="2026-03-20",
        charge_ids=json.dumps(charge_ids), notes=None))
    assert is_ok(r), r
    return r["id"]


def _submit(conn, claim_id):
    r = call_action(ACTIONS["health-adv-submit-claim"], conn, ns(claim_id=claim_id))
    assert is_ok(r), r
    return r


def _submitted_claim(conn, env, unit_fee="500.03", company_id=None):
    cid = _claim(conn, env, [_charge(conn, env, unit_fee)], company_id=company_id)
    _submit(conn, cid)
    return cid


def _post(conn, company_id, claim_id, receivable, revenue, posting_date=POSTING_DATE):
    return call_action(ACTIONS["health-post-patient-revenue"], conn, ns(
        company_id=company_id, claim_id=claim_id, posting_date=posting_date,
        receivable_account_id=receivable, revenue_account_id=revenue,
        cost_center_id=None))


def _gl_rows(conn, claim_id):
    return conn.execute(
        "SELECT id, account_id, debit, credit, posting_date, voucher_type,"
        " entry_set, is_cancelled FROM gl_entry WHERE voucher_id = ?",
        (claim_id,)).fetchall()


def _gl_count(conn):
    return conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0]


def _audit_count(conn, claim_id):
    return conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'health-post-patient-revenue'"
        " AND entity_id = ?", (claim_id,)).fetchone()[0]


def _msg(r):
    return r.get("message", "") + r.get("error", "")


def test_posts_exact_500_03_balanced_gl(conn, env):
    receivable, revenue = seed_ledger(conn, env["company_id"])
    claim_id = _submitted_claim(conn, env)

    r = _post(conn, env["company_id"], claim_id, receivable, revenue)
    assert is_ok(r), r
    assert r["claim_id"] == claim_id
    assert r["amount"] == "500.03"
    assert r["posting_date"] == POSTING_DATE
    assert len(r["gl_entry_ids"]) == 2

    rows = _gl_rows(conn, claim_id)
    assert len(rows) == 2
    by_account = {x["account_id"]: (x["debit"], x["credit"]) for x in rows}
    assert by_account[receivable] == ("500.03", "0.00")
    assert by_account[revenue] == ("0.00", "500.03")
    debit = sum((Decimal(x["debit"]) for x in rows), Decimal("0"))
    credit = sum((Decimal(x["credit"]) for x in rows), Decimal("0"))
    assert debit == credit == Decimal("500.03")
    assert {x["voucher_type"] for x in rows} == {"journal_entry"}
    assert {x["is_cancelled"] for x in rows} == {0}
    assert _audit_count(conn, claim_id) == 1


def test_identical_retry_returns_original_receipt(conn, env):
    receivable, revenue = seed_ledger(conn, env["company_id"])
    claim_id = _submitted_claim(conn, env)

    first = _post(conn, env["company_id"], claim_id, receivable, revenue)
    assert is_ok(first), first
    second = _post(conn, env["company_id"], claim_id, receivable, revenue)
    assert is_ok(second), second
    assert second["gl_entry_ids"] == first["gl_entry_ids"]
    assert second["amount"] == "500.03"
    assert second["posting_date"] == POSTING_DATE
    assert len(_gl_rows(conn, claim_id)) == 2


def test_changed_account_retry_is_refused(conn, env):
    receivable, revenue = seed_ledger(conn, env["company_id"])
    other_revenue = seed_account(conn, env["company_id"], "Other Revenue",
                                 "income", "revenue", "4010-X1")
    claim_id = _submitted_claim(conn, env)

    first = _post(conn, env["company_id"], claim_id, receivable, revenue)
    assert is_ok(first), first
    r = _post(conn, env["company_id"], claim_id, receivable, other_revenue)
    assert is_error(r), r
    assert "different accounts" in _msg(r)
    assert len(_gl_rows(conn, claim_id)) == 2
    assert _gl_count(conn) == 2


def test_account_validation_writes_nothing(conn, env):
    receivable, revenue = seed_ledger(conn, env["company_id"])
    group_acct = seed_account(conn, env["company_id"], "Group Asset",
                              "asset", None, "1990-G1")
    conn.execute("UPDATE account SET is_group = 1 WHERE id = ?", (group_acct,))
    conn.commit()
    disabled_acct = seed_account(conn, env["company_id"], "Disabled Revenue",
                                 "income", "revenue", "4020-D1")
    conn.execute("UPDATE account SET disabled = 1 WHERE id = ?", (disabled_acct,))
    conn.commit()
    liability_acct = seed_account(conn, env["company_id"], "Payable",
                                  "liability", "payable", "2000-L1")

    cases = [
        ("missing receivable", "no-such-account", revenue),
        ("missing revenue", receivable, "no-such-account"),
        ("group receivable", group_acct, revenue),
        ("disabled revenue", receivable, disabled_acct),
        ("wrong root receivable", liability_acct, revenue),
        ("wrong root revenue", receivable, receivable),
    ]
    for label, recv, rev in cases:
        claim_id = _submitted_claim(conn, env)
        r = _post(conn, env["company_id"], claim_id, recv, rev)
        assert is_error(r), (label, r)
        assert _gl_count(conn) == 0, label
        assert _audit_count(conn, claim_id) == 0, label


def test_claim_state_validation_writes_nothing(conn, env):
    receivable, revenue = seed_ledger(conn, env["company_id"])

    draft_id = _claim(conn, env, [_charge(conn, env, "500.03")])
    r = _post(conn, env["company_id"], draft_id, receivable, revenue)
    assert is_error(r), r
    assert "submitted" in _msg(r)

    void_id = _submitted_claim(conn, env)
    conn.execute("UPDATE healthclaw_claim SET claim_status = 'void' WHERE id = ?",
                 (void_id,))
    conn.commit()
    r = _post(conn, env["company_id"], void_id, receivable, revenue)
    assert is_error(r), r

    r = _post(conn, env["company_id"], "no-such-claim", receivable, revenue)
    assert is_error(r), r
    assert "not found" in _msg(r)

    zero_id = _claim(conn, env, [])
    _submit(conn, zero_id)
    r = _post(conn, env["company_id"], zero_id, receivable, revenue)
    assert is_error(r), r
    assert "positive" in _msg(r)

    assert _gl_count(conn) == 0
    for cid in (draft_id, void_id, zero_id):
        assert _audit_count(conn, cid) == 0


def test_company_isolation_writes_nothing(conn, env):
    from health_helpers import seed_company
    receivable, revenue = seed_ledger(conn, env["company_id"])
    other_company = seed_company(conn, "Other Co")
    seed_ledger(conn, other_company)
    foreign_receivable = conn.execute(
        "SELECT id FROM account WHERE company_id = ? AND root_type = 'asset'",
        (other_company,)).fetchone()[0]
    foreign_revenue = conn.execute(
        "SELECT id FROM account WHERE company_id = ? AND root_type = 'income'",
        (other_company,)).fetchone()[0]

    claim_id = _submitted_claim(conn, env)

    r = _post(conn, other_company, claim_id, foreign_receivable, foreign_revenue)
    assert is_error(r), r
    assert "belongs to company" in _msg(r)

    r = _post(conn, env["company_id"], claim_id, foreign_receivable, revenue)
    assert is_error(r), r

    r = _post(conn, env["company_id"], claim_id, receivable, foreign_revenue)
    assert is_error(r), r

    assert _gl_count(conn) == 0
    assert _audit_count(conn, claim_id) == 0


def test_required_flags(conn, env):
    receivable, revenue = seed_ledger(conn, env["company_id"])
    claim_id = _submitted_claim(conn, env)
    base = dict(company_id=env["company_id"], claim_id=claim_id,
                posting_date=POSTING_DATE, receivable_account_id=receivable,
                revenue_account_id=revenue, cost_center_id=None)
    for flag in ("company_id", "claim_id", "posting_date",
                 "receivable_account_id", "revenue_account_id"):
        kw = dict(base)
        kw[flag] = None
        r = call_action(ACTIONS["health-post-patient-revenue"], conn, ns(**kw))
        assert is_error(r), (flag, r)
        assert "is required" in _msg(r)
    assert _gl_count(conn) == 0
