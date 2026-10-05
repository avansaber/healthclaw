"""Approved charity-care adjustments against submitted claims.

Action driven:
  - health-apply-charity-care  (adv_billing.py apply_charity_care)

The handler debits a charity-care expense account and credits a receivable
asset account for the exact approved amount through the shared GL posting
seam in one transaction. An identical retry naming the same claim plus
approval reference returns the original receipt, while a retry with a
different amount or different accounts is refused. Amounts above the claim
balance are refused, as are draft, void, missing, foreign-company, and
zero-total claims, and accounts that are missing, grouped, disabled, of the
wrong root type, or from another company. Only exact positive Decimal
amounts are accepted, never float. Every refusal writes nothing: no
adjustment row, no GL entries, and no audit row.
"""
import json
import os
import subprocess
import sys
import uuid
from decimal import Decimal

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from health_helpers import call_action, is_error, is_ok, load_db_query, ns  # noqa: E402

ACTIONS = load_db_query().ACTIONS

APPROVAL_DATE = "2026-06-15"
APPROVAL_REF = "APPR-2026-001"


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
    charity_expense = seed_account(conn, company_id, "Charity Care Expense",
                                   "expense", "expense", f"5000-{company_id[:4]}")
    return receivable, charity_expense


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


def _apply(conn, company_id, claim_id, receivable, charity_expense,
           amount="500.03", ref=APPROVAL_REF, approval_date=APPROVAL_DATE):
    return call_action(ACTIONS["health-apply-charity-care"], conn, ns(
        company_id=company_id, claim_id=claim_id, approval_date=approval_date,
        charity_amount=amount, approval_reference=ref,
        receivable_account_id=receivable,
        charity_expense_account_id=charity_expense,
        cost_center_id=None))


def _gl_by_ids(conn, ids):
    rows = []
    for gid in ids:
        r = conn.execute(
            "SELECT id, account_id, debit, credit, posting_date, voucher_type,"
            " entry_set, is_cancelled FROM gl_entry WHERE id = ?",
            (gid,)).fetchone()
        assert r is not None, gid
        rows.append(dict(r))
    return rows


def _gl_count(conn):
    return conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0]


def _adj_rows(conn, claim_id):
    return [dict(r) for r in conn.execute(
        "SELECT id, company_id, claim_id, approval_date, approval_reference,"
        " amount, receivable_account_id, charity_expense_account_id,"
        " gl_entry_ids FROM healthclaw_charity_care_adjustment"
        " WHERE claim_id = ?", (claim_id,)).fetchall()]


def _audit_rows(conn, entity_id):
    return [dict(r) for r in conn.execute(
        "SELECT skill, action, entity_type, entity_id, new_values FROM audit_log"
        " WHERE action = 'health-apply-charity-care' AND entity_id = ?",
        (entity_id,)).fetchall()]


def _msg(r):
    return r.get("message", "") + r.get("error", "")


def test_applies_exact_500_03_balanced_gl(conn, env):
    receivable, charity_expense = seed_ledger(conn, env["company_id"])
    claim_id = _submitted_claim(conn, env)

    r = _apply(conn, env["company_id"], claim_id, receivable, charity_expense)
    assert is_ok(r), r
    assert r["claim_id"] == claim_id
    assert r["amount"] == "500.03"
    assert r["remaining_balance"] == "0.00"
    assert r["approval_reference"] == APPROVAL_REF
    assert r["approval_date"] == APPROVAL_DATE
    assert len(r["gl_entry_ids"]) == 2
    assert r["gl_entry_count"] == 2

    rows = _gl_by_ids(conn, r["gl_entry_ids"])
    by_account = {x["account_id"]: (x["debit"], x["credit"]) for x in rows}
    assert by_account[charity_expense] == ("500.03", "0.00")
    assert by_account[receivable] == ("0.00", "500.03")
    debit = sum((Decimal(x["debit"]) for x in rows), Decimal("0"))
    credit = sum((Decimal(x["credit"]) for x in rows), Decimal("0"))
    assert debit == credit == Decimal("500.03")
    assert {x["voucher_type"] for x in rows} == {"journal_entry"}
    assert {x["entry_set"] for x in rows} == {"primary"}
    assert {x["is_cancelled"] for x in rows} == {0}
    assert {x["posting_date"] for x in rows} == {APPROVAL_DATE}

    stored = _adj_rows(conn, claim_id)
    assert len(stored) == 1
    assert stored[0]["amount"] == "500.03"
    assert stored[0]["approval_reference"] == APPROVAL_REF
    assert stored[0]["receivable_account_id"] == receivable
    assert stored[0]["charity_expense_account_id"] == charity_expense
    assert json.loads(stored[0]["gl_entry_ids"]) == r["gl_entry_ids"]

    audits = _audit_rows(conn, r["id"])
    assert len(audits) == 1
    assert (audits[0]["skill"], audits[0]["action"],
            audits[0]["entity_type"]) == (
        "healthclaw", "health-apply-charity-care",
        "healthclaw_charity_care_adjustment")
    assert json.loads(audits[0]["new_values"])["claim_id"] == claim_id


