"""HealthClaw Home Health — schema initialization.

Creates 4 home-health-specific tables in the shared ERPClaw database.
Requires healthclaw core tables to exist (patient FK references).

ADR-0034 phase 2 bulk-39. Schema declared as metadata and provisioned through
`erpclaw_lib.seam`, which emits dialect-correct DDL, replacing a hand-written
``CREATE TABLE`` block opened with ``sqlite3.connect`` that could not run on
PostgreSQL at all. Conversion rules are the pilot's (`erpclaw-esign`); the one
reimbursable measure here (`mileage`) stays TEXT, because an amount is a
`Decimal` string on every backend (ADR-0034 dec. 1). `travel_time_minutes` is a
count and stays INTEGER.

This module owns only its own 4 tables. `company` and `employee` belong to
erpclaw-setup and `healthclaw_patient` to healthclaw core; all three are declared
reference-only so the foreign keys resolve and are never created here.
"""
import importlib.util
import os
import sys

# Bootstrap the shared lib only when it is not already reachable — an
# unconditional insert at position 0 overrides a caller that deliberately bound a
# different tree (ADR-0034 phase 2 step 2d).
if importlib.util.find_spec("erpclaw_lib") is None:
    sys.path.insert(0, os.path.join(os.path.expanduser(
        os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))

from erpclaw_lib.seam import (  # noqa: E402
    CheckConstraint, Column, ForeignKey, Index, Integer, MetaData, Table, Text,
    provision, reference_table, text,
)

DB_PATH = os.environ.get("ERPCLAW_DB_PATH", os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "data.sqlite"))

METADATA = MetaData()

# Foundation and healthclaw-core tables this module points at but does not own —
# declared so the foreign keys resolve, never created here. `healthclaw_patient`
# is healthclaw core's, which is why core must be installed first.
reference_table("company", METADATA)
reference_table("employee", METADATA)
reference_table("healthclaw_patient", METADATA)

# ---------------------------------------------------------------------------
# 1. healthclaw_home_visit — scheduled/completed home health visits
# ---------------------------------------------------------------------------
HOME_VISIT = Table(
    "healthclaw_home_visit", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("patient_id", Text, ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("clinician_id", Text, ForeignKey("employee.id"), nullable=False),
    Column("visit_date", Text, nullable=False),
    Column("visit_type", Text, nullable=False),
    Column("start_time", Text),
    Column("end_time", Text),
    Column("travel_time_minutes", Integer),
    Column("mileage", Text),
    Column("visit_status", Text, nullable=False, server_default=text("'scheduled'")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "visit_type IN ('skilled_nursing','pt','ot','st','aide','msw')",
        name="ck_healthclaw_home_visit_visit_type"),
    CheckConstraint(
        "visit_status IN ('scheduled','in_progress','completed','missed','cancelled')",
        name="ck_healthclaw_home_visit_visit_status"),
)

Index("idx_home_visit_patient", HOME_VISIT.c.patient_id)
Index("idx_home_visit_company", HOME_VISIT.c.company_id)
Index("idx_home_visit_clinician", HOME_VISIT.c.clinician_id)
Index("idx_home_visit_date", HOME_VISIT.c.patient_id, HOME_VISIT.c.visit_date)

# ---------------------------------------------------------------------------
# 2. healthclaw_care_plan — 485 care plans with certification periods
# ---------------------------------------------------------------------------
CARE_PLAN = Table(
    "healthclaw_care_plan", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("patient_id", Text, ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("certifying_physician_id", Text, ForeignKey("employee.id")),
    Column("start_of_care", Text, nullable=False),
    Column("certification_period_start", Text, nullable=False),
    Column("certification_period_end", Text, nullable=False),
    Column("frequency", Text),
    Column("goals", Text),
    Column("plan_status", Text, nullable=False, server_default=text("'active'")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "plan_status IN ('active','on_hold','discharged','expired','recertified')",
        name="ck_healthclaw_care_plan_plan_status"),
)

Index("idx_care_plan_patient", CARE_PLAN.c.patient_id)
Index("idx_care_plan_company", CARE_PLAN.c.company_id)
Index("idx_care_plan_status", CARE_PLAN.c.plan_status)

# ---------------------------------------------------------------------------
# 3. healthclaw_oasis_assessment — OASIS clinical assessments
# ---------------------------------------------------------------------------
OASIS_ASSESSMENT = Table(
    "healthclaw_oasis_assessment", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("patient_id", Text, ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("clinician_id", Text, ForeignKey("employee.id"), nullable=False),
    Column("assessment_type", Text, nullable=False),
    Column("assessment_date", Text, nullable=False),
    Column("m_items", Text),
    Column("notes", Text),
    Column("created_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "assessment_type IN ('soc','roc','recert','transfer','discharge','followup')",
        name="ck_healthclaw_oasis_assessment_assessment_type"),
)

Index("idx_oasis_patient", OASIS_ASSESSMENT.c.patient_id)
Index("idx_oasis_company", OASIS_ASSESSMENT.c.company_id)
Index("idx_oasis_type", OASIS_ASSESSMENT.c.assessment_type)

# ---------------------------------------------------------------------------
# 4. healthclaw_aide_assignment — home health aide scheduling
# ---------------------------------------------------------------------------
AIDE_ASSIGNMENT = Table(
    "healthclaw_aide_assignment", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("patient_id", Text, ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("aide_id", Text, ForeignKey("employee.id"), nullable=False),
    Column("assignment_start", Text, nullable=False),
    Column("assignment_end", Text),
    Column("days_of_week", Text),
    Column("visit_time", Text),
    Column("tasks", Text),
    # Both the aide and the supervising clinician are employees; the supervisor
    # is optional where the aide is not. The asymmetry is the original's.
    Column("supervisor_id", Text, ForeignKey("employee.id")),
    Column("supervision_due_date", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "status IN ('active','on_hold','completed','cancelled')",
        name="ck_healthclaw_aide_assignment_status"),
)

Index("idx_aide_assign_patient", AIDE_ASSIGNMENT.c.patient_id)
Index("idx_aide_assign_company", AIDE_ASSIGNMENT.c.company_id)
Index("idx_aide_assign_aide", AIDE_ASSIGNMENT.c.aide_id)
Index("idx_aide_assign_status", AIDE_ASSIGNMENT.c.status)


def init_homehealth_schema(db_path: str = DB_PATH) -> dict:
    """Create home health tables and indexes on whichever backend is configured.

    Same contract as before the ADR-0034 conversion: idempotent, and the returned
    counts are what was ACTUALLY created rather than what was declared.
    """
    result = provision(METADATA, db_path)

    return {
        "database": db_path,
        "tables": result["tables"],
        "indexes": result["indexes"],
    }


if __name__ == "__main__":
    result = init_homehealth_schema()
    print(f"HealthClaw Home Health schema created in {result['database']}", file=sys.stderr)
    print(f"  Tables: {result['tables']}", file=sys.stderr)
    print(f"  Indexes: {result['indexes']}", file=sys.stderr)
