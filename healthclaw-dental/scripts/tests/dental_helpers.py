"""Shared helper functions for HealthClaw Dental unit tests.

Provides:
  - DB bootstrap via init_schema.init_db() + create_healthclaw_tables() + init_dental_schema()
  - call_action() / ns() / is_error() / is_ok()
  - Seed functions for company, employee, customer, naming series, patient, encounter
  - build_env() for full test environment
  - load_db_query() for explicit module loading (avoids sys.path collisions)
"""
import argparse
import importlib.util
import io
import json
import os
import sqlite3
import sys
import uuid
from decimal import Decimal
from unittest.mock import patch

# ──────────────────────────────────────────────────────────────────────────────
# SSN encryption key for tests
# ──────────────────────────────────────────────────────────────────────────────
os.environ["ERPCLAW_FIELD_KEY"] = "test-key-for-unit-tests"

# ──────────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────────

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_DIR = os.path.dirname(TESTS_DIR)                    # scripts/
ROOT_DIR = os.path.dirname(MODULE_DIR)                     # healthclaw-dental/
PARENT_DIR = os.path.dirname(ROOT_DIR)                     # source/healthclaw/
SRC_DIR = os.path.dirname(PARENT_DIR)                      # source/

# Foundation schema init
SETUP_DIR = os.path.join(SRC_DIR, "erpclaw", "scripts", "erpclaw-setup")
INIT_SCHEMA_PATH = os.path.join(SETUP_DIR, "init_schema.py")

# Core healthclaw init
CORE_INIT_PATH = os.path.join(PARENT_DIR, "healthclaw", "init_db.py")

# Dental init
DENTAL_INIT_PATH = os.path.join(ROOT_DIR, "init_db.py")

# Make erpclaw_lib importable
ERPCLAW_LIB = os.path.expanduser("~/.openclaw/erpclaw/lib")
if ERPCLAW_LIB not in sys.path:
    sys.path.insert(0, ERPCLAW_LIB)

from erpclaw_lib.db import setup_pragmas