def test_identical_retry_returns_original_receipt(conn, env):
    receivable, charity_expense = seed_ledger(conn, env["company_id"])
    claim_id = _submitted_claim(conn, env)

    first = _apply(conn, env["company_id"], claim_id, receivable, charity_expense)
    assert is_ok(first), first
    second = _apply(conn, env["company_id"], claim_id, receivable, charity_expense)
    assert is_ok(second), second
    assert second["id"] == first["id"]
    assert second["gl_entry_ids"] == first["gl_entry_ids"]
    assert second["amount"] == "500.03"
    assert second["remaining_balance"] == "0.00"
    assert second["approval_date"] == APPROVAL_DATE
    assert _gl_count(conn) == 2
    assert len(_adj_rows(conn, claim_id)) == 1
    assert len(_audit_rows(conn, first["id"])) == 1


def test_changed_amount_retry_is_refused(conn, env):
    receivable, charity_expense = seed_ledger(conn, env["company_id"])
    claim_id = _submitted_claim(conn, env)

    first = _apply(conn, env["company_id"], claim_id, receivable, charity_expense)
    assert is_ok(first), first
    r = _apply(conn, env["company_id"], claim_id, receivable, charity_expense,
               amount="400.00")
    assert is_error(r), r
    assert "different amount" in _msg(r)
    assert _gl_count(conn) == 2
    assert len(_adj_rows(conn, claim_id)) == 1
    assert len(_audit_rows(conn, first["id"])) == 1


def test_changed_account_retry_is_refused(conn, env):
    receivable, charity_expense = seed_ledger(conn, env["company_id"])
    other_receivable = seed_account(conn, env["company_id"], "Other Receivable",
                                    "asset", "receivable", "1110-X1")
    other_expense = seed_account(conn, env["company_id"], "Other Charity",
                                 "expense", "expense", "5010-X1")
    claim_id = _submitted_claim(conn, env)

    first = _apply(conn, env["company_id"], claim_id, receivable, charity_expense)
    assert is_ok(first), first
    for label, recv, exp in (
        ("changed receivable", other_receivable, charity_expense),
        ("changed expense", receivable, other_expense),
    ):
        r = _apply(conn, env["company_id"], claim_id, recv, exp)
        assert is_error(r), (label, r)
        assert "different accounts" in _msg(r), (label, r)
    assert _gl_count(conn) == 2
    assert len(_adj_rows(conn, claim_id)) == 1
    assert len(_audit_rows(conn, first["id"])) == 1


def test_partial_adjustments_track_remaining_balance(conn, env):
    receivable, charity_expense = seed_ledger(conn, env["company_id"])
    claim_id = _submitted_claim(conn, env)

    first = _apply(conn, env["company_id"], claim_id, receivable, charity_expense,
                   amount="200.00", ref="APPR-2026-010")
    assert is_ok(first), first
    assert first["amount"] == "200.00"
    assert first["remaining_balance"] == "300.03"

    over = _apply(conn, env["company_id"], claim_id, receivable, charity_expense,
                  amount="300.04", ref="APPR-2026-011")
    assert is_error(over), over
    assert "exceeds" in _msg(over)

    second = _apply(conn, env["company_id"], claim_id, receivable, charity_expense,
                    amount="300.03", ref="APPR-2026-011")
    assert is_ok(second), second
    assert second["remaining_balance"] == "0.00"
    assert second["gl_entry_ids"] != first["gl_entry_ids"]

    retry = _apply(conn, env["company_id"], claim_id, receivable, charity_expense,
                   amount="200.00", ref="APPR-2026-010")
    assert is_ok(retry), retry
    assert retry["gl_entry_ids"] == first["gl_entry_ids"]
    assert retry["remaining_balance"] == "0.00"

    dust = _apply(conn, env["company_id"], claim_id, receivable, charity_expense,
                  amount="0.01", ref="APPR-2026-012")
    assert is_error(dust), dust
    assert "exceeds" in _msg(dust)

    assert len(_adj_rows(conn, claim_id)) == 2
    assert _gl_count(conn) == 4


