"""340B accumulator: local eligibility and accumulation register.

Action driven:
  - health-record-340b-dispense  (accumulator_340b.py record_340b_dispense)
  - health-list-340b-dispenses   (accumulator_340b.py list_340b_dispenses)
  - health-get-340b-dispense     (accumulator_340b.py get_340b_dispense)

The register records qualified dispense rows after explicit validation and
reports exact acquisition and ceiling values. It is a local record only: no
legal eligibility determination, no claim transmission, no general ledger
posting. Retries naming the same durable idempotency key plus identical
fields return the original row, while a retry with the same key plus changed
fields is refused. Missing evidence, foreign encounters, negative money, and
acquisition above ceiling are all refused with nothing written.
"""
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

RECORD = "health-record-340b-dispense"
LIST = "health-list-340b-dispenses"
GET = "health-get-340b-dispense"

BASE = {
    "drug_identifier": "00093-0058-01",
    "quantity": "30",
    "dispense_date": "2026-04-10",
    "qualification_reason": "covered-entity-dispense",
    "evidence_reference": "EV-2026-001",
    "acquisition_cost": "120.05",
    "ceiling_price": "150.00",
}


def _record(conn, env, key=None, **over):
    kw = dict(company_id=env["company_id"], encounter_id=env["encounter_id"])
    kw.update(BASE)
    kw["idempotency_key"] = key
    kw.update(over)
    return call_action(ACTIONS[RECORD], conn, ns(**kw))


def _rows(conn, company_id=None):
    if company_id:
        return conn.execute(
            "SELECT * FROM healthclaw_340b_accumulation WHERE company_id = ?",
            (company_id,)).fetchall()
    return conn.execute("SELECT * FROM healthclaw_340b_accumulation").fetchall()


def _idem_count(conn):
    return conn.execute("SELECT COUNT(*) FROM healthclaw_340b_idempotency_key").fetchone()[0]


def _audit_count(conn, entity_id):
    return conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE entity_id = ?",
        (entity_id,)).fetchone()[0]


def _msg(result):
    return result.get("message", "") + result.get("error", "")


def test_records_exact_money_and_quantity(conn, env):
    r = _record(conn, env, key="key-exact-001")
    assert is_ok(r), r
    assert r["acquisition_cost"] == "120.05"
    assert r["ceiling_price"] == "150.00"
    assert r["ceiling_value"] == "150.00"
    assert r["quantity"] == "30"
    assert r["drug_identifier"] == "00093-0058-01"
    assert r["encounter_id"] == env["encounter_id"]
    assert r["company_id"] == env["company_id"]

    stored = conn.execute(
        "SELECT acquisition_cost, ceiling_price, quantity FROM"
        " healthclaw_340b_accumulation WHERE id = ?",
        (r["id"],)).fetchone()
    assert stored["acquisition_cost"] == "120.05"
    assert stored["ceiling_price"] == "150.00"
    assert stored["quantity"] == "30"
    assert Decimal(stored["acquisition_cost"]) == Decimal("120.05")
    assert Decimal(stored["ceiling_price"]) == Decimal("150.00")

    audits = conn.execute(
        "SELECT skill, action, entity_type FROM audit_log WHERE entity_id = ?",
        (r["id"],)).fetchall()
    assert len(audits) == 1
    assert audits[0]["skill"] == "healthclaw"
    assert audits[0]["action"] == RECORD
    assert audits[0]["entity_type"] == "healthclaw_340b_accumulation"


def test_quantity_preserves_fraction(conn, env):
    r = _record(conn, env, key="key-qty-001", quantity="2.50")
    assert is_ok(r), r
    assert r["quantity"] == "2.50"
    stored = conn.execute(
        "SELECT quantity FROM healthclaw_340b_accumulation WHERE id = ?",
        (r["id"],)).fetchone()
    assert stored["quantity"] == "2.50"
    assert Decimal(stored["quantity"]) == Decimal("2.50")