def load_db_query():
    """Load healthclaw-dental's db_query.py explicitly to avoid sys.path collisions."""
    db_query_path = os.path.join(MODULE_DIR, "db_query.py")
    spec = importlib.util.spec_from_file_location("db_query_dental", db_query_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Attach action functions as underscore-named attributes for convenience
    for action_name, fn in mod.ACTIONS.items():
        setattr(mod, action_name.replace("-", "_"), fn)
    return mod


# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────

def init_all_tables(db_path: str):
    """Create all foundation + core healthclaw + dental tables."""
    # 1. Foundation tables
    spec = importlib.util.spec_from_file_location("init_schema", INIT_SCHEMA_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.init_db(db_path)

    # 2. Core healthclaw tables (40 tables)
    spec2 = importlib.util.spec_from_file_location("health_init", CORE_INIT_PATH)
    m2 = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(m2)
    m2.create_healthclaw_tables(db_path)

    # 3. Dental tables (4 tables)
    spec3 = importlib.util.spec_from_file_location("dental_init", DENTAL_INIT_PATH)
    m3 = importlib.util.module_from_spec(spec3)
    spec3.loader.exec_module(m3)
    m3.init_dental_schema(db_path)


class _DecimalSum:
    """Custom SQLite aggregate: SUM using Python Decimal for precision."""
    def __init__(self):
        self.total = Decimal("0")
    def step(self, value):
        if value is not None:
            self.total += Decimal(str(value))
    def finalize(self):
        return str(self.total)


def get_conn(db_path: str) -> sqlite3.Connection:
    """Return a sqlite3.Connection with FK enabled and Row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    setup_pragmas(conn)
    conn.create_aggregate("decimal_sum", 1, _DecimalSum)
    return conn


# ──────────────────────────────────────────────────────────────────────────────
# Action invocation helpers
# ──────────────────────────────────────────────────────────────────────────────

def call_action(fn, conn, args) -> dict:
    """Invoke a domain function, capture stdout JSON, return parsed dict."""
    buf = io.StringIO()

    def _fake_exit(code=0):
        raise SystemExit(code)

    try:
        with patch("sys.stdout", buf), patch("sys.exit", side_effect=_fake_exit):
            fn(conn, args)
    except SystemExit:
        pass

    output = buf.getvalue().strip()
    if not output:
        return {"status": "error", "message": "no output captured"}
    return json.loads(output)


def ns(**kwargs) -> argparse.Namespace:
    """Build an argparse.Namespace from keyword args (mimics CLI flags)."""
    return argparse.Namespace(**kwargs)


def is_error(result: dict) -> bool:
    return result.get("status") == "error"


def is_ok(result: dict) -> bool:
    return result.get("status") == "ok"


# ──────────────────────────────────────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────────────────────────────────────

def _uuid() -> str:
    return str(uuid.uuid4())


# ──────────────────────────────────────────────────────────────────────────────
# Seed helpers
# ──────────────────────────────────────────────────────────────────────────────

def seed_company(conn, name="Test Dental Co", abbr="TDC") -> str:
    cid = _uuid()
    conn.execute(
        """INSERT INTO company (id, name, abbr, default_currency, country,
           fiscal_year_start_month)
           VALUES (?, ?, ?, 'USD', 'United States', 1)""",
        (cid, f"{name} {cid[:6]}", f"{abbr}{cid[:4]}")
    )
    conn.commit()
    return cid


def seed_employee(conn, company_id: str, name="Dr. Dental Provider") -> str:
    eid = _uuid()
    parts = name.split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""
    conn.execute(
        """INSERT INTO employee (id, first_name, last_name, full_name,
           date_of_joining, company_id, status)
           VALUES (?, ?, ?, ?, '2020-01-01', ?, 'active')""",
        (eid, first, last, name, company_id)
    )
    conn.commit()
    return eid


def seed_customer(conn, company_id: str, name="Dental Customer") -> str:
    cid = _uuid()
    conn.execute(
        """INSERT INTO customer (id, name, company_id, customer_type, status, credit_limit)
           VALUES (?, ?, ?, 'individual', 'active', '0')""",
        (cid, name, company_id)
    )
    conn.commit()
    return cid


def seed_naming_series(conn, company_id: str):
    series = [
        ("healthclaw_patient", "PAT-", 0),
        ("healthclaw_patient_insurance", "INS-", 0),
        ("healthclaw_appointment", "APPT-", 0),
        ("healthclaw_encounter", "ENC-", 0),
        ("healthclaw_prescription", "RX-", 0),
        ("healthclaw_procedure", "PROC-", 0),
        ("healthclaw_order", "ORD-", 0),
        ("healthclaw_dispensing", "DISP-", 0),
        ("healthclaw_charge", "CHG-", 0),
        ("healthclaw_claim", "CLM-", 0),
        ("healthclaw_lab_order", "LAB-", 0),
        ("healthclaw_imaging_order", "IMG-", 0),
        ("healthclaw_referral", "REF-", 0),
        ("healthclaw_prior_auth", "AUTH-", 0),
    ]
    for entity_type, prefix, current in series:
        conn.execute(
            """INSERT OR IGNORE INTO naming_series
               (id, entity_type, prefix, current_value, company_id)
               VALUES (?, ?, ?, ?, ?)""",
            (_uuid(), entity_type, prefix, current, company_id)
        )
    conn.commit()


def seed_patient(conn, company_id: str, first="Jane", last="Smith") -> str:
    pid = _uuid()
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        """INSERT INTO healthclaw_patient
           (id, naming_series, first_name, last_name, full_name,
            date_of_birth, gender, status, company_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, '1990-01-01', 'male', 'active', ?, ?, ?)""",
        (pid, f"PAT-SEED-{pid[:6]}", first, last, f"{first} {last}",
         company_id, now, now)
    )
    conn.commit()
    return pid


def seed_encounter(conn, company_id: str, patient_id: str, provider_id: str) -> str:
    eid = _uuid()
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        """INSERT INTO healthclaw_encounter
           (id, naming_series, patient_id, provider_id, encounter_date,
            encounter_type, status, company_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, '2026-01-15', 'outpatient', 'open', ?, ?, ?)""",
        (eid, f"ENC-SEED-{eid[:6]}", patient_id, provider_id,
         company_id, now, now)
    )
    conn.commit()
    return eid


def build_env(conn) -> dict:
    """Create a full dental test environment.

    Returns dict with all IDs needed for dental domain tests.
    """
    cid = seed_company(conn)
    provider = seed_employee(conn, cid, "Dr. Dental Provider")
    cust = seed_customer(conn, cid, "Dental Customer")
    seed_naming_series(conn, cid)
    patient = seed_patient(conn, cid, "Jane", "Smith")
    encounter = seed_encounter(conn, cid, patient, provider)

    return {
        "company_id": cid,
        "provider_id": provider,
        "customer_id": cust,
        "patient_id": patient,
        "encounter_id": encounter,
    }