def test_over_adjustment_refused(conn, env):
    receivable, charity_expense = seed_ledger(conn, env["company_id"])
    claim_id = _submitted_claim(conn, env)

    r = _apply(conn, env["company_id"], claim_id, receivable, charity_expense,
               amount="500.04")
    assert is_error(r), r
    assert "exceeds" in _msg(r)
    assert _gl_count(conn) == 0
    assert _adj_rows(conn, claim_id) == []
    assert _audit_rows(conn, claim_id) == []


def test_amount_must_be_exact_positive_decimal(conn, env):
    receivable, charity_expense = seed_ledger(conn, env["company_id"])
    claim_id = _submitted_claim(conn, env)

    for label, bad in (("zero", "0.00"), ("negative", "-10.00")):
        r = _apply(conn, env["company_id"], claim_id, receivable, charity_expense,
                   amount=bad)
        assert is_error(r), (label, r)
        assert "positive" in _msg(r), (label, r)

    r = _apply(conn, env["company_id"], claim_id, receivable, charity_expense,
               amount=500.03)
    assert is_error(r), r

    r = _apply(conn, env["company_id"], claim_id, receivable, charity_expense,
               amount="not-a-number")
    assert is_error(r), r

    assert _gl_count(conn) == 0
    assert _adj_rows(conn, claim_id) == []
    assert _audit_rows(conn, claim_id) == []


def test_account_validation_writes_nothing(conn, env):
    receivable, charity_expense = seed_ledger(conn, env["company_id"])
    group_acct = seed_account(conn, env["company_id"], "Group Asset",
                              "asset", None, "1990-G1")
    conn.execute("UPDATE account SET is_group = 1 WHERE id = ?", (group_acct,))
    conn.commit()
    disabled_acct = seed_account(conn, env["company_id"], "Disabled Charity",
                                 "expense", "expense", "5020-D1")
    conn.execute("UPDATE account SET disabled = 1 WHERE id = ?", (disabled_acct,))
    conn.commit()
    liability_acct = seed_account(conn, env["company_id"], "Payable",
                                  "liability", "payable", "2000-L1")
    revenue_acct = seed_account(conn, env["company_id"], "Revenue",
                                "income", "revenue", "4000-R1")

    cases = [
        ("missing receivable", "no-such-account", charity_expense),
        ("missing expense", receivable, "no-such-account"),
        ("group receivable", group_acct, charity_expense),
        ("disabled expense", receivable, disabled_acct),
        ("wrong root receivable", liability_acct, charity_expense),
        ("expense as receivable", charity_expense, charity_expense),
        ("wrong root expense", receivable, revenue_acct),
        ("receivable as expense", receivable, receivable),
    ]
    for label, recv, exp in cases:
        claim_id = _submitted_claim(conn, env)
        r = _apply(conn, env["company_id"], claim_id, recv, exp)
        assert is_error(r), (label, r)
        assert _gl_count(conn) == 0, label
        assert _adj_rows(conn, claim_id) == [], label
        assert _audit_rows(conn, claim_id) == [], label