def test_identical_retry_returns_original(conn, env):
    first = _record(conn, env, key="key-idem-001")
    assert is_ok(first), first
    second = _record(conn, env, key="key-idem-001")
    assert is_ok(second), second
    assert second["id"] == first["id"]
    assert second["acquisition_cost"] == "120.05"
    assert len(_rows(conn)) == 1
    assert _idem_count(conn) == 1
    assert _audit_count(conn, first["id"]) == 1


def test_conflicting_retry_is_refused(conn, env):
    first = _record(conn, env, key="key-conflict-001")
    assert is_ok(first), first
    r = _record(conn, env, key="key-conflict-001",
                acquisition_cost="99.99")
    assert is_error(r), r
    assert "conflicting" in _msg(r).lower() or "different" in _msg(r).lower()
    assert len(_rows(conn)) == 1
    assert _idem_count(conn) == 1
    assert _audit_count(conn, first["id"]) == 1

    r = _record(conn, env, key="key-conflict-001",
                quantity="31")
    assert is_error(r), r
    assert len(_rows(conn)) == 1
    assert _idem_count(conn) == 1


def test_missing_evidence_is_refused(conn, env):
    r = _record(conn, env, key="key-ev-001", evidence_reference=None)
    assert is_error(r), r
    assert "evidence" in _msg(r).lower()
    r = _record(conn, env, key="key-ev-002", evidence_reference="  ")
    assert is_error(r), r
    assert "evidence" in _msg(r).lower()
    assert _rows(conn) == []
    assert _idem_count(conn) == 0


def test_ceiling_breach_is_refused(conn, env):
    r = _record(conn, env, key="key-ceil-001",
                acquisition_cost="200.00", ceiling_price="150.00")
    assert is_error(r), r
    assert "ceiling" in _msg(r).lower()
    assert _rows(conn) == []
    assert _idem_count(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_negative_money_is_refused(conn, env):
    for label, kw in (
        ("negative acquisition", {"acquisition_cost": "-5.00"}),
        ("negative ceiling", {"ceiling_price": "-1.00"}),
    ):
        r = _record(conn, env, key="key-neg-%s" % uuid.uuid4().hex[:6], **kw)
        assert is_error(r), (label, r)
    assert _rows(conn) == []
    assert _idem_count(conn) == 0


def test_foreign_encounter_is_refused(conn, env):
    from health_helpers import build_env
    other = build_env(conn)
    r = _record(conn, env, key="key-foreign-001",
                encounter_id=other["encounter_id"])
    assert is_error(r), r
    assert "belongs to company" in _msg(r)
    assert _rows(conn, env["company_id"]) == []
    assert _idem_count(conn) == 0

    r = call_action(ACTIONS[RECORD], conn, ns(
        company_id=env["company_id"], encounter_id="no-such-encounter",
        **BASE, idempotency_key="key-foreign-002"))
    assert is_error(r), r
    assert "not found" in _msg(r).lower()


def test_company_isolation_in_list(conn, env):
    from health_helpers import build_env
    other = build_env(conn)
    first = _record(conn, env, key="key-iso-001")
    assert is_ok(first), first
    second = call_action(ACTIONS[RECORD], conn, ns(
        company_id=other["company_id"], encounter_id=other["encounter_id"],
        **BASE, idempotency_key="key-iso-002"))
    assert is_ok(second), second

    mine = call_action(ACTIONS[LIST], conn, ns(
        company_id=env["company_id"]))
    assert is_ok(mine), mine
    assert {x["id"] for x in mine["rows"]} == {first["id"]}

    theirs = call_action(ACTIONS[LIST], conn, ns(
        company_id=other["company_id"]))
    assert is_ok(theirs), theirs
    assert {x["id"] for x in theirs["rows"]} == {second["id"]}


def test_deterministic_listing(conn, env):
    for day, key in (("2026-04-12", "key-det-003"),
                     ("2026-04-10", "key-det-001"),
                     ("2026-04-11", "key-det-002")):
        r = _record(conn, env, key=key, dispense_date=day,
                    evidence_reference="EV-%s" % key)
        assert is_ok(r), r
    listed = call_action(ACTIONS[LIST], conn, ns(
        company_id=env["company_id"]))
    assert is_ok(listed), listed
    assert [x["dispense_date"] for x in listed["rows"]] == [
        "2026-04-10", "2026-04-11", "2026-04-12"]
    again = call_action(ACTIONS[LIST], conn, ns(
        company_id=env["company_id"]))
    assert [x["id"] for x in again["rows"]] == [
        x["id"] for x in listed["rows"]]


def test_get_round_trip_and_scope(conn, env):
    r = _record(conn, env, key="key-get-001")
    assert is_ok(r), r
    got = call_action(ACTIONS[GET], conn, ns(accumulation_id=r["id"]))
    assert is_ok(got), got
    assert got["acquisition_cost"] == "120.05"
    assert got["ceiling_value"] == "150.00"

    from health_helpers import seed_company
    other_company = seed_company(conn, "Other Co")
    scoped = call_action(ACTIONS[GET], conn, ns(
        accumulation_id=r["id"], company_id=other_company))
    assert is_error(scoped), scoped
    assert "belongs to company" in _msg(scoped)


def test_failure_rolls_back_everything(conn, env):
    import accumulator_340b
    real_audit = accumulator_340b.audit

    def _boom(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    accumulator_340b.audit = _boom
    try:
        r = _record(conn, env, key="key-roll-001")
    finally:
        accumulator_340b.audit = real_audit
    assert is_error(r), r
    assert _rows(conn) == []
    assert _idem_count(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_required_flags(conn, env):
    base = dict(company_id=env["company_id"],
                encounter_id=env["encounter_id"], idempotency_key=None)
    base.update(BASE)
    required = ("company_id", "encounter_id", "drug_identifier", "quantity",
                "dispense_date", "qualification_reason", "evidence_reference",
                "acquisition_cost", "ceiling_price")
    for flag in required:
        kw = dict(base)
        kw[flag] = None
        r = call_action(ACTIONS[RECORD], conn, ns(**kw))
        assert is_error(r), (flag, r)
        assert "is required" in _msg(r), (flag, r)
    assert _rows(conn) == []


def test_install_safe_schema_ownership():
    import pathlib
    root = pathlib.Path(_TESTS_DIR).parents[1]
    init_src = (root / "init_db.py").read_text()
    assert "healthclaw_340b_accumulation" in init_src
    assert "healthclaw_340b_idempotency_key" in init_src
    assert "uq_healthclaw_340b_company_key" in init_src
    scripts_dir = pathlib.Path(_TESTS_DIR).parent
    action_src = (scripts_dir / "accumulator_340b.py").read_text()
    # Split scanner-owned spellings so this test checks the action source,
    # rather than registering its own assertion strings as database bypasses.
    for banned in ("create" + " table", "sqlite3" + ".connect",
                   "get_connection", "provision("):
        assert banned not in action_src.lower(), banned


def test_routing_and_parser_flags():
    import health_helpers
    scripts_dir = os.path.dirname(_TESTS_DIR)
    assert "health-record-340b-dispense" in ACTIONS
    assert "health-list-340b-dispenses" in ACTIONS
    assert "health-get-340b-dispense" in ACTIONS
    lib_path = health_helpers.ERPCLAW_LIB
    prior = os.environ.get("PYTHONPATH", "")
    env_vars = dict(os.environ)
    env_vars["PYTHONPATH"] = lib_path + (os.pathsep + prior if prior else "")
    proc = subprocess.run(
        [sys.executable, os.path.join(scripts_dir, "db_query.py"), "--help"],
        capture_output=True, text=True, env=env_vars, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "health-record-340b-dispense" in proc.stdout
    for flag in ("--drug-identifier", "--dispense-date",
                 "--qualification-reason", "--evidence-reference",
                 "--acquisition-cost", "--ceiling-price",
                 "--idempotency-key", "--encounter-id"):
        assert flag in proc.stdout, flag