def test_claim_state_validation_writes_nothing(conn, env):
    receivable, charity_expense = seed_ledger(conn, env["company_id"])

    draft_id = _claim(conn, env, [_charge(conn, env, "500.03")])
    r = _apply(conn, env["company_id"], draft_id, receivable, charity_expense)
    assert is_error(r), r
    assert "submitted" in _msg(r)

    void_id = _submitted_claim(conn, env)
    conn.execute("UPDATE healthclaw_claim SET claim_status = 'void' WHERE id = ?",
                 (void_id,))
    conn.commit()
    r = _apply(conn, env["company_id"], void_id, receivable, charity_expense)
    assert is_error(r), r

    r = _apply(conn, env["company_id"], "no-such-claim", receivable, charity_expense)
    assert is_error(r), r
    assert "not found" in _msg(r)

    zero_id = _claim(conn, env, [])
    _submit(conn, zero_id)
    r = _apply(conn, env["company_id"], zero_id, receivable, charity_expense)
    assert is_error(r), r
    assert "exceeds" in _msg(r)

    assert _gl_count(conn) == 0
    for cid in (draft_id, void_id, zero_id):
        assert _adj_rows(conn, cid) == []
        assert _audit_rows(conn, cid) == []


def test_company_isolation_writes_nothing(conn, env):
    from health_helpers import seed_company
    receivable, charity_expense = seed_ledger(conn, env["company_id"])
    other_company = seed_company(conn, "Other Co")
    seed_ledger(conn, other_company)
    foreign_receivable = conn.execute(
        "SELECT id FROM account WHERE company_id = ? AND root_type = 'asset'",
        (other_company,)).fetchone()[0]
    foreign_expense = conn.execute(
        "SELECT id FROM account WHERE company_id = ? AND root_type = 'expense'",
        (other_company,)).fetchone()[0]

    claim_id = _submitted_claim(conn, env)

    r = _apply(conn, other_company, claim_id, foreign_receivable, foreign_expense)
    assert is_error(r), r
    assert "belongs to company" in _msg(r)

    r = _apply(conn, env["company_id"], claim_id, foreign_receivable, charity_expense)
    assert is_error(r), r

    r = _apply(conn, env["company_id"], claim_id, receivable, foreign_expense)
    assert is_error(r), r

    assert _gl_count(conn) == 0
    assert _adj_rows(conn, claim_id) == []
    assert _audit_rows(conn, claim_id) == []


def test_required_flags(conn, env):
    receivable, charity_expense = seed_ledger(conn, env["company_id"])
    claim_id = _submitted_claim(conn, env)
    base = dict(company_id=env["company_id"], claim_id=claim_id,
                approval_date=APPROVAL_DATE, charity_amount="500.03",
                approval_reference=APPROVAL_REF,
                receivable_account_id=receivable,
                charity_expense_account_id=charity_expense,
                cost_center_id=None)
    for flag in ("company_id", "claim_id", "approval_date", "charity_amount",
                 "approval_reference", "receivable_account_id",
                 "charity_expense_account_id"):
        kw = dict(base)
        kw[flag] = None
        r = call_action(ACTIONS["health-apply-charity-care"], conn, ns(**kw))
        assert is_error(r), (flag, r)
        assert "is required" in _msg(r), (flag, r)
    assert _gl_count(conn) == 0
    assert _adj_rows(conn, claim_id) == []


def test_gl_failure_writes_nothing(conn, env):
    seed_fiscal_year(conn, env["company_id"])
    receivable = seed_account(conn, env["company_id"], "Patient Receivable",
                              "asset", "receivable", f"1100-{env['company_id'][:4]}")
    charity_expense = seed_account(conn, env["company_id"], "Charity Care Expense",
                                   "expense", "expense", f"5000-{env['company_id'][:4]}")
    claim_id = _submitted_claim(conn, env)

    r = _apply(conn, env["company_id"], claim_id, receivable, charity_expense)
    assert is_error(r), r
    assert _gl_count(conn) == 0
    assert _adj_rows(conn, claim_id) == []
    assert _audit_rows(conn, claim_id) == []


def test_routing_and_parser_flags():
    import health_helpers
    scripts_dir = os.path.dirname(_TESTS_DIR)
    env_vars = dict(os.environ)
    lib_path = health_helpers.ERPCLAW_LIB
    prior = env_vars.get("PYTHONPATH", "")
    env_vars["PYTHONPATH"] = lib_path + (os.pathsep + prior if prior else "")
    proc = subprocess.run(
        [sys.executable, os.path.join(scripts_dir, "db_query.py"), "--help"],
        capture_output=True, text=True, env=env_vars, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "health-apply-charity-care" in proc.stdout
    for flag in ("--approval-date", "--approval-reference", "--charity-amount",
                 "--charity-expense-account-id"):
        assert flag in proc.stdout, flag
